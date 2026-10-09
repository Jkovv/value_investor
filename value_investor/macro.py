"""09 · macro: rates, Market Cap / GDP and the cash regime.

Market Cap / GDP decides how much cash to hold, never what to buy. The
ratio has drifted up for decades (more foreign profits, lower rates), so it
is read against its own long-run log trend rather than a fixed threshold;
a fixed 140% line would have kept the portfolio in cash for most of the
last ten years.

The Fed's Z.1 equity figure lags by a quarter or two, so the latest value
is carried forward with the S&P 500's move since that quarter ended.
"""

import io
import logging

import numpy as np
import pandas as pd
import requests

from value_investor import config, prices, store

logger = logging.getLogger(__name__)

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

REGIMES = [
    (-1.0, "cheap", 0.00),
    (0.5, "fair", 0.10),
    (1.5, "expensive", 0.20),
    (float("inf"), "very expensive", 0.35),
]


def fetch_series(series_id: str) -> pd.DataFrame:
    resp = requests.get(FRED_CSV.format(series=series_id), timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.dropna()


def refresh(con) -> None:
    for name, series_id in config.FRED_SERIES.items():
        try:
            store.replace_macro(con, name, fetch_series(series_id))
        except Exception as exc:
            logger.warning("FRED %s failed: %s", series_id, exc)
    prices.ensure(con, "^GSPC")


def latest(con, name: str, as_of=None) -> "tuple[float, pd.Timestamp] | tuple[None, None]":
    s = store.load_macro(con, name)
    if as_of is not None:
        s = s[s.index <= pd.Timestamp(as_of)]
    if s.empty:
        return None, None
    return float(s.iloc[-1]), s.index[-1]


def market_cap_to_gdp(con, as_of=None) -> "dict | None":
    equities = store.load_macro(con, "corporate_equities")
    gdp = store.load_macro(con, "gdp")
    if equities.empty or gdp.empty:
        return None
    # FRED stamps quarterly series with the first day of the quarter, but the
    # Z.1 equity level is measured at quarter end. Date it where it belongs, or
    # the S&P roll-forward below starts three months too early.
    ratio = (equities / 1000.0 / gdp.reindex(equities.index, method="ffill")).dropna()
    ratio.index = ratio.index + pd.offsets.QuarterEnd(0)
    if as_of is not None:
        ratio = ratio[ratio.index <= pd.Timestamp(as_of)]
    if len(ratio) < 40:
        return None

    value, value_date = float(ratio.iloc[-1]), ratio.index[-1]
    spx = prices.until(store.load_prices(con, "^GSPC").assign(date=lambda d: pd.to_datetime(d["date"])), as_of)
    spx = spx.dropna(subset=["close"])
    if not spx.empty:
        then = spx[spx["date"] <= value_date]
        if not then.empty:
            value *= float(spx["close"].iloc[-1]) / float(then["close"].iloc[-1])
            value_date = spx["date"].iloc[-1]

    years = (ratio.index - ratio.index[0]).days / 365.25
    logs = np.log(ratio.values)
    slope, intercept = np.polyfit(years, logs, 1)
    residual_std = float(np.std(logs - (slope * years + intercept)))
    now_years = (pd.Timestamp(value_date) - ratio.index[0]).days / 365.25
    trend = float(np.exp(slope * now_years + intercept))
    z = (np.log(value) - np.log(trend)) / residual_std

    for upper, label, cash in REGIMES:
        if z < upper:
            break
    history = pd.DataFrame({"ratio": ratio, "trend": np.exp(slope * years + intercept)}, index=ratio.index)
    if pd.Timestamp(value_date) > history.index[-1]:
        history.loc[pd.Timestamp(value_date)] = [value, trend]
    return {
        "value": value, "date": pd.Timestamp(value_date).date(), "trend": trend, "z": float(z),
        "regime": label, "suggested_cash": cash,
        "history": history,
    }


def sahm_rule(con, as_of=None) -> "float | None":
    u = store.load_macro(con, "unemployment")
    if as_of is not None:
        u = u[u.index <= pd.Timestamp(as_of)]
    if len(u) < 15:
        return None
    avg3 = u.rolling(3).mean()
    return float(avg3.iloc[-1] - avg3.iloc[-13:-1].min())


def snapshot(con, as_of=None) -> dict:
    ten, ten_date = latest(con, "treasury_10y", as_of)
    two, _ = latest(con, "treasury_2y", as_of)
    vix, _ = latest(con, "vix", as_of)
    mc = market_cap_to_gdp(con, as_of)
    if mc:
        mc = {k: v for k, v in mc.items() if k != "history"}
    sahm = sahm_rule(con, as_of)
    return {
        "treasury_10y": None if ten is None else ten / 100.0,
        "treasury_10y_date": ten_date,
        "yield_curve": None if ten is None or two is None else (ten - two) / 100.0,
        "vix": vix,
        "sahm": sahm,
        "recession_warning": sahm is not None and sahm >= 0.5,
        "market_cap_to_gdp": mc,
    }
