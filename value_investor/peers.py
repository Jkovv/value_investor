"""26 · peers: the closest competitors in the same industry, and where the company stands among them.

competitors come from every market: yahoo's industry label is shared by both
sources once sec filers are tagged (ingestion.tag_industries); untagged sec
filers fall back to the sic code. closest means nearest in market cap.
"""

import json
import math

import pandas as pd

from value_investor import config, fx
from value_investor.screener import _name_key

# key, label, format, which way is better, group
METRICS = [
    ("quality", "Quality score", "int", "high", "Quality"),
    ("f_score", "Piotroski F-score", "int", "high", "Quality"),
    ("gross_margin", "Gross margin", "pct", "high", "Profitability"),
    ("operating_margin", "Operating margin", "pct", "high", "Profitability"),
    ("net_margin", "Net margin", "pct", "high", "Profitability"),
    ("roe", "Return on equity", "pct", "high", "Profitability"),
    ("roa", "Return on assets", "pct", "high", "Profitability"),
    ("return_on_capital", "Return on capital", "pct", "high", "Profitability"),
    ("revenue_cagr", "Revenue growth a year", "pct", "high", "Growth"),
    ("eps_cagr_smoothed", "EPS growth a year", "pct", "high", "Growth"),
    ("revenue_yoy", "Revenue, last quarter vs a year ago", "pct", "high", "Growth"),
    ("debt_years", "Years of earnings to repay debt", "times", "low", "Balance sheet"),
    ("current_ratio", "Current ratio", "times", "high", "Balance sheet"),
    ("altman_z", "Altman Z-score", "num", "high", "Balance sheet"),
    ("pe_now", "P/E", "num", "low", "Price"),
    ("earnings_yield", "Earnings yield (EBIT / EV)", "pct", "high", "Price"),
    ("dividend_yield", "Dividend yield", "pct", "high", "Price"),
    ("margin_of_safety", "Margin of safety", "pct", "high", "Price"),
    ("expected_return", "Expected return a year", "pct", "high", "Price"),
]
GROUPS = ["Quality", "Profitability", "Growth", "Balance sheet", "Price"]


