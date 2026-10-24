from fastapi.testclient import TestClient

import app as dashboard
from value_investor import config, research_tools


def test_a_public_dashboard_refuses_anything_that_spends_credits(monkeypatch):
    monkeypatch.setattr(config, "PUBLIC_DASHBOARD", True)
    client = TestClient(dashboard.app)
    assert client.post("/company/KO/research", data={"mode": "fresh"}).status_code == 403
    assert client.post("/company/KO/ask", data={"question": "who competes?"}).status_code == 403


def test_tavily_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "key")
    monkeypatch.setattr(config, "TAVILY_MONTHLY_CREDITS", 0)
    assert not research_tools._tavily_budget_left()


def test_the_markets_page_opens_on_the_market_furthest_below_its_trend():
    readings = {"USA": {"iso3": "USA", "value": 2.6, "z": 1.8, "confidence": "high"},
                "BEL": {"iso3": "BEL", "value": 0.6, "z": -1.9, "confidence": "medium"},
                "EGY": {"iso3": "EGY", "value": 0.1, "z": -3.0, "confidence": "stale"},
                "ISL": {"iso3": "ISL", "value": None, "z": None, "confidence": "stale"}}
    assert dashboard.cheapest(readings) == "BEL"          # egypt's figure is too old to lead with
    assert dashboard.cheapest({"EGY": readings["EGY"]}) == "EGY"
    assert dashboard.cheapest({}) is None
