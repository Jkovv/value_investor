"""20 · research_tools: what the research agents are allowed to do. all read-only.

    company_numbers        our own analysis (the agents never compute numbers)
    quarterly_results      the last quarters against a year earlier
    peer_table             the same numbers for the closest companies in the industry
    insider_trades         open-market form 4 buys and sells (us only)
    annual_report_section  the latest 10-K / 20-F, by section, a page at a time
    attention_trend        wikipedia pageviews, a free stand-in for brand interest
    news_trend             gdelt news volume and tone over the last year
    web_search             tavily while the free credits last, then duckduckgo
    read_web_page          one page of readable text from a url

long text comes in 5,000-character pages so a 16k-context local model can read it.
"""

import ipaddress
import json
import logging
import socket
import threading
import time
from datetime import date, timedelta
from urllib.parse import quote, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

from value_investor import config, peers, store

logger = logging.getLogger(__name__)

PAGE_CHARS = 5000
RESEARCH_DIR = config.DATA_DIR / "research"
CACHE_DIR = RESEARCH_DIR / "cache"
USAGE_FILE = RESEARCH_DIR / "tavily_usage.json"
_usage_lock = threading.Lock()

SECTIONS = {"business": "Item 1", "risk_factors": "Item 1A", "mda": "Item 7"}
SECTIONS_20F = {"business": "Item 4", "risk_factors": "Item 3", "mda": "Item 5"}


