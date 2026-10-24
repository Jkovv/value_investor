"""what kind of durable advantage ten years of statements point to: a product people
come back for, a service others can't do without, being the low-cost operator, or none.
"""

from value_investor import config

KINDS = {
    "unique product": "People come back for it and pay up: a brand.",
    "unique service": "Others can't easily do without it: a toll bridge.",
    "low-cost operator": "It buys and sells cheaper than anyone, year after year.",
    "none": "No durable advantage shows in the numbers.",
}
SHORT = {"unique product": "Product", "unique service": "Service", "low-cost operator": "Low cost", "none": "None"}
# yahoo gives no sic code outside the us, so banks and insurers are told apart by industry
FINANCIAL = ("bank", "insurance", "reit", "mortgage")
STEADY_SWING = 0.03             # a low-margin business needs an even steadier margin than a high-margin one


def _num(s: dict, key: str) -> "float | None":
    v = s.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _tone(v: "float | None", good: float, poor: float, higher: bool = True) -> str:
    if v is None:
        return "na"
    if higher:
        return "pass" if v >= good else "fail" if v < poor else "warn"
    return "pass" if v <= good else "fail" if v > poor else "warn"


def evidence(s: dict) -> list:
    """the book's signs of a durable advantage, as (label, reading, tone)."""
    out = []
    gm, gm_sd = _num(s, "gross_margin"), _num(s, "gross_margin_std")
    if gm is not None:
        tone = _tone(gm, config.GROSS_MARGIN_GOOD, config.GROSS_MARGIN_POOR)
        if gm_sd is not None and gm_sd > config.GROSS_MARGIN_MAX_SWING:
            tone = "warn" if tone == "pass" else tone
        out.append(("Gross margin", f"{gm:.0%}" + (f", ± {gm_sd * 100:.0f} pts" if gm_sd is not None else ""), tone))
    else:
        om, om_sd = _num(s, "operating_margin"), _num(s, "operating_margin_std")
        if om is not None:
            out.append(("Operating margin", f"{om:.0%}" + (f", ± {om_sd * 100:.0f} pts" if om_sd is not None else ""),
                        _tone(om, config.OPERATING_MARGIN_GOOD, config.OPERATING_MARGIN_POOR)))
    sga = _num(s, "sga_to_gp")
    if sga is not None:
        out.append(("SG&A of gross profit", f"{sga:.0%}",
                    _tone(sga, config.SGA_TO_GROSS_PROFIT_GOOD, config.SGA_TO_GROSS_PROFIT_POOR, higher=False)))
    capex = _num(s, "capex_to_ni")
    if capex is not None:
        out.append(("Capex of net income", f"{capex:.0%}",
                    _tone(capex, config.CAPEX_TO_EARNINGS_GOOD, config.CAPEX_TO_EARNINGS_POOR, higher=False)))
    roe = _num(s, "roe_good_share")
    if roe is not None:
        out.append((f"ROE above {config.ROE_GOOD:.0%}", f"in {roe:.0%} of years",
                    _tone(roe, config.ROE_CONSISTENT_YEARS, 0.5)))
    up, losses = _num(s, "eps_up_share"), _num(s, "loss_years")
    if up is not None:
        out.append(("EPS up on the year", f"in {up:.0%} of years" + (f", {losses:.0f} with a loss" if losses else ""),
                    "fail" if losses else _tone(up, config.EPS_UP_YEARS_GOOD, config.EPS_UP_YEARS_POOR)))
    debt = _num(s, "debt_years")
    if debt is not None:
        out.append(("Long-term debt", f"{debt:.1f} years of earnings",
                    _tone(debt, config.DEBT_PAYOFF_YEARS_GOOD, config.DEBT_PAYOFF_YEARS_POOR, higher=False)))
    return out


def classify(s: dict, profile: str = "general", industry: "str | None" = None) -> dict:
    """{kind, short, why, evidence}; kind is None when the question doesn't apply or can't be told."""
    if profile == "financial" or any(w in (industry or "").lower() for w in FINANCIAL):
        return {"kind": None, "short": "-", "why": "Banks and insurers are judged on their own checklist.",
                "evidence": []}
    if (s.get("history_years") or 0) < 5:
        return {"kind": None, "short": "-", "why": "Too little history to tell.", "evidence": evidence(s)}
    gm, gm_sd = _num(s, "gross_margin"), _num(s, "gross_margin_std")
    om, om_sd = _num(s, "operating_margin"), _num(s, "operating_margin_std")
    net, capex = _num(s, "net_margin"), _num(s, "capex_to_ni")
    roe, up, losses = _num(s, "roe_good_share"), _num(s, "eps_up_share"), _num(s, "loss_years") or 0
    turnover = _num(s, "gp_to_assets")
    steady = losses == 0 and ((roe or 0) >= 0.6 or (net or 0) >= config.NET_MARGIN_GOOD)

    if (gm is not None and gm >= config.GROSS_MARGIN_GOOD and gm_sd is not None
            and gm_sd <= config.GROSS_MARGIN_MAX_SWING and (net or 0) >= config.NET_MARGIN_POOR and steady):
        kind = "unique product"
    elif (gm is None and om is not None and om >= config.OPERATING_MARGIN_GOOD and om_sd is not None
            and om_sd <= config.GROSS_MARGIN_MAX_SWING and (capex if capex is not None else 0) <= config.CAPEX_TO_EARNINGS_POOR
            and steady):
        kind = "unique service"
    elif (losses == 0 and (roe or 0) >= config.ROE_CONSISTENT_YEARS and (up or 0) >= config.EPS_UP_YEARS_GOOD
            and ((gm is not None and gm_sd is not None and gm_sd <= STEADY_SWING and (turnover or 0) >= 0.3)
                 or (gm is None and om_sd is not None and om_sd <= STEADY_SWING))):
        kind = "low-cost operator"
    else:
        kind = "none"
    return {"kind": kind, "short": SHORT[kind], "why": KINDS[kind], "evidence": evidence(s)}
