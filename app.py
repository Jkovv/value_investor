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

from value_investor import (audit, config, llm, macro, markets, moat, peers, research, screener, store, valuation,
                            watchlist)
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


def ordinal(n) -> str:
    if _missing(n):
        return "-"
    n = int(n)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def measure(v, kind: str = "num"):
    """a value in the format its metric uses."""
    if _missing(v):
        return "-"
    return {"pct": pct(v), "int": whole(v), "times": times(v)}.get(kind, f"{v:.1f}")


def text_or(v, fallback=""):
    return v if isinstance(v, str) and v else fallback


templates.env.filters.update(pct=pct, money=money, compact=compact, times=times, nice_name=nice_name,
                             text_or=text_or, whole=whole, ordinal=ordinal, measure=measure)
templates.env.globals.update(config=config, asset_version=ASSET_VERSION)

TONE = {"cheap": "pass", "fair": "pass", "expensive": "warn", "very expensive": "fail"}
VERDICT_TONE = {"Strong candidate": "pass", "Worth watching": "warn", "Pass": "na"}
templates.env.globals.update(regime_tone=TONE, verdict_tone=VERDICT_TONE)


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


_moat_cache: dict = {}


def _moat_kinds(con) -> dict:
    """cik -> moat kind for every company that passes the gate, worked out again only after a screen."""
    stamp = con.execute("SELECT max(analysed_at), count(*) FROM analyses").fetchone()
    if _moat_cache.get("stamp") != stamp:
        rows = con.execute("SELECT a.cik, json_extract(a.payload, '$.summary'), a.profile, c.industry "
                           "FROM analyses a JOIN companies c USING (cik) WHERE a.passes_gate").fetchall()
        _moat_cache.update(stamp=stamp, kinds={cik: moat.classify(json.loads(s) if s else {}, prof, ind)["short"]
                                               for cik, s, prof, ind in rows})
    return _moat_cache["kinds"]


