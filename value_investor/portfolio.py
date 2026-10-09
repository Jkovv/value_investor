"""28 · portfolio: positions in their own currency, totals in the base one.

trades live in a small sqlite file because the dashboard holds duckdb
read-only. the plan sizes by expected return and quality, caps positions and
clusters of related ones, and keeps the cash each market's regime asks for.
"""

import sqlite3
from contextlib import closing
from datetime import date

import numpy as np
import pandas as pd

from value_investor import config, fx, store

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    traded_on TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('buy', 'sell')),
    shares REAL NOT NULL CHECK (shares > 0),
    price REAL NOT NULL CHECK (price >= 0),
    fees REAL NOT NULL DEFAULT 0,
    note TEXT
)"""


def _db() -> sqlite3.Connection:
    config.PORTFOLIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.PORTFOLIO_PATH)
    conn.execute(SCHEMA)
    return conn


def add(ticker: str, traded_on: str, kind: str, shares: float, price: float, fees: float = 0.0,
        note: "str | None" = None) -> int:
    with closing(_db()) as conn, conn:
        cur = conn.execute("INSERT INTO transactions (ticker, traded_on, kind, shares, price, fees, note) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)",
                           [ticker.upper(), traded_on, kind, shares, price, fees or 0.0, note or None])
        return int(cur.lastrowid)


def delete(tx_id: int) -> None:
    with closing(_db()) as conn, conn:
        conn.execute("DELETE FROM transactions WHERE id = ?", [tx_id])


def transactions() -> pd.DataFrame:
    with closing(_db()) as conn:
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY traded_on, id", conn)
    df["traded_on"] = pd.to_datetime(df["traded_on"])
    return df


def tickers() -> list:
    df = transactions()
    return sorted(df["ticker"].unique()) if not df.empty else []


def _prices(con, ticker: str, currency: "str | None") -> pd.DataFrame:
    frame = store.load_prices(con, ticker)
    if frame.empty:
        return frame
    frame["date"] = pd.to_datetime(frame["date"])
    frame, _ = fx.to_major(frame.dropna(subset=["close"]), currency)
    return frame.set_index("date")


def xirr(flows: list) -> "float | None":
    """yearly rate that makes the dated cash flows sum to zero (bisection).
    none under 90 days: a week's move annualised says nothing."""
    flows = [(pd.Timestamp(d), a) for d, a in flows if a]
    if not any(a < 0 for _, a in flows) or not any(a > 0 for _, a in flows):
        return None
    t0 = min(d for d, _ in flows)
    if (max(d for d, _ in flows) - t0).days < 90:
        return None

    def npv(rate):
        return sum(a / (1 + rate) ** ((d - t0).days / 365.25) for d, a in flows)

    lo, hi = -0.99, 10.0
    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


def _position(con, ticker: str, trades: pd.DataFrame, company: dict, base: str) -> dict:
    ccy = fx.major(company.get("price_currency") or company.get("currency") or base)[0]
    prices = _prices(con, ticker, company.get("price_currency"))
    shares = cost = invested = invested_base = received = received_base = 0.0
    flows = []
    held_after = []
    for t in trades.itertuples():
        rate = fx.rate(con, ccy, base, when=t.traded_on, fetch=False) if ccy != base else 1.0
        rate = rate or np.nan
        amount = t.shares * t.price
        if t.kind == "buy":
            outlay = amount + t.fees
            shares += t.shares
            cost += outlay
            invested += outlay
            invested_base += outlay * rate
            flows.append((t.traded_on, -outlay * rate))
        else:
            sold = min(t.shares, shares)
            cost -= cost * sold / shares if shares else 0.0
            shares -= sold
            proceeds = amount - t.fees
            received += proceeds
            received_base += proceeds * rate
            flows.append((t.traded_on, proceeds * rate))
        held_after.append((t.traded_on, shares))

    dividends = dividends_base = 0.0
    if not prices.empty and held_after:
        paid = prices[prices["dividend"].fillna(0) > 0]
        for when, per_share in paid["dividend"].items():
            held = [n for d, n in held_after if d < when]
            if not held or held[-1] <= 0:
                continue
            cash = held[-1] * per_share
            rate = fx.rate(con, ccy, base, when=when, fetch=False) if ccy != base else 1.0
            dividends += cash
            dividends_base += cash * (rate or np.nan)
            flows.append((when, cash * (rate or np.nan)))

    last = None if prices.empty else float(prices["close"].iloc[-1])
    last_date = None if prices.empty else prices.index[-1].date()
    rate_now = fx.rate(con, ccy, base, fetch=False) if ccy != base else 1.0
    value = shares * last if last is not None else None
    value_base = value * rate_now if value is not None and rate_now else None
    gain = None if value is None else value + received + dividends - invested
    gain_base = None if value_base is None else value_base + received_base + dividends_base - invested_base
    out = {
        "ticker": ticker, "name": company.get("name") or ticker, "market": company.get("market"),
        "industry": company.get("industry"), "currency": ccy, "shares": shares,
        "avg_cost": cost / shares if shares else None, "price": last, "price_date": last_date,
        "value": value, "value_base": value_base, "invested_base": invested_base,
        "dividends": dividends, "dividends_base": dividends_base, "gain_base": gain_base,
        "return_local": gain / invested if gain is not None and invested else None,
        "return_base": gain_base / invested_base if gain_base is not None and invested_base else None,
        "flows": flows,
    }
    if out["return_local"] is not None and out["return_base"] is not None:
        out["fx_effect"] = out["return_base"] - out["return_local"]
    return out