def _known(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _cap_usd(con, cap, currency, rates: "dict | None" = None) -> "float | None":
    if not _known(cap) or not cap:
        return None
    # yahoo gives market cap in the major unit even when the price is in pence or cents
    code = fx.major(currency)[0]
    if code in (None, "USD"):
        return float(cap)
    if rates is None or code not in rates:
        rate = fx.rate(con, code, "USD", fetch=False)
        if rates is not None:
            rates[code] = rate
    else:
        rate = rates[code]
    return None if rate is None else cap * rate


def candidates(con, cik: int) -> "tuple[dict, pd.DataFrame]":
    rows = con.execute("""
        SELECT c.cik, c.ticker, c.name, c.market, c.industry, c.sector, c.sic, c.market_cap,
               c.price_currency, a.quality, a.f_score, a.passes_gate, a.expected_return
        FROM companies c JOIN analyses a USING (cik)""").df()
    me = rows[rows["cik"] == cik]
    if me.empty:
        return {}, rows.iloc[0:0]
    me = me.iloc[0].to_dict()
    others = rows[rows["cik"] != cik]
    pool = others.iloc[0:0]
    if _known(me.get("industry")):
        pool = others[others["industry"] == me["industry"]]
    if len(pool) < 3 and _known(me.get("sic")):
        for digits in (4, 3, 2):
            code = str(int(me["sic"])).zfill(4)[:digits]
            pool = others[others["sic"].fillna(0).astype(int).astype(str).str.zfill(4).str[:digits] == code]
            if len(pool) >= 3:
                break
    return me, pool


def find(con, cik: int, limit: int = config.PEERS_SHOWN) -> dict:
    """the company and its closest competitors, every metric, and where it ranks on each."""
    empty = {"rows": [], "metrics": [], "sheet": [], "basis": None}
    me, pool = candidates(con, cik)
    if not me or pool.empty:
        return empty
    rates: dict = {}
    my_cap = _cap_usd(con, me.get("market_cap"), me.get("price_currency"), rates)
    pool = pool.assign(cap_usd=[_cap_usd(con, c, ccy, rates) for c, ccy in zip(pool["market_cap"], pool["price_currency"])])
    if my_cap:
        pool = pool.assign(distance=[abs(math.log(c / my_cap)) if c else 99.0 for c in pool["cap_usd"].fillna(0)])
        pool = pool.sort_values(["distance", "quality"], ascending=[True, False])
    else:
        pool = pool.sort_values("quality", ascending=False)
    keys = pool["name"].map(_name_key)
    pool = pool[(keys != _name_key(me.get("name"))) & ~keys.duplicated()].head(limit)
    if pool.empty:
        return empty
    me["cap_usd"] = my_cap
    rows = [_row(con, me, True)] + [_row(con, r, False) for r in pool.to_dict(orient="records")]
    metrics = [standing(rows, m) for m in METRICS]
    ranked = [m for m in metrics if m["rank"] is not None]
    by_place = sorted(ranked, key=lambda m: (m["rank"] - 1) / max(m["of"] - 1, 1))
    basis = "industry" if _known(me.get("industry")) and (pool["industry"] == me["industry"]).all() else "sic"
    return {
        "rows": rows, "metrics": ranked,
        "sheet": [(g, [m for m in metrics if m["group"] == g and m["values"]]) for g in GROUPS],
        "basis": basis, "industry": me.get("industry"), "markets": len({r["market"] for r in rows[1:]}),
        "ahead": sum(1 for m in ranked if m["ahead"]), "compared": len(ranked),
        "strengths": [m for m in by_place[:3] if m["rank"] <= max(2, m["of"] // 3)],
        "weaknesses": [m for m in by_place[::-1][:3] if m["rank"] > m["of"] - max(2, m["of"] // 3)],
    }


def standing(rows: list, metric: tuple) -> dict:
    """one metric across the company and its competitors: values, rank, median and dot positions."""
    key, label, kind, better, group = metric
    values = {r["ticker"]: r[key] for r in rows if _known(r.get(key))}
    me = rows[0]["ticker"]
    out = {"key": key, "label": label, "kind": kind, "better": better, "group": group, "values": values,
           "mine": values.get(me), "rank": None, "of": len(values), "median": None, "ahead": False,
           "best": None, "dots": []}
    peers = [v for t, v in values.items() if t != me]
    if peers:
        out["median"] = float(pd.Series(peers).median())
    if values:
        out["best"] = (max if better == "high" else min)(values, key=values.get)
    if out["mine"] is None or len(peers) < 2:
        return out
    mine = out["mine"]
    worse_or_equal = [v for v in values.values() if (v <= mine if better == "high" else v >= mine)]
    out["rank"] = len(values) - len(worse_or_equal) + 1
    out["ahead"] = mine > out["median"] if better == "high" else mine < out["median"]
    # positions run from worst (0) to best (1); the outer tenth is clipped so one outlier
    # doesn't squash everyone else into a corner
    series = pd.Series(list(values.values()))
    lo, hi = float(series.quantile(0.1)), float(series.quantile(0.9))
    pad = (hi - lo) * 0.15 or abs(hi) * 0.1 or 1.0
    lo, hi = lo - pad, hi + pad

    def place(v):
        x = min(max((v - lo) / (hi - lo), 0.0), 1.0)
        return x if better == "high" else 1 - x

    out["dots"] = [{"ticker": t, "x": place(v), "value": v, "me": t == me} for t, v in values.items()]
    out["dots"].sort(key=lambda d: d["me"])          # the company drawn last, on top
    out["median_x"] = place(out["median"])
    return out


def _row(con, r: dict, is_me: bool) -> dict:
    payload = con.execute("SELECT payload FROM analyses WHERE cik = ?", [int(r["cik"])]).fetchone()
    p = json.loads(payload[0]) if payload else {}
    s, v = p.get("summary") or {}, p.get("valuation") or {}
    lenses, quarters = p.get("lenses") or {}, (p.get("quarters") or {}).get("summary") or {}
    priced = bool(v.get("available"))
    out = {"cik": int(r["cik"]), "ticker": r["ticker"], "name": r["name"], "market": r["market"],
           "me": is_me, "passes_gate": bool(r.get("passes_gate")), "cap_usd": r.get("cap_usd"),
           "quality": r.get("quality"), "f_score": r.get("f_score")}
    for key in ("gross_margin", "operating_margin", "net_margin", "roe", "roa", "revenue_cagr",
                "eps_cagr_smoothed", "debt_years", "current_ratio"):
        out[key] = s.get(key)
    out["return_on_capital"] = (lenses.get("magic") or {}).get("return_on_capital")
    out["earnings_yield"] = (lenses.get("magic") or {}).get("earnings_yield")
    out["altman_z"] = (lenses.get("altman") or {}).get("z")
    out["revenue_yoy"] = quarters.get("revenue_yoy")
    out["pe_now"] = v.get("pe_now") if priced and (v.get("pe_now") or 0) > 0 else None
    out["dividend_yield"] = v.get("dividend_yield") if priced else None
    out["margin_of_safety"] = v.get("margin_of_safety") if priced else None
    out["expected_return"] = r.get("expected_return")
    return {k: (None if isinstance(val, float) and math.isnan(val) else val) for k, val in out.items()}
