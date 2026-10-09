"""26 · peers: the same numbers for the closest companies in the same industry.

peers come from every market: yahoo's industry label is shared by both
sources once sec filers are tagged (ingestion.tag_industries). untagged sec
filers fall back to the sic code. closest means nearest in market cap.
"""

import json
import math

import pandas as pd

from value_investor import config, fx
from value_investor.screener import _name_key

METRICS = [
    ("gross_margin", "Gross margin", "pct"),
    ("operating_margin", "Operating margin", "pct"),
    ("roe", "ROE", "pct"),
    ("revenue_cagr", "Revenue growth", "pct"),
    ("eps_cagr_smoothed", "EPS growth", "pct"),
    ("debt_years", "Debt years", "times"),
    ("pe_now", "P/E", "num"),
    ("expected_return_base", "Return", "pct"),
]
LOWER_IS_BETTER = {"debt_years", "pe_now"}


def _known(v) -> bool:
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def _cap_usd(con, cap, currency) -> "float | None":
    if not _known(cap) or not cap:
        return None
    code, divisor = fx.major(currency)
    rate = 1.0 if code in (None, "USD") else fx.rate(con, code, "USD", fetch=False)
    return None if rate is None else cap / divisor * rate


def candidates(con, cik: int) -> "tuple[dict, pd.DataFrame]":
    rows = con.execute("""
        SELECT c.cik, c.ticker, c.name, c.market, c.industry, c.sector, c.sic, c.market_cap,
               c.price_currency, a.quality, a.f_score, a.passes_gate, a.expected_return_base
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
    """the company and its peers, each with the metrics above, plus medians and ranks."""
    me, pool = candidates(con, cik)
    if not me or pool.empty:
        return {"rows": [], "medians": {}, "ranks": {}, "basis": None}
    my_cap = _cap_usd(con, me.get("market_cap"), me.get("price_currency"))
    pool = pool.assign(cap_usd=[_cap_usd(con, c, ccy) for c, ccy in zip(pool["market_cap"], pool["price_currency"])])
    if my_cap:
        pool = pool.assign(distance=[abs(math.log(c / my_cap)) if c else 99.0 for c in pool["cap_usd"].fillna(0)])
        pool = pool.sort_values(["distance", "quality"], ascending=[True, False])
    else:
        pool = pool.sort_values("quality", ascending=False)
    keys = pool["name"].map(_name_key)
    pool = pool[(keys != _name_key(me.get("name"))) & ~keys.duplicated()].head(limit)
    me["cap_usd"] = my_cap
    rows = [_row(con, me, True)] + [_row(con, r, False) for r in pool.to_dict(orient="records")]
    medians, ranks = {}, {}
    for key, _, _ in METRICS:
        values = [r[key] for r in rows[1:] if _known(r.get(key))]
        medians[key] = float(pd.Series(values).median()) if values else None
        mine = rows[0].get(key)
        if _known(mine) and values:
            better = sum(1 for v in values if (v > mine if key in LOWER_IS_BETTER else v < mine))
            ranks[key] = {"beats": better, "of": len(values)}
    basis = "industry" if _known(me.get("industry")) and (pool["industry"] == me["industry"]).all() else "sic"
    return {"rows": rows, "medians": medians, "ranks": ranks, "basis": basis, "industry": me.get("industry")}


def _row(con, r: dict, is_me: bool) -> dict:
    payload = con.execute("SELECT payload FROM analyses WHERE cik = ?", [int(r["cik"])]).fetchone()
    p = json.loads(payload[0]) if payload else {}
    s, v = p.get("summary") or {}, p.get("valuation") or {}
    out = {"cik": int(r["cik"]), "ticker": r["ticker"], "name": r["name"], "market": r["market"],
           "me": is_me, "quality": r.get("quality"), "f_score": r.get("f_score"),
           "passes_gate": bool(r.get("passes_gate")), "cap_usd": r.get("cap_usd")}
    for key in ("gross_margin", "operating_margin", "roe", "revenue_cagr", "eps_cagr_smoothed", "debt_years"):
        out[key] = s.get(key)
    out["pe_now"] = v.get("pe_now") if v.get("available") else None
    out["expected_return_base"] = r.get("expected_return_base")
    return {k: (None if isinstance(val, float) and math.isnan(val) else val) for k, val in out.items()}
