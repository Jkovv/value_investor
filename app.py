"""app.py: the dashboard.

  uvicorn app:app --port 8001        then open http://127.0.0.1:8001

duckdb is opened read-only, so the dashboard can stay up while you browse;
while ingest.py or main.py screen writes, pages say "busy" until it's done.
research and questions run in background threads and write files.
"""

import json
import re
import time
from pathlib import Path

import duckdb
import markdown
import pandas as pd
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import Undefined
from markupsafe import Markup

from value_investor import config, llm, macro, markets, peers, research, screener, store
from value_investor.research_tools import RESEARCH_DIR

ROOT = Path(__file__).parent
app = FastAPI(title="Value Investor")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")



class _AssetVersion:
    """appended to static urls so a browser never runs yesterday's css or js.
    read on every render, so editing a static file needs no restart."""

    def __str__(self) -> str:
        return str(int(max(p.stat().st_mtime for p in (ROOT / "static").iterdir())))


ASSET_VERSION = _AssetVersion()


def _missing(v) -> bool:
    if v is None or isinstance(v, (Undefined, str)):
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def pct(v, digits=1, signed=False):
    if _missing(v):
        return "-"
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
    """cents only where they matter: 1,250,000 won needs no decimals."""
    if _missing(v):
        return "-"
    return f"{v:,.{0 if abs(v) >= 10_000 else digits}f}"


def compact(v):
    if _missing(v):
        return "-"
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= size:
            return f"{v / size:.1f}{suffix}"
    return f"{v:,.0f}"


def times(v):
    return "-" if _missing(v) else f"{v:.1f}×"


def whole(v, fallback="-"):
    return fallback if _missing(v) else f"{int(v)}"


def text_or(v, fallback=""):
    return v if isinstance(v, str) and v else fallback


templates.env.filters.update(pct=pct, money=money, compact=compact, times=times, nice_name=nice_name,
                             text_or=text_or, whole=whole)
templates.env.globals.update(config=config, asset_version=ASSET_VERSION)

TONE = {"cheap": "pass", "fair": "pass", "expensive": "warn", "very expensive": "fail"}
templates.env.globals.update(regime_tone=TONE)


def _busy(request: Request, page: str):
    return templates.TemplateResponse(request, "busy.html", {"page": page}, status_code=503)


def _series(points) -> str:
    return json.dumps([[str(k), None if _missing(v) else float(v)] for k, v in points])


_readings_cache: dict = {}


def _market_readings(con) -> dict:
    """all market readings, recomputed at most every ten minutes."""
    now = time.time()
    if _readings_cache.get("at", 0) > now - 600:
        return _readings_cache["data"]
    data = {r["iso3"]: r for r in markets.all_readings(con)}
    _readings_cache.update(at=now, data=data)
    return data


def render_report(text: str) -> Markup:
    """markdown from the agent, with any raw HTML neutralised and only web links kept."""
    safe = text.replace("&", "&amp;").replace("<", "&lt;")
    html = markdown.markdown(safe, extensions=["tables", "sane_lists"])
    html = re.sub(r'href="(?!https?://)[^"]*"', 'href="#"', html)
    html = html.replace("<a href=", '<a target="_blank" rel="noopener noreferrer" href=')
    return Markup(html)


