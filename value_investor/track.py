"""27 · track: did the ranking work? a forward test, not a backtest.

each full screen saves the ranking. its top ten are bought on paper at that
day's close, equal weight, and marked to today with dividends in the base
currency, against the MSCI All Country World ETF and each pick's own market.
"""

from datetime import date

import pandas as pd

from value_investor import config, fx, markets, store


def take(con, ranked: pd.DataFrame, taken_on=None) -> int:
    """save today's ranking (gate passers with a price, best first)."""
    taken_on = taken_on or date.today()
    ranked = ranked[ranked["expected_return"].notna() & ranked["price"].notna()].reset_index(drop=True)
    rows = [(i + 1, int(r["cik"]), r["ticker"], r["name"], r["market"], r["currency"], float(r["price"]),
             None if pd.isna(r["buy_price"]) else float(r["buy_price"]),
             None if pd.isna(r["expected_return_base"]) else float(r["expected_return_base"]), float(r["quality"]))
            for i, r in ranked.iterrows()]
    store.save_snapshot(con, taken_on, rows)
    return len(rows)


def _closes(con, ticker: str) -> pd.DataFrame:
    frame = store.load_prices(con, ticker)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.dropna(subset=["close"]).set_index("date")


def holding_return(con, ticker: str, start, currency: "str | None", base: str = config.BASE_CURRENCY,
                   end=None) -> "dict | None":
    """total return from the close on (or just before) start, with dividends, local and in base."""
    p = _closes(con, ticker)
    if p.empty:
        return None
    start, end = pd.Timestamp(start), pd.Timestamp(end) if end is not None else p.index[-1]
    before = p[p.index <= start]
    if before.empty:
        return None
    first = float(before["close"].iloc[-1])
    window = p[(p.index > before.index[-1]) & (p.index <= end)]
    if window.empty or first <= 0:
        return {"local": 0.0, "base": 0.0, "days": 0}
    last = float(window["close"].iloc[-1])
    local = (last + float(window["dividend"].fillna(0).sum())) / first - 1
    code = fx.major(currency)[0]
    if code == base:
        in_base = local
    else:
        then = fx.rate(con, code, base, when=before.index[-1], fetch=False)
        now = fx.rate(con, code, base, when=window.index[-1], fetch=False)
        in_base = None if not then or not now else (1 + local) * now / then - 1
    return {"local": local, "base": in_base, "days": (window.index[-1] - before.index[-1]).days,
            "end": window.index[-1].date()}


def record(con, top: int = config.TRACK_TOP) -> dict:
    snaps = store.snapshots(con)
    if snaps.empty:
        return {"snapshots": [], "summary": {}}
    out = []
    for taken_on, group in snaps.groupby("taken_on", sort=True):
        picks = []
        for r in group.sort_values("rank").head(top).itertuples():
            ret = holding_return(con, r.ticker, taken_on, r.currency)
            proxy = markets.BY_ISO.get(r.market).proxy if r.market in markets.BY_ISO else None
            vs = holding_return(con, proxy, taken_on, markets.BY_ISO[r.market].proxy_currency) if proxy else None
            picks.append({
                "rank": int(r.rank), "ticker": r.ticker, "name": r.name, "market": r.market,
                "price": r.price, "currency": r.currency, "expected": r.expected_return_base,
                "return": None if ret is None else ret["base"],
                "local": None if ret is None else ret["local"],
                "market_return": None if vs is None else vs["local"],
            })
        days = (pd.Timestamp.today().normalize() - pd.Timestamp(taken_on)).days
        if days == 0:
            # bought today at today's close: nothing to measure yet
            for p in picks:
                p["return"] = p["local"] = p["market_return"] = None
        known = [p["return"] for p in picks if p["return"] is not None]
        world = holding_return(con, config.BENCHMARK, taken_on, "USD") if days else None
        portfolio = sum(known) / len(known) if known else None
        beat_market = [p for p in picks if p["local"] is not None and p["market_return"] is not None]
        out.append({
            "taken_on": pd.Timestamp(taken_on).date(), "picks": picks, "priced": len(known),
            "portfolio": portfolio, "benchmark": None if world is None else world["base"],
            "excess": None if portfolio is None or world is None or world["base"] is None
            else portfolio - world["base"],
            "hit_rate": sum(p["local"] > p["market_return"] for p in beat_market) / len(beat_market)
            if beat_market else None,
            "days": days,
            "size": len(group),
        })
    scored = [s for s in out if s["excess"] is not None and s["days"] >= 7]
    summary = {
        "snapshots": len(out), "first": out[0]["taken_on"], "last": out[-1]["taken_on"],
        "scored": len(scored),
        "avg_excess": sum(s["excess"] for s in scored) / len(scored) if scored else None,
        "beat_share": sum(s["excess"] > 0 for s in scored) / len(scored) if scored else None,
    }
    return {"snapshots": out[::-1], "summary": summary}