@app.get("/", response_class=HTMLResponse)
def ranking(request: Request, q: str = "", profile: str = "", market: str = "", full: bool = True):
    try:
        with store.connect(read_only=True) as con:
            df = screener.ranking(con)
            readings = _market_readings(con)
            kinds = _moat_kinds(con)
    except duckdb.IOException:
        return _busy(request, "ranking")
    if not df.empty:
        df = df.assign(moat=df["cik"].map(kinds).fillna("-"))

    present = sorted({m for m in df["market"].dropna()}) if not df.empty else []
    if q:
        needle = q.strip().lower()
        df = df[df["ticker"].fillna("").str.lower().str.contains(needle)
                | df["name"].fillna("").str.lower().str.contains(needle)]
    if profile:
        df = df[df["profile"] == profile]
    if market:
        df = df[df["market"] == market]
    if full:
        df = df[df["history_years"] >= config.HISTORY_YEARS]
    rows = df.to_dict(orient="records")
    top = df["expected_return"].max(skipna=True) if not df.empty else None
    return templates.TemplateResponse(request, "ranking.html", {
        "rows": rows, "q": q, "full": full, "profile": profile, "market": market, "count": len(rows),
        "markets_present": [(iso, markets.BY_ISO[iso].name) for iso in present if iso in markets.BY_ISO],
        "readings": readings, "top_return": None if _missing(top) else float(top),
        "n_markets": int(df["market"].nunique()) if not df.empty else 0, "briefs": {path.stem.upper() for path in RESEARCH_DIR.glob("*.md")},
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

    advantage = moat.classify(payload["summary"], (row or {}).get("profile") or "general",
                              payload["company"].get("industry"))
    v = payload["valuation"]
    if v.get("available") and "implied_growth" not in v:
        v["implied_growth"] = valuation.implied_growth(v["initial_return"], v["pe"]["mid"], v["payout"])
    groups = {"income": "Income statement", "balance": "Balance sheet", "cash": "Cash flow"}
    checks = {key: [c for c in payload["checks"] if c["group"] == key] for key in groups}
    text = research.report(ticker)
    return templates.TemplateResponse(request, "company.html", {
        "p": payload, "row": row, "v": payload["valuation"], "s": payload["summary"],
        "c": payload["company"], "checks": checks, "groups": groups, "charts": charts,
        "yearly": payload["yearly"][-12:], "reading": reading,
        "report": render_report(text) if text else None,
        "research_status": research.status(ticker), "research_busy": research.busy(),
        "brief_verdict": research.verdict(text), "moat": advantage, "watched": ticker.upper() in watchlist.load(),
        "backends": llm.backends(), "quarters": quarters, "q_chart": q_chart, "peers": peer,
        "insiders": payload.get("insiders"),
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


def _grades() -> dict:
    """how each brief did when its sentences were checked against its sources, if they were."""
    path = config.DATA_DIR / "evals" / "results.json"
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("by_brief", {})
    except (OSError, ValueError):
        return {}


@app.post("/watch/{ticker}")
def watch(request: Request, ticker: str):
    _owner_only()
    watchlist.toggle(ticker)
    back = request.headers.get("referer") or f"/company/{ticker}"
    return RedirectResponse(back if back.startswith(str(request.base_url)) else f"/company/{ticker}", status_code=303)


@app.get("/watchlist", response_class=HTMLResponse)
def watch_page(request: Request):
    items = watchlist.load()
    try:
        with store.connect(read_only=True) as con:
            now = watchlist.snapshot(con, items)
            names = dict(con.execute("SELECT ticker, name FROM companies").fetchall())
            ciks = dict(con.execute("SELECT ticker, cik FROM companies").fetchall())
            kinds = _moat_kinds(con)
    except duckdb.IOException:
        return _busy(request, "watchlist")
    state = watchlist.last_state()
    rows = []
    for ticker, added in items.items():
        r = now.get(ticker, {})
        rows.append({"ticker": ticker, "name": names.get(ticker), "added": added.get("added"), **r,
                     "moat": kinds.get(ciks.get(ticker), "-"), "verdict": research.verdict(research.report(ticker))})
    rows.sort(key=lambda r: r.get("gap") if r.get("gap") is not None else 9)
    return templates.TemplateResponse(request, "watchlist.html", {
        "rows": rows, "since": state.get("at"),
        "events": watchlist.changes(state.get("companies", {}), now) if state else [],
    })


@app.get("/research", response_class=HTMLResponse)
def research_desk(request: Request):
    try:
        with store.connect(read_only=True) as con:
            names = dict(con.execute("SELECT ticker, name FROM companies").fetchall())
            top = screener.ranking(con).head(10)
    except duckdb.IOException:
        return _busy(request, "research")
    current = research.busy()
    briefs = research.library()
    done = {b["ticker"] for b in briefs}
    return templates.TemplateResponse(request, "research.html", {
        "briefs": briefs, "names": names, "grades": _grades(), "current": current,
        "current_status": research.status(current) if current else None, "waiting": research.waiting(),
        "top": [{"ticker": t, "name": n, "ret": r, "done": t in done}
                for t, n, r in zip(top["ticker"], top["name"], top["expected_return"])],
        "backends": llm.backends(),
    })


@app.post("/research")
def queue_research(tickers: str = Form(""), top: int = Form(0)):
    _owner_only()
    wanted = [t for t in re.split(r"[\s,;]+", tickers.upper()) if t]
    names = {}
    try:
        with store.connect(read_only=True) as con:
            if top:
                ranked = screener.ranking(con).head(min(top, 20))
                wanted += ranked["ticker"].tolist()
            names = dict(con.execute("SELECT ticker, name FROM companies").fetchall())
    except duckdb.IOException:
        pass
    research.enqueue([t for t in wanted if t in names], names)
    return RedirectResponse("/research", status_code=303)


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


@app.get("/data", response_class=HTMLResponse)
def data(request: Request):
    names = {**audit.NAMES, "sec": "SEC"}
    return templates.TemplateResponse(request, "data.html", {"audit": audit.load(), "names": names})


def cheapest(readings: dict) -> "str | None":
    """the market furthest below its own trend, among those with a current or recently rolled figure."""
    scored = [r for r in readings.values() if r.get("value") is not None and r.get("z") is not None]
    sound = [r for r in scored if r.get("confidence") in ("high", "medium")] or scored
    return min(sound, key=lambda r: r["z"])["iso3"] if sound else None


@app.get("/market", response_class=HTMLResponse)
def market(request: Request, m: str = ""):
    try:
        with store.connect(read_only=True) as con:
            readings = _market_readings(con)
            snap = macro.snapshot(con)
            bonds = {iso: markets.bond_yield(con, iso) for iso in readings}
    except duckdb.IOException:
        return _busy(request, "market")
    best = cheapest(readings)
    chosen = (m or best or "USA").upper()
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
        "table": table, "bonds": bonds, "best": best, "picked": bool(m),
    })
