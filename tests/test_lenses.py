import json
import math

import pandas as pd
import pytest

from value_investor import lenses, metrics, screener
from tests.test_metrics_and_rules import statements_frame


def compounder(**overrides):
    base = dict(current_assets=[900.0] * 10, current_liabilities=[400.0] * 10, cash=[200.0] * 10,
                ppe=[600.0] * 10, short_term_debt=[0.0] * 10)
    base.update(overrides)
    t = statements_frame(**base)
    y = metrics.yearly(t)
    return t, y, metrics.summary(y)


def priced(s, price=40.0, growth=0.06, bond=0.04):
    return {"available": True, "price": price, "market_cap": price * s["shares"], "pe_now": price / s["eps"],
            "growth": growth, "bond_yield": bond, "dividend_yield": 0.02}


def test_piotroski_on_an_improving_business():
    t, _, _ = compounder()
    f = lenses.piotroski(t)
    tests = f["tests"]
    assert tests["Positive return on assets"] and tests["No new shares issued"]
    assert tests["Return on assets improved"]
    assert tests["Gross margin improved"] is False   # flat margin is not an improvement
    assert 0 <= f["scaled"] <= 9 and f["of"] == 9


def test_piotroski_skips_tests_without_data_and_scales_to_nine():
    t, _, _ = compounder(current_assets=[float("nan")] * 10, gross_profit=[float("nan")] * 10)
    f = lenses.piotroski(t)
    assert f["of"] == 7
    assert f["tests"]["Current ratio improved"] is None
    assert f["scaled"] == round(f["score"] * 9 / 7)


def test_altman_by_hand():
    t, _, _ = compounder()
    now = t.iloc[-1]
    cap = 5000.0
    expected = (1.2 * 500 / 2000 + 1.4 * now.retained_earnings / 2000 + 3.3 * now.operating_income / 2000
                + 0.6 * cap / 800 + 1.0 * now.revenue / 2000)
    a = lenses.altman(t, cap)
    assert a["z"] == pytest.approx(expected)
    assert a["zone"] == "safe"


def test_altman_falls_back_to_assets_minus_equity():
    t, _, _ = compounder(total_liabilities=[float("nan")] * 10)
    assert lenses.altman(t, 5000.0) is not None


def test_graham_number_and_defensive_tests():
    t, y, s = compounder()
    g = lenses.graham(y, s, 10.0, t, "general")
    assert g["number"] == pytest.approx(math.sqrt(22.5 * s["eps"] * s["bvps"]))
    assert g["tests"]["Current ratio of 2 or more"] is True
    assert g["tests"]["Earnings positive every year"] is True
    assert g["years"] == 10


def test_graham_drops_balance_sheet_tests_for_financials():
    t, y, s = compounder()
    g = lenses.graham(y, s, 10.0, t, "financial")
    assert "Current ratio of 2 or more" not in g["tests"]


def test_magic_formula():
    t, _, _ = compounder()
    m = lenses.magic_formula(t, 5000.0)
    ebit = t.iloc[-1].operating_income
    assert m["earnings_yield"] == pytest.approx(ebit / (5000 + 300 - 200))
    assert m["return_on_capital"] == pytest.approx(ebit / (500 + 600))


def test_magic_formula_without_tagged_operating_income():
    t, _, _ = compounder(operating_income=[float("nan")] * 10)
    now = t.iloc[-1]
    m = lenses.magic_formula(t, 5000.0)
    assert m["earnings_yield"] == pytest.approx((now.pretax_income + 10.0) / 5100)


def test_lynch_categories():
    assert lenses.lynch({"eps_cagr_smoothed": 0.03}, {})["category"] == "Slow grower"
    assert lenses.lynch({"eps_cagr_smoothed": 0.10}, {})["category"] == "Stalwart"
    assert lenses.lynch({"eps_cagr_smoothed": 0.25}, {})["category"] == "Fast grower"
    assert lenses.lynch({"eps_cagr_smoothed": 0.10, "loss_years": 2, "eps": 1.0}, {})["category"] == "Turnaround"
    steel = {"eps_cagr_smoothed": 0.10, "eps_up_share": 0.4}
    assert lenses.lynch(steel, {}, sic="3312")["category"] == "Cyclical"
    assert lenses.lynch(steel, {}, sector="Technology")["category"] == "Stalwart"


def test_peg():
    ly = lenses.lynch({"eps_cagr_smoothed": 0.10}, {"available": True, "pe_now": 15.0, "dividend_yield": 0.05})
    assert ly["peg"] == pytest.approx(1.5)
    assert ly["pegy"] == pytest.approx(1.0)


def test_dcf_is_worth_more_with_more_growth_and_less_with_higher_rates():
    _, y, s = compounder()
    base = lenses.owner_earnings_dcf(y, s, priced(s))
    faster = lenses.owner_earnings_dcf(y, s, priced(s, growth=0.12))
    dearer_money = lenses.owner_earnings_dcf(y, s, priced(s, bond=0.08))
    assert faster["value"] > base["value"] > dearer_money["value"]
    assert base["discount"] == pytest.approx(0.09)        # floor
    assert dearer_money["discount"] == pytest.approx(0.13)
    assert 0 < base["terminal_share"] < 1


def test_compute_converts_per_share_values_to_the_quote_currency():
    t, y, s = compounder()
    v = priced(s)
    plain = lenses.compute(t, y, s, v, "general")
    v_quoted = dict(v, price=v["price"] * 4.0)       # same price, quoted in a currency worth a quarter
    quoted = lenses.compute(t, y, s, v_quoted, "general", to_quote=4.0)
    assert quoted["graham"]["number"] == pytest.approx(plain["graham"]["number"] * 4)
    assert quoted["dcf"]["value"] == pytest.approx(plain["dcf"]["value"] * 4)
    assert quoted["dcf"]["vs_price"] == pytest.approx(plain["dcf"]["vs_price"])
    assert quoted["graham"]["vs_price"] == pytest.approx(plain["graham"]["vs_price"])


def test_compute_without_a_price_and_round_trips_through_json():
    t, y, s = compounder()
    out = lenses.compute(t, y, s, {"available": False}, "general")
    assert "dcf" not in out and "magic" not in out
    assert "piotroski" in out and "lynch" in out
    assert json.loads(json.dumps(out)) == out


def test_compute_ignores_a_nan_price():
    t, y, s = compounder()
    out = lenses.compute(t, y, s, dict(priced(s), price=float("nan")), "general")
    assert "dcf" not in out and "altman" not in out


def test_magic_rank_adds_the_two_places():
    df = pd.DataFrame({"earnings_yield": [0.10, 0.05, 0.08, None],
                       "return_on_capital": [0.30, 0.20, 0.50, 0.90]})
    assert screener.magic_rank(df).tolist()[:3] == [1, 3, 1]
    assert pd.isna(screener.magic_rank(df).iloc[3])
