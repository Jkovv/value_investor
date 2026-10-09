"""11 · rules: the quality checklist, one check per principle.

each check is pass, warn, fail or n/a. quality is the weighted share of points
over the checks that could run; completeness is how much could run at all.
banks, insurers and reits get a shorter list.
"""

from dataclasses import asdict, dataclass

from value_investor import config as c

POINTS = {"pass": 1.0, "warn": 0.5, "fail": 0.0}


@dataclass
class Check:
    key: str
    group: str
    label: str
    weight: float
    status: str
    value: "float | None"
    shown: str
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _pct(v):
    return "-" if v is None else f"{v * 100:.0f}%"


def _x(v):
    return "-" if v is None else f"{v:.1f}×"


def _higher(v, good, poor):
    if v is None:
        return "na"
    return "pass" if v >= good else "warn" if v >= poor else "fail"


def _lower(v, good, poor):
    if v is None:
        return "na"
    return "pass" if v <= good else "warn" if v <= poor else "fail"


def _enough_history(s) -> bool:
    return s.get("history_years", 0) >= c.MIN_HISTORY_YEARS


def profile_for(sic) -> str:
    lo, hi = c.FINANCIAL_SIC_RANGE
    return "financial" if sic is not None and lo <= int(sic) <= hi else "general"


def _gross_margin(s):
    if not s.get("has_gross_profit") and s.get("operating_margin") is not None:
        v = s["operating_margin"]
        return Check("gross_margin", "income", "Operating margin (no gross profit filed)", 3.0,
                     _higher(v, c.OPERATING_MARGIN_GOOD, c.OPERATING_MARGIN_POOR), v, _pct(v),
                     "Stands in for gross margin when the company doesn't report cost of sales.")
    v = s.get("gross_margin")
    return Check("gross_margin", "income", "Gross margin", 3.0, _higher(v, c.GROSS_MARGIN_GOOD, c.GROSS_MARGIN_POOR),
                 v, _pct(v), "10-year median. Above 40% usually means pricing power.")


def _gross_margin_stability(s):
    key, label = "gross_margin_std", "Gross margin consistency"
    if not s.get("has_gross_profit"):
        key, label = "operating_margin_std", "Operating margin consistency"
    v = s.get(key) if _enough_history(s) else None
    status = _lower(v, c.GROSS_MARGIN_MAX_SWING, 2 * c.GROSS_MARGIN_MAX_SWING)
    shown = "-" if v is None else f"±{v * 100:.1f} pp"
    return Check("gross_margin_stability", "income", label, 2.0, status, v, shown,
                 "Standard deviation of the yearly margin.")


def _sga(s):
    v = s.get("sga_to_gp")
    return Check("sga", "income", "SG&A / gross profit", 2.0, _lower(v, c.SGA_TO_GROSS_PROFIT_GOOD, c.SGA_TO_GROSS_PROFIT_POOR),
                 v, _pct(v), "Under 30% is excellent, 30-80% is common, near 100% means a crowded market.")


def _per_gp_or_revenue(s, name):
    """GP-based ratio, or the revenue-based one at half the thresholds when GP isn't filed."""
    if s.get("has_gross_profit"):
        return s.get(f"{name}_to_gp"), 1.0, "gross profit"
    return s.get(f"{name}_to_rev"), 0.5, "revenue"


def _rnd(s):
    v, scale, base = _per_gp_or_revenue(s, "rnd")
    note = "None reported." if v == 0.0 and not s.get("rnd_reported") else "Heavy R&D means the edge has to be re-bought every year."
    status = _lower(v, c.RND_TO_GROSS_PROFIT_GOOD * scale, c.RND_TO_GROSS_PROFIT_POOR * scale)
    return Check("rnd", "income", f"R&D / {base}", 1.5, status, v, _pct(v), note)


