"""17 · fx: currency conversion through Yahoo's FX pairs, cached like prices.

some exchanges quote in a subunit: London in pence (GBp), Johannesburg in
cents (ZAc), Tel Aviv in agorot (ILA), Kuwait in fils (KWF). everything is moved to the major
unit before it meets a financial statement.
"""

import pandas as pd

from value_investor import prices as px, store

SUBUNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0),
            "KWF": ("KWD", 1000.0)}


def major(currency: "str | None") -> "tuple[str | None, float]":
    """(major currency, divisor) for a quoted currency."""
    if currency in SUBUNITS:
        return SUBUNITS[currency]
    return currency, 1.0


def _closes(con, symbol: str, fetch: bool) -> pd.Series:
    if fetch:
        frame = px.ensure(con, symbol)
    else:
        # the dashboard holds the database read-only, so it takes what is stored
        frame = store.load_prices(con, symbol)
        frame["date"] = pd.to_datetime(frame["date"])
    if frame.empty:
        return pd.Series(dtype=float)
    return frame.set_index("date")["close"].dropna()


def series(con, base: str, quote: str, fetch: bool = True) -> pd.Series:
    """units of `quote` per one `base`, daily."""
    if base == quote:
        return pd.Series(dtype=float)
    direct = _closes(con, f"{base}{quote}=X", fetch)
    if not direct.empty:
        return direct
    inverse = _closes(con, f"{quote}{base}=X", fetch)
    return inverse if inverse.empty else 1.0 / inverse


def rate(con, base: str, quote: str, when=None, fetch: bool = True) -> "float | None":
    if not base or not quote:
        return None
    if base == quote:
        return 1.0
    s = series(con, base, quote, fetch)
    if s.empty:
        return None
    if when is not None:
        s = s[s.index <= pd.Timestamp(when)]
    return None if s.empty else float(s.iloc[-1])


def ensure_pairs(con, currencies, quotes) -> None:
    for base in {major(c)[0] for c in currencies if c}:
        for quote in quotes:
            if base != quote:
                series(con, base, quote)


def to_major(prices: pd.DataFrame, currency: "str | None") -> "tuple[pd.DataFrame, str | None]":
    code, divisor = major(currency)
    if divisor == 1.0 or prices.empty:
        return prices, code
    out = prices.copy()
    for col in ("high", "low", "close", "dividend"):
        out[col] = out[col] / divisor
    return out, code


def convert_prices(con, prices: pd.DataFrame, base: str, quote: str) -> "pd.DataFrame | None":
    """re-express a price frame from `base` into `quote`, day by day."""
    if base == quote or prices.empty:
        return prices
    s = series(con, base, quote)
    if s.empty:
        return None
    rates = s.reindex(prices["date"], method="ffill").to_numpy()
    out = prices.copy()
    for col in ("high", "low", "close", "dividend"):
        out[col] = out[col].to_numpy() * rates
    return out.dropna(subset=["close"])