def _page(text: str, page: int, label: str) -> str:
    pages = max(1, -(-len(text) // PAGE_CHARS))
    page = min(max(page, 1), pages)
    chunk = text[(page - 1) * PAGE_CHARS: page * PAGE_CHARS]
    return f"[{label}, page {page} of {pages}]\n{chunk}"


def _company(ticker: str) -> "dict | None":
    with store.connect(read_only=True) as con:
        cik = store.find_cik(con, ticker)
        if cik is None:
            return None
        comp = store.company(con, cik) or {}
        comp["payload"] = store.analysis_payload(con, cik)
        return comp


@tool
def company_numbers(ticker: str) -> str:
    """the computed facts about a company: profile, quality checklist results, valuation and flags.

    use these numbers as given. never recompute or estimate financial figures yourself."""
    comp = _company(ticker)
    if comp is None:
        return f"{ticker} is not in the database."
    p = comp.get("payload") or {}
    v = p.get("valuation") or {}
    lines = [
        f"Company: {comp.get('name')} ({comp.get('ticker')})",
        f"Market: {comp.get('market')}, country: {comp.get('country')}, sector: {comp.get('sector')}, "
        f"industry: {comp.get('industry')}",
        f"Reports in: {p.get('currency')}; source: {comp.get('source')}",
    ]
    if comp.get("summary"):
        lines.append(f"Business description: {comp['summary']}")
    checks = p.get("checks") or []
    if checks:
        lines.append("Quality checklist:")
        lines += [f"  - {c['label']}: {c['shown']} ({c['status']})" for c in checks]
    if v.get("available"):
        er = v.get("expected_return", {})
        lines += [
            f"Price: {v.get('price'):.2f} {v.get('currency')}; buy below: {v.get('buy_price'):.2f}",
            f"P/E: {v.get('pe_now'):.1f}; initial earnings yield: {v.get('initial_return', 0) * 100:.1f}%",
            f"Growth used: {v.get('growth', 0) * 100:.1f}% a year",
            f"Expected yearly return: {er.get('mid', 0) * 100:.1f}% local "
            f"(range {er.get('low', 0) * 100:.1f}% to {er.get('high', 0) * 100:.1f}%)",
        ]
        if p.get("expected_return_base") is not None:
            lines.append(f"Expected yearly return in {p.get('base_currency')}: {p['expected_return_base'] * 100:.1f}%")
    elif v:
        lines.append(f"No valuation: {v.get('reason')}")
    lines += lens_lines(p.get("lenses") or {}, v.get("currency") or p.get("currency"))
    q = (p.get("quarters") or {}).get("summary") or {}
    if q:
        lines.append(_quarter_line(q, p.get("currency")))
    ins = p.get("insiders")
    if ins:
        lines.append(_insider_line(ins))
    for flag in p.get("flags") or []:
        lines.append(f"Flag: {flag}")
    return "\n".join(lines)


def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:+.1f}%"


def _quarter_line(q: dict, currency) -> str:
    out = (f"Latest quarter (ended {q.get('last_end')}): revenue {_pct(q.get('revenue_yoy'))} and net income "
           f"{_pct(q.get('net_income_yoy'))} against a year earlier; trend over two quarters: {q.get('trend')}")
    if q.get("ttm_net_income") is not None:
        out += f"; trailing twelve months net income {q['ttm_net_income'] / 1e6:,.0f}M {currency}"
    if q.get("pe_ttm"):
        out += f"; P/E on trailing earnings {q['pe_ttm']:.1f}"
    return out


def _insider_line(ins: dict) -> str:
    return (f"Insiders, last {ins['days']} days (form 4): {ins['buyers']} bought "
            f"(${ins['buy_value'] / 1e6:,.1f}M), {ins['sellers']} sold (${ins['sell_value'] / 1e6:,.1f}M, of which "
            f"${ins['unplanned_sell_value'] / 1e6:,.1f}M outside 10b5-1 plans); reading: {ins.get('signal')}")


@tool
def quarterly_results(ticker: str) -> str:
    """the company's last quarters: revenue, margins, net income and free cash flow, each against
    the same quarter a year earlier. use it to see whether the business is still on track."""
    comp = _company(ticker)
    if comp is None:
        return f"{ticker} is not in the database."
    q = (comp.get("payload") or {}).get("quarters") or {}
    rows = q.get("rows") or []
    if not rows:
        return f"No quarterly figures stored for {ticker}."
    ccy = (comp.get("payload") or {}).get("currency")
    lines = [_quarter_line(q.get("summary") or {}, ccy), f"Quarter end | revenue ({ccy} M) | gross margin | "
             "operating margin | net income (M) | revenue vs year ago | net income vs year ago"]
    for r in rows[-8:]:
        lines.append(" | ".join([
            r["end"], _m(r.get("revenue")), _p(r.get("gross_margin")), _p(r.get("operating_margin")),
            _m(r.get("net_income")), _pct(r.get("revenue_yoy")), _pct(r.get("net_income_yoy"))]))
    return "\n".join(lines)


def _m(v) -> str:
    return "n/a" if v is None else f"{v / 1e6:,.0f}"


def _p(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f}%"


@tool
def peer_table(ticker: str) -> str:
    """the closest companies in the same industry, from any market, with the same computed numbers:
    margins, ROE, growth, debt, P/E, quality score and expected return. the first row is the company itself."""
    with store.connect(read_only=True) as con:
        cik = store.find_cik(con, ticker)
        if cik is None:
            return f"{ticker} is not in the database."
        found = peers.find(con, cik)
    if not found["rows"]:
        return f"No peers stored for {ticker}."
    head = "ticker | name | market | quality | " + " | ".join(label for _, label, _ in peers.METRICS)
    lines = [f"Peers by {found['basis']} ({found.get('industry') or 'SIC code'}):", head]
    for r in found["rows"]:
        cells = [r["ticker"], (r["name"] or "")[:28], r["market"] or "", f"{r['quality'] or 0:.0f}"]
        for key, _, kind in peers.METRICS:
            v = r.get(key)
            cells.append("n/a" if v is None else (f"{v:.1f}" if kind in ("num", "times") else f"{v * 100:.1f}%"))
        lines.append(" | ".join(cells))
    return "\n".join(lines)


@tool
def insider_trades(ticker: str) -> str:
    """open-market purchases and sales by the company's officers and directors over the last year,
    from SEC form 4 filings (US companies only). planned sales under 10b5-1 plans are marked."""
    comp = _company(ticker)
    if comp is None:
        return f"{ticker} is not in the database."
    ins = (comp.get("payload") or {}).get("insiders")
    if not ins:
        return "No form 4 data: only US companies are covered, and only those in the ranking or held."
    lines = [_insider_line(ins)]
    for t in ins.get("recent", []):
        kind = "bought" if t["code"] == "P" else "sold"
        plan = " (10b5-1 plan)" if t.get("planned") else ""
        lines.append(f"{t['date']}: {t['owner']} ({t['role']}) {kind} {t['shares'] or 0:,.0f} shares "
                     f"at {t['price'] or 0:,.2f}, ${t['value'] / 1e6:,.2f}M{plan}")
    return "\n".join(lines)


WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"
WIKI_VIEWS = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
              "{title}/monthly/{start}/{end}")
