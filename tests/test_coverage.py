import contextlib

import pandas as pd

from value_investor import coverage


def test_no_estimates_means_no_analysts():
    got = coverage.reading({"marketCap": 2e9, "heldPercentInstitutions": 0.04, "heldPercentInsiders": 0.7})
    assert got == {"analysts": 0, "institutions": 0.04, "insiders": 0.7}
    assert coverage.reading({"marketCap": 2e9, "numberOfAnalystOpinions": 13})["analysts"] == 13


def test_a_listing_funds_own_but_nobody_estimates_is_unknown_not_neglected():
    assert coverage.reading({"marketCap": 2e9, "heldPercentInstitutions": 0.92})["analysts"] is None


def test_a_dead_ticker_gives_nothing():
    assert coverage.reading({}) is None


def test_cboe_copies_of_london_lines_are_read_in_london():
    assert coverage.quoted_where_followed("TRNL.XC") == "TRN.L"
    assert coverage.quoted_where_followed("DOM.WA") == "DOM.WA"


def frame():
    return pd.DataFrame([
        {"cik": 1, "market": "ISR", "passes_gate": True, "expected_return": 0.20, "analysts": 0},
        {"cik": 2, "market": "ISR", "passes_gate": True, "expected_return": 0.12, "analysts": 2},
        {"cik": 3, "market": "ISR", "passes_gate": False, "expected_return": None, "analysts": 1},
        {"cik": 4, "market": "USA", "passes_gate": True, "expected_return": 0.25, "analysts": 30},
        {"cik": 5, "market": "USA", "passes_gate": True, "expected_return": 0.18, "analysts": 3},
        {"cik": 6, "market": "USA", "passes_gate": True, "expected_return": 0.30, "analysts": None},
    ])


def test_off_the_radar_is_good_priced_and_barely_followed():
    assert coverage.off_radar(frame())["cik"].tolist() == [1, 5, 2]


def test_markets_come_thinnest_first():
    got = coverage.by_market(frame(), least=2)
    assert [m["market"] for m in got] == ["ISR", "USA"]
    assert got[0]["off_radar"] == 2 and got[0]["best"] == 0.20 and abs(got[0]["none"] - 1 / 3) < 1e-9


def test_the_radar_page_lists_markets_and_companies(monkeypatch):
    from fastapi.testclient import TestClient
    import app as dashboard

    rows = frame().assign(ticker=["AAA.TA", "BBB.TA", "CCC.TA", "BIG", "SML", "ODD"], name="Co", quality=80.0,
                          moat="-", price=10.0, buy_price=12.0, currency="USD", institutions=0.1)
    monkeypatch.setattr(dashboard.store, "connect", lambda read_only=False: contextlib.nullcontext(None))
    monkeypatch.setattr(dashboard.screener, "ranking", lambda con, only_gate=True: rows)
    monkeypatch.setattr(dashboard, "_moat_kinds", lambda con: {})
    by_market = coverage.by_market
    monkeypatch.setattr(coverage, "by_market", lambda df: by_market(df, least=2))
    page = TestClient(dashboard.app).get("/radar")
    assert page.status_code == 200 and "AAA.TA" in page.text and "Israel" in page.text and "BIG" not in page.text
    only = TestClient(dashboard.app).get("/radar?market=USA")
    assert "SML" in only.text and "AAA.TA" not in only.text
