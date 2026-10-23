from datetime import date

import numpy as np
import pandas as pd
import pytest

from value_investor import study


def prices(rows):
    return pd.DataFrame(rows, columns=["date", "close", "dividend"]).assign(date=lambda d: pd.to_datetime(d["date"]))


def test_dividends_are_reinvested_in_the_return():
    p = prices([("2020-06-30", 100.0, 0.0), ("2020-12-15", 100.0, 5.0), ("2021-06-30", 110.0, 0.0)])
    tri = study.total_return_index(p)
    assert study.forward_return(tri, "2020-06-30", 1) == pytest.approx(1.05 * 1.10 - 1)


def test_no_return_without_a_price_near_both_ends():
    p = prices([("2020-06-30", 100.0, 0.0), ("2021-05-01", 120.0, 0.0)])
    tri = study.total_return_index(p)
    assert study.forward_return(tri, "2020-06-30", 1) is None          # data ends before a year is up
    assert study.forward_return(tri, "2019-06-30", 1) is None          # no price a year before


def test_formation_dates_are_each_june_up_to_today():
    dates = study.formation_dates(today="2012-07-01")
    assert dates == [pd.Timestamp(2010, 6, 30), pd.Timestamp(2011, 6, 30), pd.Timestamp(2012, 6, 30)]


def test_only_years_filed_by_the_day_count():
    facts = pd.DataFrame({"period_start": [date(2018, 1, 1), date(2019, 1, 1), date(2019, 10, 1)],
                          "period_end": [date(2018, 12, 31), date(2019, 12, 31), date(2019, 12, 31)],
                          "filed": [date(2019, 3, 1), date(2020, 3, 1), date(2020, 1, 30)]})
    assert study.years_filed(facts, "2019-06-30") == 1
    assert study.years_filed(facts, "2020-06-30") == 2


def test_overlapping_observations_widen_the_t_statistic():
    x = np.array([0.02, 0.03, 0.025, 0.04, 0.01, 0.03, 0.035, 0.02])
    plain = x.mean() / (x.std() / np.sqrt(len(x)))
    assert study.newey_west_t(x, 0) == pytest.approx(plain)
    trending = np.repeat([0.01, 0.05], 4)
    assert study.newey_west_t(trending, 2) < study.newey_west_t(trending, 0)


def panel(n=40, years=(2019, 2020, 2021), seed=1):
    rng = np.random.default_rng(seed)
    rows = []
    for y in years:
        for market in ("JPN", "POL"):
            q = rng.uniform(0, 100, n)
            r1 = q / 1000 + rng.normal(0, 0.01, n)           # the better half really does better
            for i in range(n):
                rows.append({"cik": i, "market": market, "date": date(y, 6, 30), "quality": q[i], "gate": q[i] > 50,
                             "rankable": True, "expected_return": q[i] / 500, "f_score": int(q[i] // 12),
                             "r1": r1[i], "r3": (1 + r1[i]) ** 3 - 1})
    return pd.DataFrame(rows)


def test_a_signal_that_works_shows_a_rising_line_of_fifths():
    cs = study.cross_sections(panel(), "quality", 1)
    assert len(cs) == 6 and (cs["ic"] > 0.8).all()
    s = study.summarise(cs, 1)["pooled"]
    assert s["fifths"] == sorted(s["fifths"]) and s["spread"] > 0 and s["ic_t"] > 3
    assert set(study.summarise(cs, 1)["markets"]) == {"JPN", "POL"}


def test_a_market_with_too_few_companies_is_left_out():
    assert study.cross_sections(panel(n=10), "quality", 1).empty


def test_gate_gap_and_calibration():
    p = panel()
    g = study.gate_gap(p, 1)
    assert g["gap"] > 0 and 0.3 < g["passing_share"] < 0.7
    cal = study.calibration(p, 3)
    assert [c["bucket"] for c in cal] == ["10 to 15%", "15 to 20%"]
    assert cal[1]["realised"] > cal[0]["realised"]