HEADERS = {"User-Agent": "value-investor/1.0 (personal research tool)"}


def pageviews_link(title: str) -> str:
    return f"https://pageviews.wmcloud.org/?project=en.wikipedia.org&range=last-year&pages={quote(title)}"


@tool
def attention_trend(topic: str) -> str:
    """monthly English Wikipedia pageviews for a company, brand or product over the last two years.
    a free proxy for public interest: compare the last 12 months with the 12 before, and the
    company with its competitors or its main brands."""
    try:
        found = requests.get(WIKI_SEARCH, timeout=20, headers=HEADERS, params={
            "action": "query", "list": "search", "srsearch": topic, "srlimit": 1, "format": "json"}).json()
        hits = found.get("query", {}).get("search", [])
        if not hits:
            return f"No Wikipedia article found for {topic!r}."
        title = hits[0]["title"]
        end = date.today().replace(day=1) - timedelta(days=1)
        start = (end - timedelta(days=760)).replace(day=1)
        url = WIKI_VIEWS.format(title=quote(title.replace(" ", "_"), safe=""), start=start.strftime("%Y%m%d"),
                                end=end.strftime("%Y%m%d"))
        items = requests.get(url, timeout=20, headers=HEADERS).json().get("items", [])
    except Exception as exc:
        return f"Could not read Wikipedia pageviews: {exc}"
    if len(items) < 6:
        return f"Too little pageview history for {title!r}."
    views = [(i["timestamp"][:6], int(i["views"])) for i in items]
    last, before = sum(v for _, v in views[-12:]), sum(v for _, v in views[-24:-12])
    change = f"{(last / before - 1) * 100:+.0f}%" if before else "n/a"
    months = ", ".join(f"{m[:4]}-{m[4:]}: {v:,}" for m, v in views[-12:])
    return (f"[Wikipedia pageviews: {title}]\nLast 12 months {last:,} views, {change} on the 12 before.\n"
            f"By month: {months}\nSource: {pageviews_link(title)}")


GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"


def gdelt_link(query: str) -> str:
    return f"{GDELT}?query={quote(query)}&mode=timelinevolraw&timespan=12m&format=html"


GDELT_GAP = 6.0     # they ask for one request every five seconds
_gdelt_lock = threading.Lock()
_gdelt_last = [0.0]


def _gdelt(query: str, mode: str) -> pd.DataFrame:
    for attempt in range(3):
        with _gdelt_lock:
            wait = _gdelt_last[0] + GDELT_GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            resp = requests.get(GDELT, timeout=30, headers=HEADERS,
                                params={"query": query, "mode": mode, "timespan": "12m", "format": "json"})
            _gdelt_last[0] = time.monotonic()
        if resp.status_code != 429:
            break
        time.sleep(GDELT_GAP * (attempt + 2))
    resp.raise_for_status()
    data = resp.json().get("timeline", [{}])[0].get("data", [])
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"].str[:8])
    return df.set_index("date")


