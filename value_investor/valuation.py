"""12 · valuation — what today's price buys over the next ten years.

The share is treated as a bond whose coupon is EPS and whose coupon grows.
Ten years of growth at a conservative rate, times the P/E the market has
historically paid for this company, plus the dividends collected on the
way, gives a value in year ten. The annual return from today's price to
that value is what the ranking sorts on. Working the same formula backwards
from the hurdle rate gives the most we should pay.

Growth is the lower of what EPS actually did and what ROE × retention can
sustain, capped, so one great decade doesn't get projected forever.
"""

import pandas as pd

from value_investor import config, prices as px


def _growth(s: dict) -> "tuple[float | None, dict]":
    hist = s.get("eps_cagr_smoothed")
    sustainable = None
    if s.get("roe_recent") is not None and s.get("payout") is not None:
        sustainable = s["roe_recent"] * (1.0 - min(max(s["payout"], 0.0), 1.0))
    options = [g for g in (hist, sustainable) if g is not None]
    if not options:
        return None, {"historical": hist, "sustainable": sustainable}
    g = min(max(min(options), 0.0), config.GROWTH_CAP)
    return g, {"historical": hist, "sustainable": sustainable}


def historical_pe(yearly: pd.DataFrame, prices: pd.DataFrame, years: int = config.HISTORY_YEARS) -> "dict | None":
    rows = []
    for end, rec in yearly.tail(years).iterrows():
        eps = rec["eps"]
        if pd.isna(eps) or eps <= 0:
            continue
        w = px.window(prices, end)
        if w is None:
            continue
        rows.append((w["low"] / eps, w["mean"] / eps, w["high"] / eps))
    if len(rows) < 3:
        return None
    frame = pd.DataFrame(rows, columns=["low", "mid", "high"]).clip(config.PE_FLOOR, config.PE_CAP)
    return {"low": float(frame["low"].mean()), "mid": float(frame["mid"].mean()),
            "high": float(frame["high"].mean()), "years": len(rows)}


def value(yearly: pd.DataFrame, s: dict, prices: pd.DataFrame, bond_yield: "float | None") -> dict:
    out: dict = {"available": False}
    price, price_date = px.last_close(prices)
    out["price"] = price
    out["price_date"] = None if price_date is None else pd.Timestamp(price_date).date()
    eps = s.get("eps")
    if price is None:
        out["reason"] = "no price history"
        return out
    if eps is None:
        out["reason"] = "no company-wide earnings per share in the filings"
        return out
    if eps <= 0:
        out["reason"] = "no positive earnings to project"
        return out

    reported = s.get("eps_reported")
    if reported and reported > 0 and not (0.75 <= eps / reported <= 1.33):
        out["reason"] = f"per-share mismatch (computed {eps:.2f} vs filed {reported:.2f}); share classes or ADR ratio"
        return out

    g, growth_inputs = _growth(s)
    if g is None:
        out["reason"] = "not enough history to estimate growth"
        return out
    pe = historical_pe(yearly, prices)
    pe_source = "history"
    if pe is None:
        current = min(max(price / eps, config.PE_FLOOR), config.PE_CAP)
        pe = {"low": current * 0.8, "mid": current, "high": current * 1.2, "years": 0}
        pe_source = "current"

    payout = min(max(s.get("payout") or 0.0, 0.0), 1.0)
    n = config.PROJECTION_YEARS
    eps_path = [eps * (1 + g) ** k for k in range(1, n + 1)]
    dividends = sum(e * payout for e in eps_path)
    future_eps = eps_path[-1]

    def annual(total):
        return (total / price) ** (1.0 / n) - 1.0

    totals = {k: future_eps * pe[k] + dividends for k in ("low", "mid", "high")}
    buy_price = totals["mid"] / (1 + config.HURDLE_RATE) ** n
    pe_now = price / eps
    trailing_div = px.trailing_dividends(prices)

    out.update({
        "available": True,
        "growth": g,
        "growth_inputs": growth_inputs,
        "pe": pe,
        "pe_source": pe_source,
        "pe_now": pe_now,
        "payout": payout,
        "future_eps": future_eps,
        "dividends_collected": dividends,
        "future_value": totals,
        "expected_return": {k: annual(v) for k, v in totals.items()},
        "buy_price": buy_price,
        "margin_of_safety": buy_price / price - 1.0,
        "initial_return": eps / price,
        "pretax_yield": (s["pretax_per_share"] / price) if s.get("pretax_per_share") else None,
        "bond_yield": bond_yield,
        "bond_equivalent_value": eps / bond_yield if bond_yield else None,
        "dividend_yield": trailing_div / price if trailing_div else (s.get("dps") or 0.0) / price,
        "sell_signal": pe_now >= config.SELL_PE,
    })
    return out
