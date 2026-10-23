"""36 · audit: how far each history source agrees with another, line by line.

every source that adds years outside the us is compared with yahoo finance on the
years both report. the share of years within 2% is how much a line from that source
can be trusted; lines that rarely agree are left out of the source itself (irbank's
debt, dart's sg&a). the result goes to data/audit.json for the data page.
"""

import json
import logging
from datetime import datetime

import numpy as np
import pandas as pd

from value_investor import concepts, config, markets, statements, store

logger = logging.getLogger(__name__)

PATH = config.DATA_DIR / "audit.json"
LINES = ["revenue", "operating_income", "net_income", "eps_diluted", "total_assets", "equity", "retained_earnings",
         "cash", "operating_cash_flow", "capex", "dividends_paid", "long_term_debt"]
CLOSE, NEAR = 0.02, 0.10
SHOWN = [("net_income", "Net income"), ("revenue", "Revenue"), ("total_assets", "Assets"), ("equity", "Equity"),
         ("operating_cash_flow", "Op. cash flow"), ("capex", "Capex"), ("eps_diluted", "EPS")]
NAMES = {"eastmoney": "EastMoney", "finmind": "FinMind", "screener": "Screener.in", "eastmoney-hk": "EastMoney HK",
         "cvm": "CVM", "biznesradar": "Biznesradar", "irbank": "IRBANK", "dart": "DART", "sec": "SEC 20-F / 40-F",
         "sec-foreign": "SEC 20-F / 40-F", "yahoo": "Yahoo Finance"}


def deviations(facts: pd.DataFrame) -> list:
    """(source, line, period end, gap) for every line and year a source shares with yahoo,
    the gap being |theirs / yahoo's - 1|. sources in another currency are skipped."""
    yahoo = facts[facts["taxonomy"] == "yahoo"]
    base = statements.annual_statements(yahoo) if not yahoo.empty else pd.DataFrame()
    if base.empty:
        return []
    groups = {t: facts[facts["taxonomy"] == t] for t in concepts.CANONICAL if (facts["taxonomy"] == t).any()}
    sec = facts[facts["taxonomy"].isin(["us-gaap", "ifrs-full"])]
    if not sec.empty:
        groups["sec"] = sec
    out = []
    for source, part in groups.items():
        theirs = statements.annual_statements(part)
        if theirs.empty or theirs.attrs.get("currency") != base.attrs.get("currency"):
            continue
        by_month = {(e.year, e.month): e for e in theirs.index}
        for end in base.index:
            other = by_month.get((end.year, end.month))
            if other is None:
                continue
            for line in LINES:
                a, b = base.at[end, line], theirs.at[other, line]
                if pd.notna(a) and pd.notna(b) and a:
                    out.append((source, line, end.date(), abs(float(b) / float(a) - 1)))
    return out


def summarise(rows: list) -> list:
    """rows of (cik, market, source, line, end, gap) -> one entry per source."""
    if not rows:
        return []
    df = pd.DataFrame(rows, columns=["cik", "market", "source", "line", "end", "gap"])
    out = []
    for source, part in df.groupby("source"):
        lines = {}
        for line, g in part.groupby("line"):
            gaps = g["gap"].to_numpy()
            lines[line] = {"pairs": int(len(gaps)), "close": float(np.mean(gaps <= CLOSE)),
                           "near": float(np.mean(gaps <= NEAR)), "median_gap": float(np.median(gaps))}
        out.append({"source": source, "name": NAMES.get(source, source), "companies": int(part["cik"].nunique()),
                    "markets": sorted(part["market"].dropna().unique().tolist()), "lines": lines})
    return sorted(out, key=lambda s: -s["companies"])


def coverage(con) -> list:
    """per market: companies, how many have ten years, and which sources the years come from."""
    rows = con.execute("""
        SELECT c.market, count(*) AS companies, sum(CASE WHEN a.history_years >= ? THEN 1 ELSE 0 END) AS ten,
               median(a.history_years) AS median_years
        FROM analyses a JOIN companies c USING (cik) WHERE c.market IS NOT NULL GROUP BY 1
    """, [config.HISTORY_YEARS]).fetchall()
    sources = con.execute("""
        SELECT c.market, f.taxonomy, count(DISTINCT f.cik) FROM facts f JOIN companies c USING (cik)
        WHERE c.market IS NOT NULL GROUP BY 1, 2
    """).fetchall()
    by_market: dict = {}
    for market, taxonomy, n in sources:
        name = "sec" if taxonomy in ("us-gaap", "ifrs-full") else taxonomy
        by_market.setdefault(market, {})
        by_market[market][name] = max(by_market[market].get(name, 0), int(n))
    out = []
    for market, companies, ten, median_years in rows:
        m = markets.BY_ISO.get(market)
        out.append({"market": market, "name": m.name if m else market, "companies": int(companies),
                    "ten_years": int(ten or 0), "median_years": float(median_years or 0),
                    "sources": by_market.get(market, {})})
    return sorted(out, key=lambda r: -r["companies"])


def freshness(con) -> list:
    rows = con.execute("""
        SELECT source, count(*), sum(CASE WHEN years > 0 THEN 1 ELSE 0 END), max(years), max(fetched_at)
        FROM source_fetches GROUP BY 1 ORDER BY 2 DESC
    """).fetchall()
    return [{"source": s, "name": NAMES.get(s, s), "companies": int(n), "with_years": int(w or 0),
             "most_years": int(y or 0), "last_fetch": str(f)[:16] if f else None} for s, n, w, y, f in rows]


def run(con) -> dict:
    todo = con.execute("""
        SELECT DISTINCT f.cik, c.market FROM facts f JOIN companies c USING (cik)
        WHERE c.source = 'yahoo' AND f.taxonomy <> 'yahoo'
    """).fetchall()
    rows = []
    for i, (cik, market) in enumerate(todo, start=1):
        try:
            rows += [(cik, market) + d for d in deviations(store.load_facts(con, cik))]
        except Exception as exc:
            logger.warning("audit failed for CIK %s: %s", cik, exc)
        if i % 500 == 0:
            logger.info("audit: %d / %d companies", i, len(todo))
    return {"run_at": datetime.now().isoformat(timespec="minutes"), "companies_checked": len(todo),
            "sources": summarise(rows), "markets": coverage(con), "freshness": freshness(con)}


def save(result: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")


def load() -> "dict | None":
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