def _depreciation(s):
    v, scale, base = _per_gp_or_revenue(s, "dep")
    status = _lower(v, c.DEPRECIATION_TO_GROSS_PROFIT_GOOD * scale, c.DEPRECIATION_TO_GROSS_PROFIT_POOR * scale)
    return Check("depreciation", "income", f"Depreciation / {base}", 1.0, status, v, _pct(v),
                 "Low when the business doesn't need constant reinvestment in plant.")


def _interest(s):
    v = s.get("interest_to_opinc")
    return Check("interest", "income", "Interest / operating income", 2.0,
                 _lower(v, c.INTEREST_TO_OPERATING_INCOME_GOOD, c.INTEREST_TO_OPERATING_INCOME_POOR), v, _pct(v),
                 "Within an industry, the lowest ratio usually belongs to the strongest company.")


def _net_margin(s):
    v = s.get("net_margin")
    return Check("net_margin", "income", "Net margin", 2.0, _higher(v, c.NET_MARGIN_GOOD, c.NET_MARGIN_POOR), v, _pct(v),
                 "Above 20% is strong, 10-20% grey, below 10% competitive.")


def _eps_consistency(s):
    share, losses = s.get("eps_up_share"), s.get("loss_years")
    if share is None or not _enough_history(s):
        status = "na"
    elif share >= c.EPS_UP_YEARS_GOOD and losses == 0:
        status = "pass"
    elif share >= c.EPS_UP_YEARS_POOR and (losses or 0) <= 1:
        status = "warn"
    else:
        status = "fail"
    shown = "-" if share is None else f"{share * 100:.0f}% up, {losses} loss"
    return Check("eps_consistency", "income", "Earnings consistency", 3.0, status, share, shown,
                 "Share of years EPS rose; any loss year counts against it.")


def _eps_growth(s):
    g, g5 = s.get("eps_cagr"), s.get("eps_cagr_5y")
    if g is None or not _enough_history(s):
        status = "na" if g is None else "warn"
    elif g <= 0:
        status = "fail"
    elif g5 is not None and g5 < g - 0.03:
        status = "warn"
    else:
        status = "pass"
    shown = "-" if g is None else f"{g * 100:.1f}% / 5y {_pct(g5)}"
    return Check("eps_growth", "income", "EPS growth (10y / 5y)", 2.0, status, g, shown,
                 "The recent rate shouldn't be falling behind the long one.")


def _tax(s):
    v = s.get("tax_rate")
    if v is None:
        status = "na"
    elif c.TAX_RATE_LOW <= v <= c.TAX_RATE_HIGH:
        status = "pass"
    else:
        status = "warn"
    return Check("tax_rate", "income", "Effective tax rate", 0.5, status, v, _pct(v),
                 "Far from the statutory rate deserves a look at the tax note.")


def _roe(s):
    v, share = s.get("roe"), s.get("roe_good_share")
    note = "Median ROE; share of years above 15% shown."
    if v is None and s.get("adj_roe") is not None:
        v = s["adj_roe"]
        note = "Equity is negative after buybacks; treasury stock added back."
    status = _higher(v, c.ROE_GOOD, c.ROE_POOR)
    if status == "pass" and share is not None and share < c.ROE_CONSISTENT_YEARS:
        status = "warn"
    shown = "-" if v is None else f"{_pct(v)} ({_pct(share)} of yrs)"
    return Check("roe", "balance", "Return on equity", 3.0, status, v, shown, note)


def _debt_payoff(s):
    v = s.get("debt_years")
    if v is None and s.get("net_income") is not None and s["net_income"] <= 0:
        status = "fail"
    else:
        status = _lower(v, c.DEBT_PAYOFF_YEARS_GOOD, c.DEBT_PAYOFF_YEARS_POOR)
    return Check("debt_payoff", "balance", "Years of earnings to repay LT debt", 3.0, status, v, _x(v),
                 "Under 3 years is comfortable; under 1 is the strict version.")