@tool
def news_trend(query: str) -> str:
    """how much the world's news wrote about something over the last 12 months, and in what tone
    (GDELT, free). put company or brand names in double quotes, e.g. '"Coca-Cola"'. a rising count
    with a falling tone is worth a closer look."""
    try:
        volume = _gdelt(query, "timelinevolraw")
    except Exception as exc:
        return f"Could not read GDELT: {exc}"
    try:
        tone = _gdelt(query, "timelinetone")
    except Exception:
        tone = pd.DataFrame()
    if volume.empty:
        return f"No news found for {query}."
    # the 12-month window starts and ends mid-month; partial months would skew the averages
    this_month = pd.Timestamp.today().normalize().replace(day=1)
    monthly = volume["value"].resample("MS").sum().iloc[1:]
    monthly = monthly[monthly.index < this_month]
    tone_m = tone["value"].resample("MS").mean() if not tone.empty else pd.Series(dtype=float)
    tone_m = tone_m[(tone_m.index < this_month) & (tone_m.index >= monthly.index.min())] if not monthly.empty else tone_m
    if len(monthly) < 4:
        return f"Too little news history for {query}."
    recent, earlier = monthly.tail(3).mean(), monthly.iloc[:-3].mean() if len(monthly) > 3 else None
    lines = [f"[GDELT news: {query}]"]
    if earlier:
        lines.append(f"Articles a month, last 3 months: {recent:,.0f}; the {len(monthly) - 3} before: {earlier:,.0f} "
                     f"({(recent / earlier - 1) * 100:+.0f}%).")
    if not tone_m.empty:
        lines.append(f"Average tone (below 0 is negative), last 3 months {tone_m.tail(3).mean():+.2f}, "
                     f"before {tone_m.iloc[:-3].mean():+.2f}.")
    lines.append("By month: " + ", ".join(f"{d:%Y-%m}: {v:,.0f}" for d, v in monthly.items()))
    lines.append(f"Source: {gdelt_link(query)}")
    return "\n".join(lines)


def lens_lines(lenses: dict, currency: "str | None") -> list:
    """the other valuation lenses, one line each, for the writer to weigh against the checklist."""
    out = []
    if f := lenses.get("piotroski"):
        out.append(f"Piotroski F-score: {f['scaled']} of 9 ({f['verdict']})")
    if a := lenses.get("altman"):
        out.append(f"Altman Z-score: {a['z']:.1f} ({a['zone']} zone)")
    if (g := lenses.get("graham")) and g.get("number"):
        out.append(f"Graham number: {g['number']:.2f} {currency}; {g['passed']} of {g['of']} defensive tests pass")
    if d := lenses.get("dcf"):
        out.append(f"Owner-earnings DCF value: {d['value']:.2f} {currency} a share")
    if ly := lenses.get("lynch"):
        peg = f", PEG {ly['peg']:.2f}" if ly.get("peg") is not None else ""
        out.append(f"Lynch category: {ly['category']}{peg}")
    if (m := lenses.get("magic")) and m.get("earnings_yield") is not None and m.get("return_on_capital") is not None:
        out.append(f"Magic Formula: earnings yield {m['earnings_yield'] * 100:.1f}%, "
                   f"return on capital {m['return_on_capital'] * 100:.0f}%")
    return out


def _report_text(comp: dict, section: str) -> "str | None":
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{comp['ticker']}_{section}.txt"
    if cache.exists():
        return cache.read_text(encoding="utf-8")
    from edgar import Company, set_identity

    set_identity(config.SEC_USER_AGENT)
    filings = Company(int(comp["cik"])).get_filings(form=["10-K", "20-F"])
    filing = filings.latest() if filings else None
    if filing is None:
        return None
    doc = filing.obj()
    key = (SECTIONS_20F if filing.form.startswith("20-F") else SECTIONS)[section]
    try:
        text = doc[key]
    except Exception:
        text = None
    if not text:
        return None
    text = f"{filing.form} filed {filing.filing_date}\n\n{text}"
    cache.write_text(text, encoding="utf-8")
    return text


