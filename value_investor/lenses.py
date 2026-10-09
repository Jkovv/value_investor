"""23 · lenses: other well-known ways to judge the same company, side by side.

The checklist is one school of thought. These are the others an investor
will meet, all computed from the same statements, none of them by a model:

    Piotroski F-score    nine yes/no tests of improving financial health
    Altman Z-score       distance from financial distress
    Graham               the Graham number and the defensive-investor tests
    Magic Formula        earnings yield and return on capital
    Lynch                growth category, PEG and dividend-adjusted PEG
    Owner-earnings DCF   ten years of owner earnings plus a terminal value

They're shown next to the checklist, not folded into its score: when they
disagree with it, that disagreement is the interesting part.
"""

import math

import pandas as pd

CYCLICAL_SECTORS = {"Energy", "Basic Materials", "Industrials", "Consumer Cyclical", "Real Estate"}
# SIC codes for the same idea on SEC filers: mining and oil, building, paper,
# chemicals, steel and metals, cars and planes, airlines and shipping.
CYCLICAL_SIC = [(1000, 1799), (2600, 2699), (2800, 2899), (3300, 3399), (3700, 3799), (4400, 4599)]
TERMINAL_GROWTH = 0.025
EQUITY_PREMIUM = 0.05
MIN_DISCOUNT = 0.09
DCF_YEARS = 10
GRAHAM_YEARS = 10


def _num(v) -> "float | None":
    try:
        return None if v is None or pd.isna(v) else float(v)
    except (TypeError, ValueError):
        return None


def _div(a, b) -> "float | None":
    a, b = _num(a), _num(b)
    return None if a is None or not b else a / b


def _gt(a, b) -> "bool | None":
    return None if a is None or b is None else a > b


def ebit(row) -> "float | None":
    """Operating income, or pre-tax income plus interest for filers that don't tag it (Merck)."""
    op = _num(row.operating_income)
    if op is not None:
        return op
    pretax = _num(row.pretax_income)
    return None if pretax is None else pretax + (_num(row.interest_expense) or 0)


def piotroski(t: pd.DataFrame) -> "dict | None":
    """Nine tests on the last two years. Tests without data are skipped and the
    score is scaled back to nine, so a bank isn't punished for having no
    current ratio."""
    if len(t) < 2:
        return None
    now, before = t.iloc[-1], t.iloc[-2]
    older = t.iloc[-3] if len(t) >= 3 else before
    roa_now = _div(now.net_income, before.total_assets)
    roa_before = _div(before.net_income, older.total_assets)
    ocf, ni = _num(now.operating_cash_flow), _num(now.net_income)
    lev_now = _div(_num(now.long_term_debt) or 0, now.total_assets)
    lev_before = _div(_num(before.long_term_debt) or 0, before.total_assets)
    sh_now, sh_before = _num(now.shares_diluted), _num(before.shares_diluted)

    tests = {
        "Positive return on assets": _gt(roa_now, 0),
        "Positive operating cash flow": _gt(ocf, 0),
        "Return on assets improved": _gt(roa_now, roa_before),
        "Cash flow above net income": _gt(ocf, ni),
        "Leverage fell": None if lev_now is None or lev_before is None else lev_now <= lev_before,
        "Current ratio improved": _gt(_div(now.current_assets, now.current_liabilities),
                                      _div(before.current_assets, before.current_liabilities)),
        "No new shares issued": None if sh_now is None or sh_before is None else sh_now <= sh_before * 1.005,
        "Gross margin improved": _gt(_div(now.gross_profit, now.revenue), _div(before.gross_profit, before.revenue)),
        "Asset turnover improved": _gt(_div(now.revenue, before.total_assets), _div(before.revenue, older.total_assets)),
    }
    ran = [v for v in tests.values() if v is not None]
    if len(ran) < 5:
        return None
    score = sum(ran)
    scaled = round(score * 9 / len(ran))
    verdict = "strong" if scaled >= 7 else "weak" if scaled <= 3 else "average"
    return {"score": score, "of": len(ran), "scaled": scaled, "verdict": verdict, "tests": tests}


