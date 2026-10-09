import pandas as pd
import pytest

from value_investor import concepts, metrics, rules


def statements_frame(years=10, **overrides):
    index = pd.to_datetime([f"{2015 + i}-12-31" for i in range(years)])
    base = {field: [float("nan")] * years for field in concepts.FIELDS}
    base.update({
        "revenue": [1000.0 * 1.05 ** i for i in range(years)],
        "gross_profit": [600.0 * 1.05 ** i for i in range(years)],
        "sga": [150.0 * 1.05 ** i for i in range(years)],
        "operating_income": [400.0 * 1.05 ** i for i in range(years)],
        "interest_expense": [10.0] * years,
        "pretax_income": [390.0 * 1.05 ** i for i in range(years)],
        "income_tax": [80.0 * 1.05 ** i for i in range(years)],
        "net_income": [250.0 * 1.06 ** i for i in range(years)],
        "shares_diluted": [100.0 - i for i in range(years)],
        "equity": [1000.0 + 50 * i for i in range(years)],
        "total_assets": [2000.0] * years,
        "total_liabilities": [800.0] * years,
        "long_term_debt": [300.0] * years,
        "capex": [30.0] * years,
        "operating_cash_flow": [280.0 * 1.06 ** i for i in range(years)],
        "dividends_paid": [100.0] * years,
        "buybacks": [50.0] * years,
        "retained_earnings": [500.0 + 100 * i for i in range(years)],
    })
    base.update(overrides)
    frame = pd.DataFrame(base, index=index)
    for col in ("shares_diluted_filed", "eps_diluted_filed", "dps_declared_filed"):
        frame[col] = pd.NaT
    return frame


def test_split_factor_only_touches_numbers_filed_before_the_split():
    filed = pd.Series(pd.to_datetime(["2019-02-01", "2021-02-01"]))
    splits = pd.Series({pd.Timestamp("2020-08-31"): 4.0})
    assert metrics.split_factors(filed, splits).tolist() == [4.0, 1.0]


def test_summary_of_a_steady_compounder():
    y = metrics.yearly(statements_frame())
    s = metrics.summary(y)
    assert s["history_years"] == 10
    assert s["gross_margin"] == pytest.approx(0.6)
    assert s["sga_to_gp"] == pytest.approx(0.25)
    assert s["eps_up_share"] == 1.0
    assert s["loss_years"] == 0
    assert s["share_change"] < 0
    assert s["capex_to_ni"] < 0.25


def test_steady_compounder_passes_the_gate_level_score():
    y = metrics.yearly(statements_frame())
    checks = rules.evaluate(metrics.summary(y), "general")
    quality, completeness = rules.score(checks)
    assert quality >= 85
    assert completeness > 0.9
    by_key = {c.key: c.status for c in checks}
    assert by_key["gross_margin"] == "pass"
    assert by_key["capex"] == "pass"


def test_bad_share_tags_are_rebuilt_from_reported_eps():
    frame = statements_frame(years=4)
    frame["eps_diluted"] = frame["net_income"] / 100.0
    frame["shares_diluted"] = [100.0, 100.0, 0.0001, 0.0001]
    y = metrics.yearly(frame)
    assert y["shares"].round(6).tolist() == [100.0, 100.0, 100.0, 100.0]
    assert y["shares_corrected"].tolist() == [False, False, True, True]


def test_missing_data_lowers_completeness_not_quality():
    frame = statements_frame(gross_profit=[float("nan")] * 10, sga=[float("nan")] * 10)
    checks = rules.evaluate(metrics.summary(metrics.yearly(frame)), "general")
    quality, completeness = rules.score(checks)
    labels = {c.key: c.label for c in checks}
    assert labels["gross_margin"].startswith("Operating margin")
    assert completeness < 1.0
    assert quality >= 80


def test_financials_get_the_short_list():
    assert rules.profile_for(6022) == "financial"
    assert rules.profile_for(2080) == "general"
    keys = {c.key for c in rules.evaluate({}, "financial")}
    assert "gross_margin" not in keys and "roe" in keys
