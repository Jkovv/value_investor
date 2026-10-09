"""17 · fx: currency conversion through Yahoo's FX pairs, cached like prices.

Some exchanges quote in a subunit: London in pence (GBp), Johannesburg in
cents (ZAc), Tel Aviv in agorot (ILA). Everything is moved to the major
unit before it meets a financial statement.
"""

import pandas as pd

from value_investor import prices as px

SUBUNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def major(currency: "str | None") -> "tuple[str | None, float]":
    """(major currency, divisor) for a quoted currency."""
    if currency in SUBUNITS:
        return SUBUNITS[currency]
    return currency, 1.0


def series(con, base: str, quote: str) -> pd.Series:
    """Units of `quote` per one `base`, daily."""
    if base == quote:
        return pd.Series(dtype=float)
    frame = px.ensure(con, f"{base}{quote}=X")
    if frame.empty:
        inverse = px.ensure(con, f"{quote}{base}=X")
        if inverse.empty:
            return pd.Series(dtype=float)
        return 1.0 / inverse.set_index("date")["close"]
    return frame.set_index("date")["close"]


def rate(con, base: str, quote: str, when=None) -> "float | None":
    if not base or not quote:
        return None
    if base == quote:
        return 1.0
    s = series(con, base, quote)
    if s.empty:
        return None
    if when is not None:
        s = s[s.index <= pd.Timestamp(when)]
    return None if s.empty else float(s.iloc[-1])


def to_major(prices: pd.DataFrame, currency: "str | None") -> "tuple[pd.DataFrame, str | None]":
    code, divisor = major(currency)
    if divisor == 1.0 or prices.empty:
        return prices, code
    out = prices.copy()
    for col in ("high", "low", "close", "dividend"):
        out[col] = out[col] / divisor
    return out, code


def convert_prices(con, prices: pd.DataFrame, base: str, quote: str) -> "pd.DataFrame | None":
    """Re-express a price frame from `base` into `quote`, day by day."""
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
