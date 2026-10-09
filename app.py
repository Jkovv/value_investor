"""app.py — the dashboard.

  uvicorn app:app --reload        then open http://127.0.0.1:8000

Reads the DuckDB file read-only, so it can stay open while you browse.
While ingest.py or `main.py screen` is writing, DuckDB locks the file and
pages show a "busy" notice until the run finishes.
"""

import json
import math
import re
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Undefined

from value_investor import config, macro, screener, store

ROOT = Path(__file__).parent
app = FastAPI(title="Value Investor")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")


def _missing(v) -> bool:
    if v is None or isinstance(v, Undefined) or isinstance(v, str):
        return True
    return isinstance(v, float) and math.isnan(v)


def pct(v, digits=1, signed=False):
    if _missing(v):
        return "–"
    v = round(v * 100, digits) + 0.0
    return f"{v:+.{digits}f}%" if signed and v != 0 else f"{v:.{digits}f}%"


def nice_name(name):
    """SEC names come as 'PROGRESSIVE CORP/OH/'; show 'Progressive Corp'."""
    if not name or not isinstance(name, str):
        return name or ""
    name = re.sub(r"\s*/[A-Z]{2,3}/?$", "", name.strip())
    if name.isupper():
        name = " ".join(w if len(w) <= 3 and w.isalpha() and w not in {"INC", "CO", "THE", "AND"} else w.capitalize()
                        for w in name.split())
    return name


def money(v, digits=2):
    return "–" if _missing(v) else f"{v:,.{digits}f}"


def compact(v):
    if _missing(v):
        return "–"
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= size:
            return f"{v / size:.1f}{suffix}"
    return f"{v:,.0f}"


def times(v):
    return "–" if _missing(v) else f"{v:.1f}×"


templates.env.filters.update(pct=pct, money=money, compact=compact, times=times, nice_name=nice_name)
templates.env.globals.update(config=config)


def _busy(request: Request, page: str):
    return templates.TemplateResponse(request, "busy.html", {"page": page}, status_code=503)


def _series(points) -> str:
    return json.dumps([[str(k), None if _missing(v) else float(v)] for k, v in points])


@app.get("/", response_class=HTMLResponse)
def ranking(request: Request, q: str = "", all: bool = False, profile: str = ""):
    try:
        with store.connect(read_only=True) as con:
            df = screener.ranking(con, only_gate=not all)
            snap = macro.snapshot(con)
    except duckdb.IOException:
        return _busy(request, "ranking")

    if q:
        needle = q.strip().lower()
        df = df[df["ticker"].fillna("").str.lower().str.contains(needle)
                | df["name"].fillna("").str.lower().str.contains(needle)]
    if profile:
        df = df[df["profile"] == profile]
    rows = df.to_dict(orient="records")
    return templates.TemplateResponse(request, "ranking.html", {
        "rows": rows, "q": q, "all": all, "profile": profile, "snap": snap, "count": len(rows),
    })


@app.get("/company/{ticker}", response_class=HTMLResponse)
def company(request: Request, ticker: str):
    try:
        with store.connect(read_only=True) as con:
            cik = store.find_cik(con, ticker)
            payload = store.analysis_payload(con, cik) if cik else None
            row = None
            if cik:
                found = store.analyses(con)
                found = found[found["cik"] == cik]
                row = None if found.empty else found.iloc[0].to_dict()
    except duckdb.IOException:
        return _busy(request, "company")
    if payload is None:
        return templates.TemplateResponse(request, "missing.html", {"ticker": ticker.upper()}, status_code=404)

    yearly = pd.DataFrame(payload["yearly"]).tail(config.HISTORY_YEARS + 1)
    charts = []
    if not yearly.empty:
        years = yearly["fiscal_year"].astype(int)
        for col, title, fmt in [
            ("gross_margin", "Gross margin", "pct"), ("net_margin", "Net margin", "pct"),
            ("roe", "Return on equity", "pct"), ("eps", "Earnings per share", "num"),
            ("capex_to_ni", "Capex / net income", "pct"), ("dps", "Dividend per share", "num"),
        ]:
            values = yearly[col] if col in yearly else pd.Series(dtype=float)
            if values.notna().sum() >= 2:
                charts.append({"title": title, "format": fmt, "series": json.dumps([
                    {"name": title, "points": json.loads(_series(zip(years, values)))}])})

    groups = {"income": "Income statement", "balance": "Balance sheet", "cash": "Cash flow"}
    checks = {key: [c for c in payload["checks"] if c["group"] == key] for key in groups}
    return templates.TemplateResponse(request, "company.html", {
        "p": payload, "row": row, "v": payload["valuation"], "s": payload["summary"],
        "c": payload["company"], "checks": checks, "groups": groups, "charts": charts,
        "yearly": payload["yearly"][-12:],
    })


@app.get("/market", response_class=HTMLResponse)
def market(request: Request):
    try:
        with store.connect(read_only=True) as con:
            snap = macro.snapshot(con)
            mc = macro.market_cap_to_gdp(con)
    except duckdb.IOException:
        return _busy(request, "market")
    chart, table = None, []
    if mc:
        hist = mc["history"][mc["history"].index >= "1990-01-01"]
        labels = [d.strftime("%Y-%m") for d in hist.index]
        chart = json.dumps([
            {"name": "Market Cap / GDP", "points": json.loads(_series(zip(labels, hist["ratio"])))},
            {"name": "Long-run trend", "points": json.loads(_series(zip(labels, hist["trend"]))), "muted": True},
        ])
        table = [{"date": d.strftime("%Y-%m"), "ratio": r, "trend": t}
                 for d, r, t in zip(hist.index[::-4], hist["ratio"][::-4], hist["trend"][::-4])]
    return templates.TemplateResponse(request, "market.html", {"snap": snap, "chart": chart, "table": table})
