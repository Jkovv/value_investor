from value_investor import watchlist


def test_a_star_adds_and_a_second_one_takes_away(monkeypatch, tmp_path):
    monkeypatch.setattr(watchlist, "PATH", tmp_path / "watchlist.json")
    assert watchlist.toggle("dnp.wa") is True and "DNP.WA" in watchlist.load()
    assert watchlist.toggle("DNP.WA") is False and watchlist.load() == {}


def test_a_reading_knows_the_buy_zone():
    r = watchlist.reading({"passes_gate": True, "expected_return": 0.18},
                          {"valuation": {"price": 33.66, "buy_price": 46.64, "currency": "PLN", "sell_signal": False},
                           "insiders": {"buyers": 2, "cluster": False}})
    assert r["in_zone"] and round(r["gap"], 3) == round(33.66 / 46.64 - 1, 3) and r["insider_buyers"] == 2


def snap(price, buy=100.0, sell=False, buyers=0, cluster=False, gate=True):
    return {"price": price, "buy_price": buy, "currency": "USD", "in_zone": price <= buy, "gap": price / buy - 1,
            "sell_signal": sell, "passes_gate": gate, "expected_return": 0.1, "insider_buyers": buyers,
            "cluster": cluster, "as_of": "2026-10-24"}


def test_the_digest_puts_a_new_buy_first():
    before = {"MA": snap(120), "KO": snap(90), "DNP.WA": snap(80)}
    now = {"MA": snap(95), "KO": snap(105, sell=True), "DNP.WA": snap(81, buyers=3, cluster=True)}
    found = [(e["ticker"], e["what"]) for e in watchlist.changes(before, now)]
    assert found == [("MA", "entered the buy zone"), ("KO", "sell signal"),
                     ("DNP.WA", "insiders buying together"), ("KO", "left the buy zone")]
    assert watchlist.changes({}, now) == []


def test_the_digest_is_written_as_a_dated_page(monkeypatch, tmp_path):
    monkeypatch.setattr(watchlist, "DIGESTS", tmp_path)
    path = watchlist.write_digest([{"ticker": "MA", "what": "entered the buy zone", "detail": "95.00 against 100.00"}],
                                  {"MA": snap(95), "KO": snap(130)})
    text = open(path, encoding="utf-8").read()
    assert "**MA**: entered the buy zone" in text and text.index("| MA |") < text.index("| KO |")