def _adj_debt_to_equity(s):
    v = s.get("adj_debt_to_equity")
    return Check("adj_debt_to_equity", "balance", "Liabilities / equity (treasury-adjusted)", 2.0,
                 _lower(v, c.ADJ_DEBT_TO_EQUITY_GOOD, c.ADJ_DEBT_TO_EQUITY_POOR), v, _x(v),
                 "Treasury stock added back so buybacks don't look like leverage.")


def _preferred(s):
    present = s.get("preferred_present")
    return Check("preferred", "balance", "No preferred stock", 0.5, "warn" if present else "pass",
                 1.0 if present else 0.0, "present" if present else "none", "Strong businesses rarely need it.")


def _retained_earnings(s):
    v = s.get("retained_earnings_cagr")
    if not _enough_history(s):
        status = "na"
    elif v is None:
        status = "pass" if s.get("retained_earnings_rising") else "fail"
    else:
        status = "pass" if v > 0.03 else "warn" if v > 0 else "fail"
    return Check("retained_earnings", "balance", "Retained earnings growth", 1.5, status, v, _pct(v),
                 "A growing pile of retained earnings compounds future earnings.")


def _share_count(s):
    v = s.get("share_change")
    status = "na" if v is None else "pass" if v <= 0 else "warn" if v <= c.SHARE_COUNT_DILUTION_POOR else "fail"
    shown = "-" if v is None else f"{v * 100:+.0f}%"
    return Check("share_count", "balance", "Share count over the window", 1.5, status, v, shown,
                 "Falling means buybacks; rising means owners get diluted.")


def _capex(s):
    v = s.get("capex_to_ni")
    return Check("capex", "cash", "Capex / net income (10y total)", 2.5,
                 _lower(v, c.CAPEX_TO_EARNINGS_GOOD, c.CAPEX_TO_EARNINGS_POOR), v, _pct(v),
                 "Under 25% is the mark of a business that doesn't eat its own earnings.")


def _fcf(s):
    v = s.get("fcf_conversion")
    return Check("fcf_conversion", "cash", "Free cash flow / net income", 1.5,
                 _higher(v, c.FCF_CONVERSION_GOOD, c.FCF_CONVERSION_POOR), v, _pct(v),
                 "Earnings that never turn into cash are a warning.")


def _buybacks(s):
    v = s.get("buyback_years_share")
    status = "na" if v is None else "pass" if v >= 0.5 else "warn"
    return Check("buybacks", "cash", "Buyback history", 1.0, status, v, _pct(v) + " of yrs" if v is not None else "-",
                 "Repurchases are the preferred way to hand back surplus cash.")


def _retained_return(s):
    v = s.get("retained_earnings_return")
    return Check("retained_return", "cash", "Return on retained earnings", 2.0,
                 _higher(v, c.RETAINED_EARNINGS_RETURN_GOOD, c.RETAINED_EARNINGS_RETURN_POOR), v, _pct(v),
                 "EPS gained per dollar of EPS kept in the business.")


GENERAL = [_gross_margin, _gross_margin_stability, _sga, _rnd, _depreciation, _interest, _net_margin,
           _eps_consistency, _eps_growth, _tax, _roe, _debt_payoff, _adj_debt_to_equity, _preferred,
           _retained_earnings, _share_count, _capex, _fcf, _buybacks, _retained_return]

FINANCIAL = [_eps_consistency, _eps_growth, _tax, _roe, _preferred, _retained_earnings, _share_count,
             _buybacks, _retained_return]


def evaluate(s: dict, profile: str) -> list:
    return [rule(s) for rule in (FINANCIAL if profile == "financial" else GENERAL)]


def score(checks: list) -> "tuple[float, float]":
    total = sum(ch.weight for ch in checks)
    ran = [ch for ch in checks if ch.status != "na"]
    weight = sum(ch.weight for ch in ran)
    if weight == 0:
        return 0.0, 0.0
    quality = 100.0 * sum(POINTS[ch.status] * ch.weight for ch in ran) / weight
    return quality, weight / total
