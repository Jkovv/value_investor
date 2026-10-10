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



def test_kuwait_quotes_in_fils():
    assert fx.major("KWF") == ("KWD", 1000.0)


def test_the_size_floor_follows_the_screener_units():
    assert yahoo.screener_floor("EUR", 1e9, 0.92) == pytest.approx(0.92e9)
    assert yahoo.screener_floor("GBP", 1e9, 0.75) == pytest.approx(75e9)       # pence
    assert yahoo.screener_floor("KWD", 1e9, 0.307) == pytest.approx(307e9)     # fils


def test_peer_size_reads_market_cap_in_the_major_unit(monkeypatch):
    from value_investor import peers
    monkeypatch.setattr(fx, "rate", lambda con, base, quote, when=None, fetch=True: 1.25 if base == "GBP" else None)
    assert peers._cap_usd(None, 47e9, "GBp") == pytest.approx(47e9 * 1.25)


def test_exchange_codes_map_to_their_country():
    assert yahoo._market_iso3("sr_market") == "SAU"
    assert yahoo._market_iso3("tl_market") == "EST"
    assert yahoo._market_iso3("pl_market") == "POL"
    assert yahoo._market_iso3("xx_market") is None


def test_funds_and_trusts_are_told_apart_from_businesses():
    from value_investor.screener import looks_like_fund
    assert looks_like_fund("Sprott Physical Silver Trust", "Asset Management", "")
    assert looks_like_fund("Polar Capital Technology Ord", "Asset Management", "")
    assert looks_like_fund("Ruffer Investment Company Limited", None,
                           "Ruffer Investment Company Limited is a closed-ended investment company.")
    assert not looks_like_fund("Jupiter Fund Management Plc", "Asset Management", "")
    assert not looks_like_fund("Chemtrade Logistics Income Fund", "Chemicals", "")
    assert not looks_like_fund("Granite Ord", None, "Granite is a real estate investment trust.")
