"""34 · japan: up to twenty years of headline figures for tse listings, from irbank.

irbank.net puts the yearly results of every company filing with the fsa's edinet
on one public page: sales, operating profit, net income, eps, book value per
share, assets, retained earnings, cash flows, capex, dividends and buybacks, back
to 2008, to the hundred million yen (robots.txt allows it). its debt and sg&a are
left out: checked against yahoo they were off by multiples. there are no current
assets, current liabilities or tax lines either, so those checks run on the years
yahoo fills in.
"""

import calendar
import logging
import re
import threading
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from value_investor.china import in_todays_units, splits_of
from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

URL = "https://irbank.net/{code}/results"
TAXONOMY = "irbank"
GAP = 3.0           # seconds between pages
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_lock = threading.Lock()
_last = [0.0]
UNITS = {"兆": 1e12, "億": 1e8, "万": 1e4}

# our line -> the section headings that carry it, the first one a page has wins
MONEY = {
    "revenue": ("売上高", "売上収益", "営業収益", "収益", "経常収益"),
    "operating_income": ("営業利益",),
    "net_income": ("当期純利益", "利益", "純利益"),
    "total_assets": ("総資産",),
    "equity_incl_nci": ("純資産", "資本合計"),
    "retained_earnings": ("利益剰余金",),
    "operating_cash_flow": ("営業活動によるCF",),
    "capex": ("設備投資額", "設備投資"),
    "cash": ("現金等",),
    "dividends_paid": ("剰余金の配当",),
    "buybacks": ("自社株買い",),
    "eps_diluted": ("EPS",),
    "dps_declared": ("一株配当",),
    "bps": ("BPS",),
}
SHARE_OF_SALES = {"cost_of_revenue": "売上原価率"}
PAYOUT = "配当性向"
POSITIVE = {"capex", "dividends_paid", "buybacks"}
INSTANT = {"total_assets", "equity_incl_nci", "equity", "retained_earnings", "cash", "bps"}


def code_for(symbol: str) -> "str | None":
    code, _, suffix = symbol.upper().partition(".")
    return code if suffix == "T" and code else None


def _get(url: str) -> "str | None":
    for attempt in range(3):
        with _lock:
            wait = _last[0] + GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                resp = requests.get(url, timeout=30, headers={"User-Agent": AGENT})
            except (requests.Timeout, requests.ConnectionError):
                resp = None
            _last[0] = time.monotonic()
        if resp is None or resp.status_code in (403, 429, 503):
            time.sleep(60 * (attempt + 1))
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.content.decode("utf-8", "replace")
    raise TimeoutError(f"irbank kept refusing {url}")


def amount(text: str) -> "float | None":
    """'26兆2892億' -> 2.62892e13, '-2779億8200万', '12.15円', '7.92%'."""
    t = re.sub(r"[,\s円%*]", "", text or "")
    sign = -1.0 if t.startswith("-") else 1.0
    t = t.lstrip("-")
    if not t or re.sub(r"[\d.兆億万]", "", t):
        return None
    parts = re.findall(r"(\d+(?:\.\d+)?)(兆|億|万)?", t)
    return sign * sum(float(n) * UNITS.get(u, 1.0) for n, u in parts) if parts else None


def heading(text: str) -> str:
    """'利益(IFRS)#1#2' -> '利益', '設備投資#6#7*' -> '設備投資'."""
    return re.sub(r"\(IFRS\)|#\d+|\*", "", text).strip()


def sections(html: str) -> dict:
    """{heading: {fiscal year end: value}}, actual years only (no forecasts, no latest quarter)."""
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for div in soup.find_all("div", id=re.compile(r"^c_\d+$")):
        h2, dl = div.find("h2"), div.find("dl", class_="gdl")
        if h2 is None or dl is None:
            continue
        values = {}
        for dt, dd in zip(dl.find_all("dt"), dl.find_all("dd")):
            label = dt.get_text(" ", strip=True)
            m = re.match(r"^(\d{4})/(\d{2})", label)
            if not m or "予" in label or "※" in label:
                continue
            year, month = int(m.group(1)), int(m.group(2))
            span = dd.find("span", class_="text")
            value = amount(span.get_text(strip=True) if span else dd.get_text(strip=True))
            if value is not None:
                values[pd.Timestamp(year, month, calendar.monthrange(year, month)[1]).date()] = value
        out.setdefault(heading(h2.get_text(strip=True)), values)
    return out


def frozen_out(values: dict) -> dict:
    """a balance that stays the same to the hundred million yen three years running is a
    copy, not a figure (toyota's debt on irbank sits at one number from 2019 on)."""
    ends = sorted(values)
    frozen = set()
    for i in range(len(ends) - 2):
        run = ends[i:i + 3]
        if values[run[0]] and values[run[0]] == values[run[1]] == values[run[2]]:
            frozen.update(run)
    return {e: v for e, v in values.items() if e not in frozen}


def statements(symbol: str) -> pd.DataFrame:
    code = code_for(symbol)
    if code is None:
        return pd.DataFrame(columns=COLUMNS)
    html = _get(URL.format(code=code))
    if html is None:
        return pd.DataFrame(columns=COLUMNS)
    return in_todays_units(facts_from(sections(html)), splits_of(symbol))


def facts_from(secs: dict) -> pd.DataFrame:
    """irbank's sections -> facts in our layout, in yen."""
    lines = {}
    for field, headings in MONEY.items():
        found = next((secs[h] for h in headings if secs.get(h)), {})
        lines[field] = frozen_out(found) if field in INSTANT else found
    ends = sorted(set(lines["net_income"]) | set(lines["revenue"]))
    gaps = [(b - a).days for a, b in zip(ends, ends[1:])]
    if gaps and sum(g < 300 for g in gaps) > len(gaps) / 2:
        return pd.DataFrame(columns=COLUMNS)        # reits report every six months
    # a change of year end leaves a short year (jt's nine months to december 2014)
    ends = [e for i, e in enumerate(ends) if i == 0 or (e - ends[i - 1]).days >= 300]
    rows = []
    for end in ends:
        v = {field: values.get(end) for field, values in lines.items()}
        revenue = v["revenue"]
        for field, head in SHARE_OF_SALES.items():
            share = secs.get(head, {}).get(end)
            if revenue and share:
                v[field] = revenue * share / 100
        payout = secs.get(PAYOUT, {}).get(end)
        if v["dividends_paid"] is None and payout and v["net_income"] and v["net_income"] > 0:
            v["dividends_paid"] = v["net_income"] * payout / 100
        for field in POSITIVE:
            if v[field] is not None:
                v[field] = abs(v[field])
        if v["net_income"] and v["eps_diluted"] and v["net_income"] / v["eps_diluted"] > 0:
            v["shares_diluted"] = v["net_income"] / v["eps_diluted"]
        # owners' equity with the unrealised gains that irbank's 株主資本 leaves out
        bps = v.pop("bps")
        if bps and v.get("shares_diluted"):
            v["equity"] = bps * v["shares_diluted"]
        filed = (pd.Timestamp(end) + pd.Timedelta(days=90)).date()
        start = (pd.Timestamp(end) - pd.Timedelta(days=364)).date()
        for field, value in v.items():
            if value is None:
                continue
            unit = ("JPY/shares" if field in ("eps_diluted", "dps_declared")
                    else "shares" if field == "shares_diluted" else "JPY")
            rows.append((TAXONOMY, field, unit, None if field in INSTANT else start, end, float(value), "irbank",
                         filed, None))
    return pd.DataFrame(rows, columns=COLUMNS)
