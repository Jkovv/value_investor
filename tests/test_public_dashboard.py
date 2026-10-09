from fastapi.testclient import TestClient

import app as dashboard
from value_investor import config, research_tools


def test_a_public_dashboard_refuses_anything_that_costs_or_is_private(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "PUBLIC_DASHBOARD", True)
    monkeypatch.setattr(config, "PORTFOLIO_PATH", tmp_path / "p.sqlite")
    client = TestClient(dashboard.app)
    assert client.post("/company/KO/research", data={"mode": "fresh"}).status_code == 403
    assert client.post("/company/KO/ask", data={"question": "who competes?"}).status_code == 403
    trade = {"ticker": "KO", "traded_on": "2026-01-02", "kind": "buy", "shares": 1, "price": 60}
    assert client.post("/portfolio/add", data=trade).status_code == 403
    assert client.post("/portfolio/1/delete").status_code == 403
    assert client.get("/portfolio").status_code == 404
    assert not (tmp_path / "p.sqlite").exists()


def test_tavily_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(config, "TAVILY_API_KEY", "key")
    monkeypatch.setattr(config, "TAVILY_MONTHLY_CREDITS", 0)
    assert not research_tools._tavily_budget_left()