def altman(t: pd.DataFrame, market_cap: "float | None") -> "dict | None":
    """The original 1968 Z-score. Built on manufacturers, so read it as a rough
    distress gauge for everything else."""
    now = t.iloc[-1]
    ta = _num(now.total_assets)
    if not ta or not market_cap:
        return None
    tl = _num(now.total_liabilities)
    if tl is None:
        equity = _num(now.equity_incl_nci) or _num(now.equity)
        tl = ta - equity if equity is not None else None
    if not tl or tl <= 0:
        return None
    wc = (_num(now.current_assets) or 0) - (_num(now.current_liabilities) or 0)
    z = (1.2 * wc / ta + 1.4 * (_num(now.retained_earnings) or 0) / ta + 3.3 * (ebit(now) or 0) / ta
         + 0.6 * market_cap / tl + 1.0 * (_num(now.revenue) or 0) / ta)
    zone = "safe" if z > 2.99 else "grey" if z >= 1.81 else "distress"
    return {"z": z, "zone": zone}


def graham(y: pd.DataFrame, s: dict, price: "float | None", t: pd.DataFrame, profile: str) -> "dict | None":
    """The Graham number (fair price for a defensive investor) and the
    defensive-investor tests from The Intelligent Investor. Prices here are
    in statement currency."""
    out: dict = {}
    eps, bvps = s.get("eps"), s.get("bvps")
    if eps and bvps and eps > 0 and bvps > 0:
        out["number"] = math.sqrt(22.5 * eps * bvps)
        if price:
            out["vs_price"] = out["number"] / price - 1
    now = t.iloc[-1]
    decade = y.tail(GRAHAM_YEARS)
    eps_hist = decade["eps"].dropna()
    dps_hist = decade["dps"]
    avg3 = float(eps_hist.tail(3).mean()) if len(eps_hist) >= 3 else None
    first3 = float(eps_hist.head(3).mean()) if len(eps_hist) >= 6 else None
    pe3 = price / avg3 if price and avg3 and avg3 > 0 else None
    pb = price / bvps if price and bvps and bvps > 0 else None

    tests = {}
    if profile != "financial":
        ca, cl = _num(now.current_assets), _num(now.current_liabilities)
        tests["Current ratio of 2 or more"] = None if not ca or not cl else ca / cl >= 2
        tests["Long-term debt below working capital"] = (None if ca is None or cl is None
                                                         else (_num(now.long_term_debt) or 0) <= ca - cl)
    tests.update({
        "Earnings positive every year": None if eps_hist.empty else bool((eps_hist > 0).all()),
        "Dividend paid every year": None if dps_hist.dropna().empty else bool((dps_hist.fillna(0) > 0).all()),
        "EPS up a third over the decade": None if first3 is None or first3 <= 0 else avg3 / first3 >= 4 / 3,
        "P/E on 3-year earnings of 15 or less": None if pe3 is None else pe3 <= 15,
        "P/E × P/B of 22.5 or less": None if pe3 is None or pb is None else pe3 * pb <= 22.5,
    })
    ran = [v for v in tests.values() if v is not None]
    if not out and not ran:
        return None
    out.update(passed=sum(ran), of=len(ran), tests=tests, years=len(eps_hist))
    return out


def magic_formula(t: pd.DataFrame, market_cap: "float | None") -> "dict | None":
    """Earnings yield (EBIT / enterprise value) and return on capital
    (EBIT / (net working capital + net fixed assets))."""
    now = t.iloc[-1]
    profit = ebit(now)
    if profit is None or not market_cap:
        return None
    debt = (_num(now.long_term_debt) or 0) + (_num(now.short_term_debt) or 0)
    ev = market_cap + debt - (_num(now.cash) or 0)
    nwc = max((_num(now.current_assets) or 0) - (_num(now.current_liabilities) or 0), 0)
    capital = nwc + (_num(now.ppe) or 0)
    return {
        "earnings_yield": profit / ev if ev > 0 else None,
        "return_on_capital": profit / capital if capital > 0 else None,
        "enterprise_value": ev,
    }


