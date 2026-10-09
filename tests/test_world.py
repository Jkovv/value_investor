from datetime import date

import pandas as pd
import pytest

from value_investor import fx, markets, statements, yahoo


def test_subunit_quotes_move_to_the_major_currency():
    prices = pd.DataFrame({"date": pd.to_datetime(["2026-01-02"]), "high": [5200.0], "low": [5000.0],
                           "close": [5100.0], "dividend": [100.0], "split": [0.0]})
    out, code = fx.to_major(prices, "GBp")
    assert code == "GBP"
    assert out["close"].iloc[0] == 51.0 and out["dividend"].iloc[0] == 1.0
    same, code = fx.to_major(prices, "EUR")
    assert code == "EUR" and same is prices


def yahoo_frame(rows: dict, ends: list) -> pd.DataFrame:
    return pd.DataFrame(rows, index=pd.to_datetime(ends)).T


def test_yahoo_statements_feed_the_same_pipeline():
    ends = ["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"]
    income = yahoo_frame({
        "Total Revenue": [1200.0, 1100.0, 1000.0, 900.0],
        "Gross Profit": [600.0, 540.0, 480.0, 430.0],
        "Net Income Common Stockholders": [240.0, 210.0, 190.0, 160.0],
        "Diluted EPS": [2.4, 2.1, 1.9, 1.6],
        "Diluted Average Shares": [100.0, 100.0, 100.0, 100.0],
        "Some Row We Ignore": [1.0, 1.0, 1.0, 1.0],
    }, ends)
    balance = yahoo_frame({"Total Assets": [3000.0, 2900.0, 2800.0, 2700.0],
                           "Stockholders Equity": [1500.0, 1400.0, 1300.0, 1200.0]}, ends)
    rows = yahoo._facts_from(income, yahoo.INCOME_LIKE, "PLN") + yahoo._facts_from(balance, yahoo.BALANCE, "PLN")
    facts = pd.DataFrame(rows, columns=["taxonomy", "concept", "unit", "period_start", "period_end", "value",
                                        "form", "filed", "accn"])
    assert "Some Row We Ignore" not in set(facts["concept"])
    assert set(facts.loc[facts["concept"] == "Diluted EPS", "unit"]) == {"PLN/shares"}

    table = statements.annual_statements(facts)
    assert table.attrs["currency"] == "PLN"
    assert list(table.index.year) == [2022, 2023, 2024, 2025]
    assert table["revenue"].iloc[-1] == 1200.0
    assert table["equity"].iloc[-1] == 1500.0


def test_filing_date_is_estimated_after_period_end():
    frame = yahoo_frame({"Total Revenue": [100.0]}, ["2024-12-31"])
    (row,) = yahoo._facts_from(frame, yahoo.INCOME_LIKE, "EUR")
    assert row[7] == date(2025, 4, 30)


@pytest.mark.parametrize("info, market, expected", [
    ({"country": "Germany", "financialCurrency": "EUR"}, "POL", "DEU"),      # Allianz in Warsaw
    ({"country": "Switzerland", "financialCurrency": "CHF"}, "DEU", "CHE"),  # roche in Frankfurt
    ({"country": "Poland", "financialCurrency": "PLN"}, "POL", None),        # Orlen at home
    ({"country": "Netherlands", "financialCurrency": "EUR"}, "POL", "NLD"),  # euro member, euro reports
    ({"country": "Luxembourg", "financialCurrency": "USD"}, "BRA", None),    # home not covered
])
def test_home_listing_detection(info, market, expected):
    assert yahoo.home_elsewhere(info, market) == expected


def test_every_market_has_a_region_currency_and_iso2():
    assert len({m.region for m in markets.MARKETS}) == len(markets.MARKETS)
    for m in markets.MARKETS:
        assert m.currency and m.iso3 in markets.ISO2


def test_euro_inflation_comes_from_the_euro_area():
    assert markets.reference_country("EUR") == markets.EURO_AREA
    assert markets.reference_country("PLN") == "POL"
    assert markets.reference_country("XYZ") is None


def test_returns_in_high_inflation_currencies_shrink_in_the_base_currency(monkeypatch):
    rates = {"TRY": 0.40, "PLN": 0.04, "CHF": 0.01}
    monkeypatch.setattr(markets, "inflation", lambda con, ccy, years=5: rates.get(ccy))
    assert markets.to_base(None, 0.15, "PLN", "PLN") == 0.15
    in_pln_from_try = markets.to_base(None, 0.30, "TRY", "PLN")
    in_pln_from_chf = markets.to_base(None, 0.10, "CHF", "PLN")
    assert in_pln_from_try == pytest.approx(1.30 * 1.04 / 1.40 - 1)
    assert in_pln_from_try < 0
    assert in_pln_from_chf > 0.10
    assert markets.to_base(None, 0.10, "XYZ", "PLN") is None
