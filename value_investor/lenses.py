"""23 · lenses: the other schools, worked out from the same statements.

Piotroski, Altman, Graham, Lynch, the Magic Formula, an owner-earnings dcf,
a dividend discount model and a Monte Carlo run of the ten-year projection.
kept out of the quality score on purpose: when they disagree with the
checklist, that's the thing to look into.
"""

import math

import numpy as np
import pandas as pd

from value_investor import config

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
    """operating income, or pre-tax income plus interest for filers that don't tag it (Merck)."""
    op = _num(row.operating_income)
    if op is not None:
        return op
    pretax = _num(row.pretax_income)
    return None if pretax is None else pretax + (_num(row.interest_expense) or 0)


def piotroski(t: pd.DataFrame) -> "dict | None":
    """nine tests on the last two years. tests without data are skipped and the
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
    """the original 1968 Z-score. built on manufacturers, so read it as a rough
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
    """the Graham number (fair price for a defensive investor) and the
    defensive-investor tests from The Intelligent Investor. prices here are
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
    """earnings yield (EBIT / enterprise value) and return on capital
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
    """one of Lynch's six stock categories, plus PEG and dividend-adjusted PEG
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


def _discount(v: dict) -> float:
    return max(MIN_DISCOUNT, (v.get("bond_yield") or 0.04) + EQUITY_PREMIUM)


def _two_stage(start: float, g0: float, r: float) -> "tuple[float, float]":
    """ten years of growth fading from g0 to the terminal rate, then a terminal value.
    returns (value, share of the value that comes after year ten)."""
    flow, present = start, 0.0
    for k in range(1, DCF_YEARS + 1):
        g = g0 + (TERMINAL_GROWTH - g0) * (k - 1) / (DCF_YEARS - 1)
        flow *= 1 + g
        present += flow / (1 + r) ** k
    terminal = flow * (1 + TERMINAL_GROWTH) / (r - TERMINAL_GROWTH) / (1 + r) ** DCF_YEARS
    return present + terminal, terminal / (present + terminal)


def owner_earnings_dcf(y: pd.DataFrame, s: dict, v: dict) -> "dict | None":
    """owner earnings a share (last three years' average), growth fading to 2.5%,
    discounted at the bond yield plus 5 points, never under 9%."""
    if not v.get("available"):
        return None
    oe = y["owner_earnings"].dropna().tail(3)
    shares = s.get("shares")
    if oe.empty or not shares or oe.mean() <= 0:
        return None
    per_share = float(oe.mean()) / shares
    g0 = min(max(v.get("growth") or 0.0, 0.0), 0.15)
    r = _discount(v)
    value, tail = _two_stage(per_share, g0, r)
    return {"value": value, "owner_earnings_per_share": per_share, "growth": g0, "discount": r,
            "terminal_share": tail}


def ddm(s: dict, v: dict) -> "dict | None":
    """dividend discount model: today's dividend, growing at the slower of its own
    history and the earnings projection, same fade and discount as the dcf."""
    dps = s.get("dps")
    if not v.get("available") or not dps or dps <= 0:
        return None
    rates = [g for g in (s.get("dps_cagr"), v.get("growth")) if g is not None]
    g0 = min(max(min(rates) if rates else 0.0, 0.0), 0.12)
    r = _discount(v)
    value, tail = _two_stage(dps, g0, r)
    return {"value": value, "dps": dps, "growth": g0, "discount": r, "terminal_share": tail}


MC_DRAWS = 5000
MC_BINS = [round(-0.10 + 0.02 * i, 2) for i in range(26)]    # -10% to +40%


def monte_carlo(y: pd.DataFrame, s: dict, v: dict, price: "float | None", seed: int = 7) -> "dict | None":
    """the ten-year projection run 5,000 times with growth and the exit P/E drawn
    at random instead of fixed, so the answer is a spread, not three numbers.

    growth: normal around the projection's rate; the spread is the yearly EPS
    swings over the square root of the years seen, or half the gap between the
    two growth estimates if that's wider. exit P/E: triangular between the
    low and high of the company's own history. returns are local currency."""
    if not v.get("available") or not price or not s.get("eps") or s["eps"] <= 0:
        return None
    pe, inputs = v.get("pe") or {}, v.get("growth_inputs") or {}
    low, mid, high = pe.get("low"), pe.get("mid"), pe.get("high")
    if not (low and mid and high):
        return None
    if high - low < 0.1 * mid:
        low, high = mid * 0.8, mid * 1.2
    eps_hist = y["eps"].dropna()
    eps_hist = eps_hist[eps_hist > 0]
    swings = np.diff(np.log(eps_hist.to_numpy())) if len(eps_hist) >= 3 else np.array([0.15])
    spread = float(np.std(swings) / math.sqrt(max(len(swings), 1)))
    known = [g for g in (inputs.get("historical"), inputs.get("sustainable")) if g is not None]
    if len(known) == 2:
        spread = max(spread, abs(known[0] - known[1]) / 2)
    spread = min(max(spread, 0.015), 0.06)

    rng = np.random.default_rng(seed)
    g = np.clip(rng.normal(v.get("growth") or 0.0, spread, MC_DRAWS), -0.05, 0.15)
    exit_pe = rng.triangular(low, min(max(mid, low), high), high, MC_DRAWS)
    payout = min(max(v.get("payout") or 0.0, 0.0), 1.0)
    years = np.arange(1, 11)
    eps_path = s["eps"] * (1 + g[:, None]) ** years
    total = eps_path[:, -1] * exit_pe + (eps_path * payout).sum(axis=1)
    returns = np.where(total > 0, np.power(np.maximum(total, 1e-9) / price, 0.1) - 1, -1.0)

    counts, _ = np.histogram(np.clip(returns, MC_BINS[0], MC_BINS[-1] - 1e-9), bins=MC_BINS)
    pct = np.percentile(returns, [10, 25, 50, 75, 90])
    return {
        "p10": pct[0], "p25": pct[1], "p50": pct[2], "p75": pct[3], "p90": pct[4],
        "prob_hurdle": float((returns >= config.HURDLE_RATE).mean()),
        "prob_loss": float((returns < 0).mean()),
        "bins": MC_BINS, "counts": [int(c) for c in counts], "draws": MC_DRAWS,
        "growth_spread": spread, "pe_range": [low, high],
    }


def compute(t: pd.DataFrame, y: pd.DataFrame, s: dict, v: dict, profile: str,
            sector: "str | None" = None, sic=None, to_quote: float = 1.0) -> dict:
    """all lenses for one company. statements are in their own currency; to_quote
    turns a statement-currency price into the one the shares trade in."""
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
    for key, found in (("dcf", owner_earnings_dcf(y, s, v) if price else None),
                       ("ddm", ddm(s, v) if price else None)):
        if found:
            found["value"] *= to_quote
            for per_share in ("owner_earnings_per_share", "dps"):
                if per_share in found:
                    found[per_share] *= to_quote
            found["vs_price"] = found["value"] / price - 1
            out[key] = found
    out["monte_carlo"] = monte_carlo(y, s, v, price_stmt) if price else None
    return {k: _plain(val) for k, val in out.items() if val}


def _plain(d: dict) -> dict:
    """numpy scalars to python ones, so the payload goes through json as is."""
    def one(v):
        if isinstance(v, dict):
            return _plain(v)
        if isinstance(v, list):
            return [one(x) for x in v]
        return v.item() if hasattr(v, "item") and hasattr(v, "dtype") else v
    return {k: one(v) for k, v in d.items()}
