from datetime import date

import pandas as pd
import pytest

from value_investor import audit
from value_investor.edgar import COLUMNS


def fact(taxonomy, concept, value, year, unit="JPY"):
    end = date(year, 3, 31)
    return (taxonomy, concept, unit, date(year - 1, 4, 1), end, value, "x", date(year, 6, 30), None)


def test_each_source_is_measured_against_yahoo_line_by_line():
    rows = []
    for year, ni in ((2024, 100.0), (2025, 110.0)):
        rows += [fact("yahoo", "Net Income Common Stockholders", ni, year), fact("yahoo", "Total Revenue", 1000.0, year)]
    rows += [fact("irbank", "net_income", 101.0, 2024), fact("irbank", "net_income", 110.0, 2025),
             fact("irbank", "revenue", 1300.0, 2025), fact("irbank", "net_income", 90.0, 2023)]
    gaps = {(s, line, end): g for s, line, end, g in audit.deviations(pd.DataFrame(rows, columns=COLUMNS))}
    assert gaps[("irbank", "net_income", date(2024, 3, 31))] == pytest.approx(0.01)
    assert gaps[("irbank", "net_income", date(2025, 3, 31))] == pytest.approx(0.0)
    assert gaps[("irbank", "revenue", date(2025, 3, 31))] == pytest.approx(0.3)
    assert not any(end == date(2023, 3, 31) for _, _, end in gaps)        # yahoo doesn't have 2023


def test_a_source_in_another_currency_is_not_compared():
    rows = [fact("yahoo", "Net Income Common Stockholders", 100.0, 2025, "EUR"),
            fact("biznesradar", "net_income", 430.0, 2025, "PLN")]
    assert audit.deviations(pd.DataFrame(rows, columns=COLUMNS)) == []


def test_summary_counts_years_within_two_and_ten_percent():
    rows = [(1, "JPN", "irbank", "net_income", date(2025, 3, 31), 0.01),
            (1, "JPN", "irbank", "net_income", date(2024, 3, 31), 0.05),
            (2, "JPN", "irbank", "net_income", date(2025, 3, 31), 0.5)]
    (s,) = audit.summarise(rows)
    assert s["name"] == "IRBANK" and s["companies"] == 2 and s["markets"] == ["JPN"]
    line = s["lines"]["net_income"]
    assert line["pairs"] == 3 and line["close"] == pytest.approx(1 / 3) and line["near"] == pytest.approx(2 / 3)