@tool
def annual_report_section(ticker: str, section: str = "business", page: int = 1) -> str:
    """read the company's latest annual report, one page at a time.

    section: "business" (what it does, products, customers, competition),
    "risk_factors" (the risks management lists) or "mda" (management's discussion of results).
    start at page 1; the header tells you how many pages there are."""
    if section not in SECTIONS:
        return f"Unknown section {section!r}. Use one of: {', '.join(SECTIONS)}."
    comp = _company(ticker)
    if comp is None:
        return f"{ticker} is not in the database."
    if comp.get("source") != "sec" or int(comp["cik"]) < 0:
        summary = comp.get("summary") or "No description stored."
        return ("This company does not file with the SEC, so its annual report is not stored here. "
                "Use web_search to find its latest annual report or investor relations page, then "
                f"read_web_page.\n\nShort description from Yahoo Finance:\n{summary}")
    try:
        text = _report_text(comp, section)
    except Exception as exc:
        logger.warning("annual report fetch failed for %s: %s", ticker, exc)
        return f"Could not fetch the annual report: {exc}"
    if not text:
        return f"The latest annual report has no readable {section} section."
    return _page(text, page, f"{comp['ticker']} {section}")


def _tavily_budget_left() -> bool:
    if not config.TAVILY_API_KEY:
        return False
    month = date.today().strftime("%Y-%m")
    with _usage_lock:
        usage = json.loads(USAGE_FILE.read_text()) if USAGE_FILE.exists() else {}
        return usage.get(month, 0) < config.TAVILY_MONTHLY_CREDITS


def _spend_tavily_credit() -> None:
    month = date.today().strftime("%Y-%m")
    with _usage_lock:
        RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
        usage = json.loads(USAGE_FILE.read_text()) if USAGE_FILE.exists() else {}
        usage[month] = usage.get(month, 0) + 1
        USAGE_FILE.write_text(json.dumps(usage))


def _search(query: str, max_results: int) -> list:
    if _tavily_budget_left():
        try:
            resp = requests.post("https://api.tavily.com/search", timeout=30, json={
                "api_key": config.TAVILY_API_KEY, "query": query, "max_results": max_results,
                "search_depth": "basic",
            })
            resp.raise_for_status()
            _spend_tavily_credit()
            return [(r.get("title"), r.get("url"), r.get("content")) for r in resp.json().get("results", [])]
        except Exception as exc:
            logger.info("Tavily failed (%s), falling back to DuckDuckGo", exc)
    from ddgs import DDGS

    return [(r.get("title"), r.get("href"), r.get("body")) for r in DDGS().text(query, max_results=max_results)]


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """search the web. returns numbered results with title, URL and a snippet.

    keep queries specific, e.g. "Orlen market share Polish fuel retail 2025"."""
    try:
        results = _search(query, min(max(max_results, 1), 8))
    except Exception as exc:
        return f"Search failed: {exc}"
    if not results:
        return "No results."
    return "\n\n".join(f"[{i}] {title}\n{url}\n{(snippet or '')[:400]}"
                       for i, (title, url, snippet) in enumerate(results, start=1))


def _public_host(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    try:
        for info in socket.getaddrinfo(parsed.hostname, None):
            ip = ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return False
    except socket.gaierror:
        return False
    return True


@tool
def read_web_page(url: str, page: int = 1) -> str:
    """read one page of readable text from a web page (HTML only), 5,000 characters at a time."""
    if not _public_host(url):
        return "Only public http(s) pages can be read."
    try:
        resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (research bot)"}, stream=True)
        resp.raise_for_status()
        if "html" not in resp.headers.get("Content-Type", "html"):
            return f"Not an HTML page ({resp.headers.get('Content-Type')})."
        raw = resp.raw.read(2_000_000, decode_content=True)
    except Exception as exc:
        return f"Could not read the page: {exc}"
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "form", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    title = soup.title.string.strip() if soup.title and soup.title.string else url
    return _page(text, page, title)


TOOLS = [company_numbers, quarterly_results, peer_table, insider_trades, annual_report_section,
         attention_trend, news_trend, web_search, read_web_page]
