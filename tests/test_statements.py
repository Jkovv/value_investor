import pandas as pd

from value_investor import statements


def fact(concept, end, value, filed, start=None, unit="USD", taxonomy="us-gaap"):
    return {
        "taxonomy": taxonomy, "concept": concept, "unit": unit,
        "period_start": pd.Timestamp(start).date() if start else None,
        "period_end": pd.Timestamp(end).date(), "value": value,
        "form": "10-K", "filed": pd.Timestamp(filed).date(), "accn": filed,
    }


def year(concept, fy, value, filed, unit="USD"):
    return fact(concept, f"{fy}-12-31", value, filed, start=f"{fy}-01-01", unit=unit)


def test_years_are_keyed_by_period_not_filing_year():
    facts = pd.DataFrame([
        year("NetIncomeLoss", 2022, 100.0, "2023-02-15"),
        year("NetIncomeLoss", 2022, 100.0, "2024-02-15"),
        year("NetIncomeLoss", 2023, 120.0, "2024-02-15"),
    ])
    table = statements.annual_statements(facts)
    assert list(table.index.year) == [2022, 2023]
    assert table["net_income"].tolist() == [100.0, 120.0]


def test_restatement_respects_as_of():
    facts = pd.DataFrame([
        year("NetIncomeLoss", 2022, 100.0, "2023-02-15"),
        year("NetIncomeLoss", 2022, 90.0, "2024-02-15"),
        year("NetIncomeLoss", 2023, 120.0, "2024-02-15"),
    ])
    assert statements.annual_statements(facts)["net_income"].iloc[0] == 90.0
    then = statements.annual_statements(facts, as_of="2023-06-30")
    assert list(then.index.year) == [2022]
    assert then["net_income"].iloc[0] == 100.0


def test_tag_change_mid_history_keeps_every_year():
    facts = pd.DataFrame([
        year("SalesRevenueNet", 2016, 1000.0, "2017-02-15"),
        year("RevenueFromContractWithCustomerExcludingAssessedTax", 2018, 1200.0, "2019-02-15"),
        year("NetIncomeLoss", 2016, 100.0, "2017-02-15"),
        year("NetIncomeLoss", 2018, 130.0, "2019-02-15"),
    ])
    table = statements.annual_statements(facts)
    assert table["revenue"].tolist() == [1000.0, 1200.0]


def test_gross_profit_and_liabilities_are_derived_when_missing():
    facts = pd.DataFrame([
        year("NetIncomeLoss", 2023, 50.0, "2024-02-15"),
        year("Revenues", 2023, 500.0, "2024-02-15"),
        year("CostOfRevenue", 2023, 300.0, "2024-02-15"),
        fact("LiabilitiesAndStockholdersEquity", "2023-12-31", 900.0, "2024-02-15"),
        fact("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "2023-12-31", 400.0, "2024-02-15"),
    ])
    row = statements.annual_statements(facts).iloc[0]
    assert row["gross_profit"] == 200.0
    assert row["total_liabilities"] == 500.0


def test_sum_alternative_adds_up_parts():
    facts = pd.DataFrame([
        year("NetIncomeLoss", 2023, 50.0, "2024-02-15"),
        year("SellingAndMarketingExpense", 2023, 30.0, "2024-02-15"),
        year("GeneralAndAdministrativeExpense", 2023, 20.0, "2024-02-15"),
    ])
    assert statements.annual_statements(facts)["sga"].iloc[0] == 50.0


def test_split_is_read_off_restated_share_counts():
    facts = pd.DataFrame([
        year("WeightedAverageNumberOfDilutedSharesOutstanding", 2019, 1_000.0, "2020-02-15", unit="shares"),
        year("WeightedAverageNumberOfDilutedSharesOutstanding", 2019, 4_000.0, "2021-02-15", unit="shares"),
        year("EarningsPerShareDiluted", 2019, 8.0, "2020-02-15", unit="USD/shares"),
        year("EarningsPerShareDiluted", 2019, 2.0, "2021-02-15", unit="USD/shares"),
    ])
    splits = statements.inferred_splits(facts)
    assert splits.to_dict() == {pd.Timestamp("2021-02-15"): 4.0}


def test_scale_errors_are_not_mistaken_for_splits():
    facts = pd.DataFrame([
        year("WeightedAverageNumberOfDilutedSharesOutstanding", 2021, 751_800_000.0, "2022-02-15", unit="shares"),
        year("WeightedAverageNumberOfDilutedSharesOutstanding", 2021, 751.8, "2024-02-15", unit="shares"),
    ])
    assert statements.inferred_splits(facts).empty


def test_old_prices_are_put_back_in_the_share_units_of_their_day():
    import pandas as pd
    from value_investor import prices as px
    frame = pd.DataFrame({"date": pd.to_datetime(["2020-06-30", "2021-07-20", "2024-06-10"]),
                          "high": [10.0, 12.0, 13.0], "low": [9.0, 11.0, 12.0], "close": [9.5, 11.5, 12.5],
                          "dividend": [0.1, 0.0, 0.0], "split": [0.0, 4.0, 10.0]})
    then = px.as_quoted_on(frame, "2020-06-30")
    assert len(then) == 1 and then["close"].iloc[0] == 9.5 * 40 and then["dividend"].iloc[0] == 0.1 * 40
    assert px.as_quoted_on(frame, "2025-01-01")["close"].tolist() == [9.5, 11.5, 12.5]


def test_a_local_source_already_in_todays_units_is_not_split_again():
    import pandas as pd
    from value_investor import screener
    priced = pd.DataFrame({"date": pd.to_datetime(["2026-06-01", "2026-09-29"]), "close": [1.0, 1.0],
                           "split": [0.0, 5.0]})
    facts = pd.DataFrame({"filed": pd.to_datetime(["2026-06-29"])})
    # irbank fetched after tokyo electron's 5-for-1: its eps already counts it
    assert screener._splits(facts, priced, None, "irbank", fetched="2026-10-12").empty
    # fetched before the split: the split is still missing from its figures
    assert screener._splits(facts, priced, None, "irbank", fetched="2026-09-01").tolist() == [5.0]
