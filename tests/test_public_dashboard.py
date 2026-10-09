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
