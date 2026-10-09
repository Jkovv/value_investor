"""10 · metrics: yearly ratios, then one summary over the last ten years.

Per-share figures are rebuilt from totals (net income / diluted shares)
rather than taken as filed, and every share count is moved into today's
units: a count filed before a split is multiplied by every split that came
after its filing date. Counts filed after a split are already restated by
the company and are left alone.
"""

import math

import numpy as np
import pandas as pd

from value_investor import config


def _div(a, b):
    """Elementwise a / b, NaN where b is missing or zero."""
    b = b.where(b != 0)
    return a / b


def split_factors(filed: pd.Series, splits: pd.Series) -> pd.Series:
    if splits is None or splits.empty:
        return pd.Series(1.0, index=filed.index)
    out = []
    for when in filed:
        if pd.isna(when):
            out.append(1.0)
            continue
        later = splits[splits.index > pd.Timestamp(when)]
        out.append(float(np.prod(later.values)) if not later.empty else 1.0)
    return pd.Series(out, index=filed.index)


def _maintenance_capex(t: pd.DataFrame) -> pd.Series:
    """Greenwald's split: capex beyond what new sales needed is maintenance."""
    ppe_to_sales = _div(t["ppe"], t["revenue"]).median()
    if pd.isna(ppe_to_sales):
        return t["capex"]
    growth = (t["revenue"].diff().clip(lower=0) * ppe_to_sales).fillna(0)
    return (t["capex"] - growth).clip(lower=0)


def yearly(statements: pd.DataFrame, splits: "pd.Series | None" = None) -> pd.DataFrame:
    t = statements
    y = pd.DataFrame(index=t.index)
    y["fiscal_year"] = t.index.year

    factor = split_factors(t["shares_diluted_filed"], splits)
    eps_factor = split_factors(t["eps_diluted_filed"], splits)
    dps_factor = split_factors(t["dps_declared_filed"], splits)

    y["revenue"] = t["revenue"]
    y["gross_profit"] = t["gross_profit"]
    y["operating_income"] = t["operating_income"]
    y["net_income"] = t["net_income"]
    y["gross_margin"] = _div(t["gross_profit"], t["revenue"])
    y["sga_to_gp"] = _div(t["sga"], t["gross_profit"].where(t["gross_profit"] > 0))
    y["rnd_to_gp"] = _div(t["rnd"], t["gross_profit"].where(t["gross_profit"] > 0))
    y["dep_to_gp"] = _div(t["depreciation"], t["gross_profit"].where(t["gross_profit"] > 0))
    y["interest_to_opinc"] = _div(t["interest_expense"], t["operating_income"].where(t["operating_income"] > 0))
    y["rnd_to_rev"] = _div(t["rnd"], t["revenue"])
    y["dep_to_rev"] = _div(t["depreciation"], t["revenue"])
    y["operating_margin"] = _div(t["operating_income"], t["revenue"])
    y["net_margin"] = _div(t["net_income"], t["revenue"])
    y["tax_rate"] = _div(t["income_tax"], t["pretax_income"].where(t["pretax_income"] > 0))

    y["eps_reported"] = t["eps_diluted"] / eps_factor
    shares = t["shares_diluted"] * factor
    # Some filers tag share counts in millions (MCD from 2024 on). When the
    # count disagrees badly with net income / reported EPS, trust the EPS.
    implied = _div(t["net_income"], y["eps_reported"].where(y["eps_reported"].abs() >= 0.05))
    bad = implied.notna() & (implied > 0) & ((shares / implied - 1).abs() > 0.3)
    shares = shares.where(~bad, implied).fillna(implied.where(implied > 0))
    y["shares"] = shares
    y["shares_corrected"] = bad
    y["eps"] = _div(t["net_income"], shares)
    dps_from_cash = _div(t["dividends_paid"], shares)
    y["dps"] = dps_from_cash.fillna(t["dps_declared"] / dps_factor)
    y["payout"] = _div(t["dividends_paid"].fillna(0), t["net_income"].where(t["net_income"] > 0))
    y["pretax_per_share"] = _div(t["pretax_income"], shares)

    equity = t["equity"]
    avg_equity = pd.concat([equity, equity.shift(1)], axis=1).mean(axis=1)
    usable = (equity > 0) & (equity.shift(1).fillna(equity) > 0)
    y["equity"] = equity
    y["bvps"] = _div(equity, shares)
    y["roe"] = _div(t["net_income"], avg_equity.where(usable))
    adj_equity = equity + t["treasury_stock"].fillna(0)
    y["adj_roe"] = _div(t["net_income"], adj_equity.where(adj_equity > 0))
    y["roa"] = _div(t["net_income"], t["total_assets"])
    y["gp_to_assets"] = _div(t["gross_profit"], t["total_assets"])

    y["long_term_debt"] = t["long_term_debt"]
    y["total_debt"] = t["long_term_debt"].fillna(0) + t["short_term_debt"].fillna(0)
    y["debt_years"] = _div(t["long_term_debt"].fillna(0), t["net_income"].where(t["net_income"] > 0))
    y["adj_debt_to_equity"] = _div(t["total_liabilities"], adj_equity.where(adj_equity > 0))
    y["current_ratio"] = _div(t["current_assets"], t["current_liabilities"])
    y["cash_and_investments"] = t["cash"].fillna(0) + t["short_term_investments"].fillna(0)
    y["receivables_to_revenue"] = _div(t["receivables"], t["revenue"])
    y["inventory"] = t["inventory"]
    y["retained_earnings"] = t["retained_earnings"]
    y["treasury_stock"] = t["treasury_stock"]
    y["preferred_stock"] = t["preferred_stock"]
    y["goodwill"] = t["goodwill"]

    y["operating_cash_flow"] = t["operating_cash_flow"]
    y["capex"] = t["capex"]
    y["capex_to_ni"] = _div(t["capex"], t["net_income"].where(t["net_income"] > 0))
    y["fcf"] = t["operating_cash_flow"] - t["capex"].fillna(0)
    y["owner_earnings"] = t["net_income"] + t["depreciation"].fillna(0) - _maintenance_capex(t).fillna(0)
    y["buybacks"] = t["buybacks"]
    y["stock_issued"] = t["stock_issued"]
    y["dividends_paid"] = t["dividends_paid"]
    y["taxes_paid"] = t["taxes_paid"]
    y["reported_rnd"] = t["rnd"].notna()
    y["reported_interest"] = t["interest_expense"].notna()
    return y


