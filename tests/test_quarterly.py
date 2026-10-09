from datetime import date

import pandas as pd
import pytest

from value_investor import quarterly
from value_investor.edgar import COLUMNS


def fact(concept, start, end, value, form="10-Q", filed=None):
    end = pd.Timestamp(end).date()
    return ("us-gaap", concept, "USD", pd.Timestamp(start).date(), end, float(value), form,
            filed or (pd.Timestamp(end) + pd.Timedelta(days=35)).date(), "x")


def year(y, revenue, income, q_days=(90, 91, 92, 92)):
    """10-Q style facts for one calendar fiscal year: Q1 and Q2 direct, Q3 only as nine months,
    Q4 only through the annual total."""
    start = pd.Timestamp(f"{y}-01-01")
    ends = [start + pd.Timedelta(days=sum(q_days[:i + 1]) - 1) for i in range(4)]
    q, a = [], []
    for concept, values in (("Revenues", revenue), ("NetIncomeLoss", income)):
        q.append(fact(concept, start, ends[0], values[0]))
        q.append(fact(concept, ends[0] + pd.Timedelta(days=1), ends[1], values[1]))
        q.append(fact(concept, start, ends[1], sum(values[:2])))
        q.append(fact(concept, start, ends[2], sum(values[:3])))
        a.append(fact(concept, start, ends[3], sum(values), form="10-K"))
    return q, a


def frames(*years):
    q, a = [], []
    for qq, aa in years:
        q += qq
        a += aa
    return pd.DataFrame(q, columns=COLUMNS), pd.DataFrame(a, columns=COLUMNS)


def test_missing_quarters_come_from_running_totals():
    q, a = frames(year(2024, [100, 110, 120, 130], [10, 11, 12, 13]))
    t = quarterly.table(q, a, "USD")
    assert t["revenue"].tolist() == [100, 110, 120, 130]
    assert t["net_income"].tolist() == [10, 11, 12, 13]


def test_year_over_year_and_trailing_twelve_months():
    q, a = frames(year(2023, [100, 100, 100, 100], [10, 10, 10, 10]),
                  year(2024, [110, 120, 90, 95], [12, 13, 8, 9]))
    t = quarterly.table(q, a, "USD")
    assert t["revenue_yoy"].iloc[-1] == pytest.approx(-0.05)
    assert t["revenue_yoy"].iloc[-4] == pytest.approx(0.10)
    s = quarterly.summary(t, annual_net_income=40)
    assert s["ttm_revenue"] == 415
    assert s["ttm_net_income"] == 42
    assert s["ttm_vs_year"] == pytest.approx(0.05)
    assert s["trend"] == "slipping"
    assert s["revenue_up"] == 2 and s["revenue_known"] == 4


def test_a_sixteen_week_fourth_quarter_is_still_a_quarter():
    q, a = frames(year(2024, [84, 84, 84, 112], [8, 8, 8, 11], q_days=(84, 84, 84, 112)))
    t = quarterly.table(q, a, "USD")
    assert t["revenue"].tolist() == [84, 84, 84, 112]


def test_half_year_without_a_first_quarter_is_not_taken_for_a_quarter():
    q, a = frames(year(2024, [100, 110, 120, 130], [10, 11, 12, 13]))
    q = q[~((q["period_start"] == date(2024, 1, 1)) & (q["period_end"] == date(2024, 3, 30)))]
    t = quarterly.table(q, a, "USD")
    assert 210 not in t["revenue"].tolist()


def test_restated_quarter_keeps_the_latest_filing():
    q, a = frames(year(2024, [100, 110, 120, 130], [10, 11, 12, 13]))
    restated = fact("Revenues", "2024-01-01", q["period_end"].iloc[0], 105, filed=date(2025, 5, 1))
    q = pd.concat([q, pd.DataFrame([restated], columns=COLUMNS)], ignore_index=True)
    assert quarterly.table(q, a, "USD")["revenue"].iloc[0] == 105
    assert quarterly.table(q, a, "USD", as_of="2025-01-01")["revenue"].iloc[0] == 100


def test_growing_and_mixed():
    q, a = frames(year(2023, [100] * 4, [10] * 4), year(2024, [104, 106, 108, 110], [11, 11, 12, 12]))
    assert quarterly.summary(quarterly.table(q, a, "USD"))["trend"] == "growing"
    q, a = frames(year(2023, [100] * 4, [10] * 4), year(2024, [104, 106, 108, 110], [11, 11, 12, 9]))
    assert quarterly.summary(quarterly.table(q, a, "USD"))["trend"] == "mixed"
