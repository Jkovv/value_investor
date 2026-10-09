import pandas as pd
import pytest

from value_investor import config, valuation


def flat_prices(price, start="2014-01-01", end="2025-12-31"):
    dates = pd.bdate_range(start, end)
    return pd.DataFrame({"date": dates, "high": price * 1.1, "low": price * 0.9, "close": price,
                         "dividend": 0.0, "split": 0.0})


def yearly_with_eps(eps_values):
    index = pd.to_datetime([f"{2016 + i}-12-31" for i in range(len(eps_values))])
    return pd.DataFrame({"eps": eps_values}, index=index)


def test_projection_matches_the_worked_example():
    # workbook-style example: EPS 1.18 growing 9.6% for 10 years at P/E 17.5 from a price of 14.80.
    future_eps = 1.18 * 1.096 ** 10
    assert future_eps == pytest.approx(2.95, abs=0.01)
    future_price = future_eps * 17.5
    assert future_price == pytest.approx(51.62, abs=0.1)
    assert (future_price / 14.80) ** 0.1 - 1 == pytest.approx(0.133, abs=0.001)


def test_value_uses_lower_of_historical_and_sustainable_growth():
    s = {"eps": 2.0, "eps_reported": 2.0, "eps_cagr_smoothed": 0.12, "roe_recent": 0.20, "payout": 0.5}
    out = valuation.value(yearly_with_eps([1.0] * 10), s, flat_prices(20.0), bond_yield=0.04)
    assert out["available"]
    assert out["growth"] == pytest.approx(0.10)
    assert out["pe"]["mid"] == pytest.approx(20.0)


def test_buy_price_gives_exactly_the_hurdle_rate():
    s = {"eps": 2.0, "eps_reported": 2.0, "eps_cagr_smoothed": 0.08, "roe_recent": 0.30, "payout": 0.2}
    out = valuation.value(yearly_with_eps([1.5] * 10), s, flat_prices(30.0), bond_yield=0.04)
    implied = (out["future_value"]["mid"] / out["buy_price"]) ** (1 / config.PROJECTION_YEARS) - 1
    assert implied == pytest.approx(config.HURDLE_RATE)


def test_growth_is_capped():
    s = {"eps": 2.0, "eps_reported": 2.0, "eps_cagr_smoothed": 0.40, "roe_recent": 0.60, "payout": 0.0}
    out = valuation.value(yearly_with_eps([1.0] * 10), s, flat_prices(20.0), bond_yield=0.04)
    assert out["growth"] == config.GROWTH_CAP


def test_no_valuation_without_positive_earnings():
    s = {"eps": -1.0, "eps_cagr_smoothed": 0.1}
    out = valuation.value(yearly_with_eps([1.0] * 10), s, flat_prices(20.0), bond_yield=0.04)
    assert not out["available"]


def test_sell_signal_at_pe_forty():
    s = {"eps": 1.0, "eps_reported": 1.0, "eps_cagr_smoothed": 0.05, "roe_recent": 0.2, "payout": 0.3}
    out = valuation.value(yearly_with_eps([1.0] * 10), s, flat_prices(45.0), bond_yield=0.04)
    assert out["sell_signal"]