def _cagr(first, last, years) -> "float | None":
    if years <= 0 or first is None or last is None or pd.isna(first) or pd.isna(last) or first <= 0 or last <= 0:
        return None
    return (last / first) ** (1.0 / years) - 1.0


def _median(s: pd.Series) -> "float | None":
    s = s.dropna()
    return None if s.empty else float(s.median())


def _last(s: pd.Series) -> "float | None":
    s = s.dropna()
    return None if s.empty else float(s.iloc[-1])


def _span_years(index: pd.Index) -> float:
    return (index[-1] - index[0]).days / 365.25


def summary(y: pd.DataFrame, years: int = config.HISTORY_YEARS) -> dict:
    w = y[y["net_income"].notna()].tail(years)
    s: dict = {"history_years": len(w)}
    if w.empty:
        return s
    s["first_year"] = int(w["fiscal_year"].iloc[0])
    s["last_year"] = int(w["fiscal_year"].iloc[-1])

    has_gp = bool(w["gross_profit"].notna().sum() >= max(3, len(w) // 2))
    s["has_gross_profit"] = has_gp
    s["gross_margin"] = _median(w["gross_margin"]) if has_gp else None
    s["gross_margin_std"] = float(w["gross_margin"].std()) if has_gp and w["gross_margin"].count() >= 3 else None
    s["operating_margin_std"] = float(w["operating_margin"].std()) if w["operating_margin"].count() >= 3 else None
    s["sga_to_gp"] = _median(w["sga_to_gp"]) if has_gp else None
    s["rnd_reported"] = bool(w["reported_rnd"].any())
    if has_gp:
        s["rnd_to_gp"] = _median(w["rnd_to_gp"]) if s["rnd_reported"] else 0.0
        s["dep_to_gp"] = _median(w["dep_to_gp"])
    else:
        s["rnd_to_rev"] = _median(w["rnd_to_rev"]) if s["rnd_reported"] else (0.0 if w["revenue"].notna().any() else None)
        s["dep_to_rev"] = _median(w["dep_to_rev"])
    s["shares_corrected"] = bool(w["shares_corrected"].any())
    s["interest_to_opinc"] = (_median(w["interest_to_opinc"]) if w["reported_interest"].any()
                              else (0.0 if w["operating_income"].notna().any() else None))
    s["operating_margin"] = _median(w["operating_margin"])
    s["net_margin"] = _median(w["net_margin"])
    s["tax_rate"] = _median(w["tax_rate"])

    eps = w["eps"].dropna()
    if len(eps) >= 2:
        changes = eps.diff().dropna()
        s["eps_up_share"] = float((changes > 0).mean())
        s["loss_years"] = int((eps <= 0).sum())
        span = _span_years(eps.index)
        s["eps_cagr"] = _cagr(eps.iloc[0], eps.iloc[-1], span)
        recent = eps[eps.index >= eps.index[-1] - pd.Timedelta(days=int(5 * 365.25) + 10)]
        s["eps_cagr_5y"] = _cagr(recent.iloc[0], recent.iloc[-1], _span_years(recent.index)) if len(recent) >= 3 else None
        if len(eps) >= 6:
            head, tail = eps.iloc[:3].mean(), eps.iloc[-3:].mean()
            s["eps_cagr_smoothed"] = _cagr(head, tail, _span_years(eps.index[[1, -2]]))
        else:
            s["eps_cagr_smoothed"] = s["eps_cagr"]
    s["eps"] = _last(w["eps"])
    s["eps_reported"] = _last(w["eps_reported"])

    s["roe"] = _median(w["roe"])
    roe = w["roe"].dropna()
    s["roe_good_share"] = float((roe >= config.ROE_GOOD).mean()) if not roe.empty else None
    s["roe_recent"] = _median(w["roe"].tail(5))
    s["adj_roe"] = _median(w["adj_roe"])
    s["negative_equity"] = bool((w["equity"].dropna() <= 0).any())
    s["roa"] = _median(w["roa"])
    s["gp_to_assets"] = _median(w["gp_to_assets"])

    recent_ni = w["net_income"].tail(3).mean()
    ltd = _last(w["long_term_debt"])
    s["long_term_debt"] = ltd
    s["debt_years"] = (ltd or 0.0) / recent_ni if recent_ni and recent_ni > 0 else None
    s["adj_debt_to_equity"] = _last(w["adj_debt_to_equity"])
    s["current_ratio"] = _last(w["current_ratio"])
    s["cash_and_investments"] = _last(w["cash_and_investments"])
    s["total_debt"] = _last(w["total_debt"])
    s["preferred_present"] = bool((w["preferred_stock"].fillna(0) > 0).iloc[-1])
    s["treasury_present"] = bool((w["treasury_stock"].fillna(0) > 0).iloc[-1])

    re_ = w["retained_earnings"].dropna()
    s["retained_earnings_cagr"] = _cagr(re_.iloc[0], re_.iloc[-1], _span_years(re_.index)) if len(re_) >= 3 else None
    s["retained_earnings_rising"] = bool(len(re_) >= 3 and re_.iloc[-1] > re_.iloc[0])

    shares = w["shares"].dropna()
    shares = shares[shares > 0]
    s["share_change"] = float(shares.iloc[-1] / shares.iloc[0] - 1) if len(shares) >= 3 else None
    s["shares"] = _last(w["shares"])

    ni_total = w["net_income"].sum()
    s["capex_to_ni"] = float(w["capex"].fillna(0).sum() / ni_total) if ni_total > 0 and w["capex"].notna().any() else None
    fcf = w["fcf"].dropna()
    s["fcf_conversion"] = float(fcf.sum() / w.loc[fcf.index, "net_income"].sum()) if not fcf.empty and ni_total > 0 else None
    s["owner_earnings"] = _last(w["owner_earnings"])
    buybacks = w["buybacks"].fillna(0)
    s["buyback_years_share"] = float((buybacks > 0).mean())

    retained = (w["eps"] - w["dps"].fillna(0)).iloc[:-1].sum()
    eps_gain = w["eps"].iloc[-1] - w["eps"].iloc[0]
    s["retained_earnings_return"] = (float(eps_gain / retained) if len(w) >= config.MIN_HISTORY_YEARS
                                     and retained and retained > 0 and not math.isnan(eps_gain) else None)

    s["payout"] = _median(w["payout"].tail(5))
    s["dps"] = _last(w["dps"])
    dps = w["dps"].dropna()
    s["dps_cagr"] = _cagr(dps.iloc[0], dps.iloc[-1], _span_years(dps.index)) if len(dps) >= 3 else None
    s["pretax_per_share"] = _last(w["pretax_per_share"])
    s["bvps"] = _last(w["bvps"])
    s["revenue"] = _last(w["revenue"])
    s["net_income"] = _last(w["net_income"])
    s["revenue_cagr"] = _cagr(w["revenue"].iloc[0], w["revenue"].iloc[-1], _span_years(w.index))
    return s