@app.get("/", response_class=HTMLResponse)
def ranking(request: Request, q: str = "", all: bool = False, profile: str = "", market: str = ""):
    try:
        with store.connect(read_only=True) as con:
            df = screener.ranking(con, only_gate=not all)
            readings = _market_readings(con)
    except duckdb.IOException:
        return _busy(request, "ranking")

    present = sorted({m for m in df["market"].dropna()}) if not df.empty else []
    if q:
        needle = q.strip().lower()
        df = df[df["ticker"].fillna("").str.lower().str.contains(needle)
                | df["name"].fillna("").str.lower().str.contains(needle)]
    if profile:
        df = df[df["profile"] == profile]
    if market:
        df = df[df["market"] == market]
    rows = df.to_dict(orient="records")
    top = df["expected_return"].max(skipna=True) if not df.empty else None
    return templates.TemplateResponse(request, "ranking.html", {
        "rows": rows, "q": q, "all": all, "profile": profile, "market": market, "count": len(rows),
        "markets_present": [(iso, markets.BY_ISO[iso].name) for iso in present if iso in markets.BY_ISO],
        "readings": readings, "top_return": None if _missing(top) else float(top),
        "n_markets": len(present), "briefs": {path.stem.upper() for path in RESEARCH_DIR.glob("*.md")},
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
            reading, peer = None, {"rows": []}
            if payload:
                reading = _market_readings(con).get(payload["company"].get("market"))
                peer = peers.find(con, cik)
    except duckdb.IOException:
        return _busy(request, "company")
    if payload is None:
        return templates.TemplateResponse(request, "missing.html", {"ticker": ticker.upper()}, status_code=404)

    yearly = pd.DataFrame(payload["yearly"]).tail(config.HISTORY_YEARS + 1)
    quarters = payload.get("quarters") or {}
    q_rows = quarters.get("rows") or []
    q_chart = None
    if len(q_rows) >= 3:
        labels = [f"{r['end'][:4]} Q{(int(r['end'][5:7]) - 1) // 3 + 1}" for r in q_rows]
        q_chart = json.dumps([
            {"name": "Revenue", "points": json.loads(_series(zip(labels, [r["revenue"] for r in q_rows])))},
            {"name": "Net income", "points": json.loads(_series(zip(labels, [r["net_income"] for r in q_rows]))),
             "muted": True},
        ])
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
    text = research.report(ticker)
    return templates.TemplateResponse(request, "company.html", {
        "p": payload, "row": row, "v": payload["valuation"], "s": payload["summary"],
        "c": payload["company"], "checks": checks, "groups": groups, "charts": charts,
        "yearly": payload["yearly"][-12:], "reading": reading,
        "report": render_report(text) if text else None,
        "research_status": research.status(ticker), "research_busy": research.busy(),
        "backends": llm.backends(), "quarters": quarters, "q_chart": q_chart, "peers": peer,
        "peer_metrics": peers.METRICS, "insiders": payload.get("insiders"),
        "questions": [dict(q, html=render_report(q["answer"]) if q.get("answer") else None)
                      for q in research.questions(ticker)],
    })


def _name(ticker: str) -> "str | None":
    try:
        with store.connect(read_only=True) as con:
            cik = store.find_cik(con, ticker)
            return (store.company(con, cik) or {}).get("name") if cik else None
    except duckdb.IOException:
        return None


def _owner_only() -> None:
    if config.PUBLIC_DASHBOARD:
        raise HTTPException(status_code=403, detail="not on a public dashboard")


@app.post("/company/{ticker}/research")
def start_research(ticker: str, mode: str = Form("resume")):
    _owner_only()
    research.start_in_background(ticker, _name(ticker), resume=mode == "resume")
    return RedirectResponse(f"/company/{ticker}#research", status_code=303)


@app.post("/company/{ticker}/ask")
def ask(ticker: str, question: str = Form("")):
    _owner_only()
    research.start_question(ticker, question, _name(ticker))
    return RedirectResponse(f"/company/{ticker}#research", status_code=303)


@app.get("/company/{ticker}/ask/status")
def ask_status(ticker: str):
    items = research.questions(ticker)
    current = items[0] if items else {}
    return JSONResponse({"state": current.get("state", "none"), "last_step": current.get("last_step", "")},
                        headers={"Cache-Control": "no-store"})


@app.get("/company/{ticker}/research/status")
def research_status(ticker: str):
    return JSONResponse(json.loads(json.dumps(research.status(ticker) or {"state": "none"}, default=str)),
                        headers={"Cache-Control": "no-store"})


@app.get("/market", response_class=HTMLResponse)
def market(request: Request, m: str = ""):
    try:
        with store.connect(read_only=True) as con:
            readings = _market_readings(con)
            snap = macro.snapshot(con)
            bonds = {iso: markets.bond_yield(con, iso) for iso in readings}
    except duckdb.IOException:
        return _busy(request, "market")
    chosen = (m or "USA").upper()
    reading = readings.get(chosen)
    chart, table = None, []
    if reading and reading.get("value") is not None:
        hist = reading["history"]
        hist = hist[hist.index >= "1990-01-01"]
        labels = [d.strftime("%Y-%m") if chosen == "USA" else d.strftime("%Y") for d in hist.index]
        chart = json.dumps([
            {"name": "Market Cap / GDP", "points": json.loads(_series(zip(labels, hist["ratio"])))},
            {"name": "Long-run trend", "points": json.loads(_series(zip(labels, hist["trend"]))), "muted": True},
        ])
        table = [{"date": lab, "ratio": r, "trend": t}
                 for lab, r, t in list(zip(labels, hist["ratio"], hist["trend"]))[::-1]]
    rows = sorted(readings.values(), key=lambda r: (r.get("z") is None, -(r.get("z") or 0)))
    return templates.TemplateResponse(request, "market.html", {
        "snap": snap, "readings": rows, "chosen": chosen, "reading": reading, "chart": chart,
        "table": table, "bonds": bonds,
    })