def cyclical(sector: "str | None", sic) -> bool:
    if sector in CYCLICAL_SECTORS:
        return True
    try:
        code = int(sic)
    except (TypeError, ValueError):
        return False
    return any(lo <= code <= hi for lo, hi in CYCLICAL_SIC)


def lynch(s: dict, v: dict, sector: "str | None" = None, sic=None) -> "dict | None":
    """One of Lynch's six stock categories, plus PEG and dividend-adjusted PEG
    (under 1 is cheap for the growth, over 2 is expensive)."""
    g = s.get("eps_cagr_smoothed")
    if g is None:
        return None
    up = s.get("eps_up_share")
    if (s.get("loss_years") or 0) > 0 and (s.get("eps") or 0) > 0:
        category = "Turnaround"
    elif cyclical(sector, sic) and up is not None and up < 0.6:
        category = "Cyclical"
    elif g < 0.05:
        category = "Slow grower"
    elif g < 0.15:
        category = "Stalwart"
    else:
        category = "Fast grower"
    out = {"category": category, "growth": g}
    pe = v.get("pe_now") if v.get("available") else None
    if pe and pe > 0 and g > 0:
        out["peg"] = pe / (g * 100)
        out["pegy"] = pe / ((g + (v.get("dividend_yield") or 0)) * 100)
    return out


def owner_earnings_dcf(y: pd.DataFrame, s: dict, v: dict) -> "dict | None":
    """Owner earnings per share (average of the last three years), grown at the
    projection's rate fading to 2.5% by year ten, discounted at the bond yield
    plus 5 points (never under 9%), plus a terminal value."""
    if not v.get("available"):
        return None
    oe = y["owner_earnings"].dropna().tail(3)
    shares = s.get("shares")
    if oe.empty or not shares or oe.mean() <= 0:
        return None
    per_share = float(oe.mean()) / shares
    g0 = min(max(v.get("growth") or 0.0, 0.0), 0.15)
    r = max(MIN_DISCOUNT, (v.get("bond_yield") or 0.04) + EQUITY_PREMIUM)
    flow, present = per_share, 0.0
    for k in range(1, DCF_YEARS + 1):
        g = g0 + (TERMINAL_GROWTH - g0) * (k - 1) / (DCF_YEARS - 1)
        flow *= 1 + g
        present += flow / (1 + r) ** k
    terminal = flow * (1 + TERMINAL_GROWTH) / (r - TERMINAL_GROWTH) / (1 + r) ** DCF_YEARS
    value = present + terminal
    return {"value": value, "owner_earnings_per_share": per_share, "growth": g0, "discount": r,
            "terminal_share": terminal / value}


def compute(t: pd.DataFrame, y: pd.DataFrame, s: dict, v: dict, profile: str,
            sector: "str | None" = None, sic=None, to_quote: float = 1.0) -> dict:
    """All lenses for one company. Statements are in their own currency;
    to_quote turns a statement-currency price into the currency the shares
    trade in, so the per-share values shown sit next to the quoted price."""
    if t.empty or y.empty:
        return {}
    price = _num(v.get("price")) if v.get("available") else None
    price_stmt = price / to_quote if price else None
    cap = _num(v.get("market_cap")) if price else None
    out = {"piotroski": piotroski(t), "graham": graham(y, s, price_stmt, t, profile), "lynch": lynch(s, v, sector, sic)}
    if profile != "financial":
        out["altman"] = altman(t, cap)
        out["magic"] = magic_formula(t, cap)
    if out["graham"] and "number" in out["graham"]:
        out["graham"]["number"] *= to_quote
    dcf = owner_earnings_dcf(y, s, v) if price else None
    if dcf:
        dcf["value"] *= to_quote
        dcf["owner_earnings_per_share"] *= to_quote
        dcf["vs_price"] = dcf["value"] / price - 1
        out["dcf"] = dcf
    return {k: _plain(val) for k, val in out.items() if val}


def _plain(d: dict) -> dict:
    """numpy scalars to Python ones, so the payload round-trips through JSON as is."""
    return {k: _plain(v) if isinstance(v, dict) else (float(v) if hasattr(v, "dtype") else v) for k, v in d.items()}
