"""20 · research_tools: what the research agents are allowed to do.

Four tools, all read-only:

    company_numbers        our own computed analysis (the agents never compute numbers)
    annual_report_section  the latest 10-K / 20-F, by section, a page at a time
    web_search             Tavily while the monthly free credits last, then DuckDuckGo
    read_web_page          one page of readable text from a URL

Text is handed out in pages so a small local model with a 16k context can
still read a 100,000-character risk-factor section.
"""

import ipaddress
import json
import logging
import socket
import threading
from datetime import date
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from langchain_core.tools import tool

from value_investor import config, store

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
    """The computed facts about a company: profile, quality checklist results, valuation and flags.

    Use these numbers as given. Never recompute or estimate financial figures yourself."""
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
    for flag in p.get("flags") or []:
        lines.append(f"Flag: {flag}")
    return "\n".join(lines)


def lens_lines(lenses: dict, currency: "str | None") -> list:
    """The other valuation lenses, one line each, for the writer to weigh against the checklist."""
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
    """Read the company's latest annual report, one page at a time.

    section: "business" (what it does, products, customers, competition),
    "risk_factors" (the risks management lists) or "mda" (management's discussion of results).
    Start at page 1; the header tells you how many pages there are."""
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
    """Search the web. Returns numbered results with title, URL and a snippet.

    Keep queries specific, e.g. "Orlen market share Polish fuel retail 2025"."""
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
    """Read one page of readable text from a web page (HTML only), 5,000 characters at a time."""
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


TOOLS = [company_numbers, annual_report_section, web_search, read_web_page]