def positions(con, base: str = config.BASE_CURRENCY) -> dict:
    tx = transactions()
    if tx.empty:
        return {"rows": [], "totals": {}, "transactions": []}
    rows = []
    for ticker, trades in tx.groupby("ticker"):
        cik = store.find_cik(con, ticker)
        company = (store.company(con, cik) or {}) if cik else {}
        rows.append(_position(con, ticker, trades.sort_values(["traded_on", "id"]), company, base))
    open_rows = [r for r in rows if r["shares"] > 1e-9]
    unpriced = {r["ticker"] for r in open_rows if r["value_base"] is None}
    counted = [r for r in rows if r["ticker"] not in unpriced]
    value = sum(r["value_base"] or 0 for r in open_rows)
    for r in open_rows:
        r["weight"] = (r["value_base"] or 0) / value if value else None
    flows = [f for r in rows for f in r.pop("flows") if r["ticker"] not in unpriced and not np.isnan(f[1])]
    if value:
        flows.append((pd.Timestamp(date.today()), value))
    invested = sum(r["invested_base"] for r in counted)
    gain = sum(r["gain_base"] or 0 for r in counted)
    totals = {
        "value": value, "invested": invested, "gain": gain,
        "return": gain / invested if invested else None,
        "dividends": sum(r["dividends_base"] for r in counted if not np.isnan(r["dividends_base"])),
        "xirr": xirr(flows), "positions": len(open_rows), "closed": len(rows) - len(open_rows),
        "missing_prices": sorted(unpriced),
    }
    exposure = {}
    for key in ("currency", "market"):
        groups: dict = {}
        for r in open_rows:
            groups[r[key] or "?"] = groups.get(r[key] or "?", 0) + (r["value_base"] or 0)
        exposure[key] = sorted(((k, v / value if value else 0) for k, v in groups.items()), key=lambda kv: -kv[1])
    records = tx.assign(traded_on=tx["traded_on"].dt.date).sort_values(["traded_on", "id"], ascending=False)
    return {"rows": sorted(rows, key=lambda r: -(r["value_base"] or 0)), "totals": totals,
            "exposure": exposure, "transactions": records.to_dict(orient="records")}


def _weekly_returns(con, tickers: list) -> pd.DataFrame:
    series = {}
    for t in tickers:
        p = store.load_prices(con, t)
        if p.empty:
            continue
        s = p.dropna(subset=["close"]).set_index(pd.to_datetime(p.dropna(subset=["close"])["date"]))["close"]
        series[t] = s.resample("W-FRI").last().pct_change().tail(156)
    return pd.DataFrame(series)


