from datetime import date, timedelta

import duckdb
import pandas as pd
import pytest

from value_investor import config, portfolio, store, track


def db():
    con = duckdb.connect()
    con.execute(store.SCHEMA)
    con.execute(store.MIGRATIONS)
    return con


def prices(con, ticker, start, closes, dividends=None):
    rows = []
    for i, close in enumerate(closes):
        d = (pd.Timestamp(start) + pd.Timedelta(days=i)).date()
        rows.append([ticker, d, close, close, close, (dividends or {}).get(i, 0.0), 0.0])
    con.executemany("INSERT INTO prices VALUES (?, ?, ?, ?, ?, ?, ?)", rows)


def company(con, cik, ticker, currency="USD", market="USA", industry=None):
    con.execute("INSERT INTO companies (cik, ticker, name, price_currency, currency, market, industry, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, 'sec')", [cik, ticker, ticker, currency, currency, market, industry])


def test_xirr_of_ten_percent():
    flows = [(date(2024, 1, 1), -100.0), (date(2025, 1, 1), 110.0)]
    assert portfolio.xirr(flows) == pytest.approx(0.0997, abs=1e-3)
    assert portfolio.xirr([(date(2024, 1, 1), -100.0)]) is None


def test_caps_hand_the_overflow_to_the_rest():
    scores = {"A": 10.0, "B": 1.0, "C": 1.0, "D": 1.0, "E": 1.0, "F": 1.0, "G": 1.0, "H": 1.0, "I": 1.0,
              "J": 1.0, "K": 1.0, "L": 1.0}
    w = portfolio._capped(scores, {t: t for t in scores})
    assert w["A"] == pytest.approx(config.POSITION_CAP)
    assert sum(w.values()) == pytest.approx(1.0)
    assert max(w.values()) <= config.POSITION_CAP + 1e-9


def test_a_cluster_is_capped_as_a_whole():
    scores = {t: 1.0 for t in "ABCDEFGHIJKL"}
    cluster = {t: ("X" if t in "ABCD" else t) for t in scores}
    w = portfolio._capped(scores, cluster)
    assert sum(w[t] for t in "ABCD") == pytest.approx(config.CLUSTER_CAP)


def test_same_industry_forms_a_cluster():
    con = db()
    out = portfolio.clusters(con, ["KO", "PEP", "MSFT"], {"KO": "Beverages", "PEP": "Beverages", "MSFT": "Software"})
    assert out["KO"] == out["PEP"] != out["MSFT"]


def test_positions_in_the_base_currency(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PORTFOLIO_PATH", tmp_path / "p.sqlite")
    con = db()
    company(con, 1, "KO")
    start = date.today() - timedelta(days=9)
    prices(con, "KO", start, [50, 50, 50, 50, 50, 55, 55, 55, 55, 60], dividends={6: 1.0})
    prices(con, "USDPLN=X", start, [4.0] * 9 + [4.4])
    portfolio.add("KO", start.isoformat(), "buy", 10, 50, fees=0)
    out = portfolio.positions(con, base="PLN")
    [r] = out["rows"]
    assert r["value"] == 600 and r["dividends"] == 10
    assert r["return_local"] == pytest.approx((600 + 10 - 500) / 500)
    assert r["value_base"] == pytest.approx(600 * 4.4)
    assert r["return_base"] == pytest.approx((600 * 4.4 + 10 * 4.0 - 500 * 4.0) / (500 * 4.0))
    assert out["totals"]["xirr"] is None      # nine days is too short to annualise


def test_xirr_over_a_year(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PORTFOLIO_PATH", tmp_path / "p.sqlite")
    con = db()
    company(con, 1, "KO")
    start = date.today() - timedelta(days=365)
    prices(con, "KO", start, [50] * 365 + [55])
    portfolio.add("KO", start.isoformat(), "buy", 10, 50)
    assert portfolio.positions(con, base="USD")["totals"]["xirr"] == pytest.approx(0.10, abs=0.002)


def test_selling_closes_the_position(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PORTFOLIO_PATH", tmp_path / "p.sqlite")
    con = db()
    company(con, 1, "KO")
    start = date.today() - timedelta(days=4)
    prices(con, "KO", start, [50, 50, 60, 60, 60])
    portfolio.add("KO", start.isoformat(), "buy", 10, 50)
    portfolio.add("KO", (start + timedelta(days=2)).isoformat(), "sell", 10, 60)
    out = portfolio.positions(con, base="USD")
    assert out["totals"]["positions"] == 0 and out["totals"]["closed"] == 1
    assert out["rows"][0]["gain_base"] == pytest.approx(100)


def test_track_record_against_the_world_index():
    con = db()
    start = date.today() - timedelta(days=10)
    prices(con, "KO", start, [100] + [110] * 10)
    prices(con, "MSFT", start, [100] + [90] * 10)
    prices(con, config.BENCHMARK, start, [100] + [102] * 10)
    prices(con, "USDPLN=X", start, [4.0] * 11)
    prices(con, "^GSPC", start, [100] + [101] * 10)
    ranked = pd.DataFrame([
        {"cik": 1, "ticker": "KO", "name": "KO", "market": "USA", "currency": "USD", "price": 100.0,
         "buy_price": 120.0, "expected_return": 0.15, "expected_return_base": 0.16, "quality": 90.0},
        {"cik": 2, "ticker": "MSFT", "name": "MSFT", "market": "USA", "currency": "USD", "price": 100.0,
         "buy_price": 90.0, "expected_return": 0.12, "expected_return_base": 0.13, "quality": 95.0},
    ])
    assert track.take(con, ranked, taken_on=start) == 2
    out = track.record(con)
    snap = out["snapshots"][0]
    assert snap["portfolio"] == pytest.approx(0.0)       # +10% and -10%
    assert snap["benchmark"] == pytest.approx(0.02)
    assert snap["excess"] == pytest.approx(-0.02)
    assert snap["hit_rate"] == pytest.approx(0.5)
    assert out["summary"]["scored"] == 1
