import pytest

from value_investor import peers


def rows(mine, *others, key="roe"):
    out = [{"ticker": "ME", key: mine}]
    out += [{"ticker": f"P{i}", key: v} for i, v in enumerate(others)]
    return out


def test_rank_median_and_position_when_higher_is_better():
    m = peers.standing(rows(0.30, 0.10, 0.20, 0.40), ("roe", "ROE", "pct", "high", "Profitability"))
    assert m["rank"] == 2 and m["of"] == 4
    assert m["median"] == pytest.approx(0.20)
    assert m["ahead"] and m["best"] == "P2"
    me = next(d for d in m["dots"] if d["me"])
    assert 0 < me["x"] < 1


def test_lower_is_better_flips_the_order_and_the_axis():
    m = peers.standing(rows(5.0, 20.0, 15.0, 30.0, key="pe_now"), ("pe_now", "P/E", "num", "low", "Price"))
    assert m["rank"] == 1 and m["best"] == "ME" and m["ahead"]
    me = next(d for d in m["dots"] if d["me"])
    worst = next(d for d in m["dots"] if d["ticker"] == "P2")
    assert me["x"] > worst["x"]


def test_ties_share_the_better_place_and_missing_values_are_skipped():
    m = peers.standing(rows(0.2, 0.2, None, 0.1), ("roe", "ROE", "pct", "high", "Profitability"))
    assert m["rank"] == 1 and m["of"] == 3


def test_no_rank_without_enough_competitors():
    m = peers.standing(rows(0.2, 0.1), ("roe", "ROE", "pct", "high", "Profitability"))
    assert m["rank"] is None and m["dots"] == []