def clusters(con, tickers: list, industries: dict) -> dict:
    """ticker -> cluster label. related means same industry or weekly correlation above the link."""
    parent = {t: t for t in tickers}

    def root(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    def join(a, b):
        parent[root(a)] = root(b)

    corr = _weekly_returns(con, tickers).corr(min_periods=52)
    for i, a in enumerate(tickers):
        for b in tickers[i + 1:]:
            same = industries.get(a) and industries.get(a) == industries.get(b)
            linked = a in corr and b in corr and corr.loc[a, b] > config.CORRELATION_LINK
            if same or linked:
                join(a, b)
    groups: dict = {}
    for t in tickers:
        groups.setdefault(root(t), []).append(t)
    return {t: sorted(groups[root(t)])[0] for t in tickers}


def _capped(scores: dict, cluster_of: dict) -> dict:
    """spread 100% by score, cap positions and clusters, hand the overflow to the rest."""
    weights = {t: 0.0 for t in scores}
    free = {t for t, s in scores.items() if s > 0}
    left = 1.0
    for _ in range(50):
        if not free or left <= 1e-9:
            break
        total = sum(scores[t] for t in free)
        for t in free:
            weights[t] += left * scores[t] / total
        left = 0.0
        for t in list(free):
            if weights[t] > config.POSITION_CAP:
                left += weights[t] - config.POSITION_CAP
                weights[t] = config.POSITION_CAP
                free.discard(t)
        for label in set(cluster_of.values()):
            members = [t for t in weights if cluster_of[t] == label]
            size = sum(weights[t] for t in members)
            if size > config.CLUSTER_CAP + 1e-9:
                scale = config.CLUSTER_CAP / size
                for t in members:
                    left += weights[t] * (1 - scale)
                    weights[t] *= scale
                    free.discard(t)
    return weights


def plan(con, held: list, ranked: pd.DataFrame, readings: dict, extra: int = 15) -> dict:
    """target weights for what's held plus the best of the ranking."""
    held_weights = {r["ticker"]: r.get("weight") or 0.0 for r in held}
    pool = ranked[ranked["expected_return_base"].notna()]
    best = pool[pool["expected_return_base"] >= config.MIN_RETURN_TO_HOLD].head(extra)
    rows = {r.ticker: r._asdict() for r in pool[pool["ticker"].isin(list(held_weights))].itertuples()}
    rows |= {r.ticker: r._asdict() for r in best.itertuples() if r.ticker not in rows}
    names = dict(con.execute("SELECT ticker, name FROM companies").fetchall())
    markets_of = dict(con.execute("SELECT ticker, market FROM companies").fetchall())
    for t in held_weights:
        rows.setdefault(t, {"ticker": t, "name": names.get(t, t), "market": markets_of.get(t), "quality": None,
                            "expected_return_base": None})
    if not rows:
        return {"rows": [], "cash": 1.0}
    industry = dict(con.execute("SELECT ticker, industry FROM companies WHERE industry IS NOT NULL").fetchall())
    cluster_of = clusters(con, list(rows), industry)
    scores, cash_of = {}, {}
    for t, r in rows.items():
        er, q = r.get("expected_return_base"), r.get("quality")
        reading = readings.get(r.get("market")) or {}
        cash_of[t] = reading.get("suggested_cash") or 0.0
        if er is None or q is None or pd.isna(er):
            scores[t] = 0.0
        else:
            scores[t] = max(er - config.MIN_RETURN_TO_HOLD, 0.0) * q / 100
    weights = _capped(scores, cluster_of)
    # every market's suggested cash comes off its own positions
    weights = {t: w * (1 - cash_of[t]) for t, w in weights.items()}
    out = []
    for t, r in rows.items():
        now, target = held_weights.get(t, 0.0), weights[t]
        if t in held_weights and target <= 0.005:
            action = "sell"
        elif t not in held_weights:
            action = "buy" if target > 0.005 else None
        elif target > now + 0.02:
            action = "add"
        elif target < now - 0.02:
            action = "trim"
        else:
            action = "hold"
        if action:
            out.append({"ticker": t, "name": r.get("name"), "market": r.get("market"),
                        "quality": r.get("quality"), "expected": r.get("expected_return_base"),
                        "cluster": cluster_of[t], "cluster_size": sum(1 for c in cluster_of.values() if c == cluster_of[t]),
                        "now": now, "target": target, "action": action, "held": t in held_weights})
    out.sort(key=lambda r: -r["target"])
    return {"rows": out, "cash": max(0.0, 1 - sum(weights.values()))}
