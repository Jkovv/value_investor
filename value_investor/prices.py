"""08 · prices — daily prices, dividends and splits from yfinance.

Close is split-adjusted but not dividend-adjusted, which is what P/E needs:
the same share units as today's EPS, without dividends folded into price.
Prices are cached in DuckDB and refetched at most once a day.
"""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from value_investor import store

logger = logging.getLogger(__name__)

MAX_AGE = timedelta(hours=20)
EMPTY = pd.DataFrame(columns=["date", "high", "low", "close", "dividend", "split"])


def fetch(ticker: str) -> pd.DataFrame:
    hist = yf.Ticker(ticker).history(period="max", auto_adjust=False, actions=True)
    if hist.empty:
        return EMPTY.copy()
    hist = hist.reset_index()
    return pd.DataFrame({
        "date": pd.to_datetime(hist["Date"]).dt.tz_localize(None).dt.date,
        "high": hist["High"].astype(float),
        "low": hist["Low"].astype(float),
        "close": hist["Close"].astype(float),
        "dividend": hist.get("Dividends", 0.0),
        "split": hist.get("Stock Splits", 0.0),
    })


def ensure(con, ticker: str, refresh: bool = False) -> pd.DataFrame:
    fetched_at = store.price_fetched_at(con, ticker)
    stale = fetched_at is None or datetime.now() - fetched_at > MAX_AGE
    if refresh or stale:
        try:
            frame = fetch(ticker)
            store.replace_prices(con, ticker, frame, ok=not frame.empty)
        except Exception as exc:
            logger.warning("price fetch failed for %s: %s", ticker, exc)
            if fetched_at is None:
                store.replace_prices(con, ticker, EMPTY.copy(), ok=False)
    prices = store.load_prices(con, ticker)
    if not prices.empty:
        prices["date"] = pd.to_datetime(prices["date"])
    return prices


def splits(prices: pd.DataFrame) -> pd.Series:
    if prices.empty:
        return pd.Series(dtype=float)
    s = prices.loc[prices["split"] > 0, ["date", "split"]]
    return s.set_index("date")["split"]


def until(prices: pd.DataFrame, as_of) -> pd.DataFrame:
    if as_of is None or prices.empty:
        return prices
    return prices[prices["date"] <= pd.Timestamp(as_of)]


def last_close(prices: pd.DataFrame) -> "tuple[float, pd.Timestamp] | tuple[None, None]":
    if prices.empty:
        return None, None
    row = prices.iloc[-1]
    return float(row["close"]), row["date"]


def window(prices: pd.DataFrame, end, days: int = 365) -> "dict | None":
    end = pd.Timestamp(end)
    w = prices[(prices["date"] > end - pd.Timedelta(days=days)) & (prices["date"] <= end)]
    if len(w) < 150:
        return None
    return {"high": float(w["high"].max()), "low": float(w["low"].min()), "mean": float(w["close"].mean())}


def trailing_dividends(prices: pd.DataFrame, days: int = 365) -> float:
    if prices.empty:
        return 0.0
    end = prices["date"].iloc[-1]
    recent = prices[prices["date"] > end - pd.Timedelta(days=days)]
    return float(recent["dividend"].sum())
