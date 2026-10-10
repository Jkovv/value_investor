"""30 · india: twelve years of statements for nse and bse listings, from screener.in.

screener.in shows a company's consolidated profit and loss, balance sheet and
cash flow for the last twelve years on a public page (robots.txt allows it).
figures are in crores and per-share numbers are already adjusted for splits and
bonus issues. the lines are coarser than a filing: no cost of sales or sg&a, so
those checks run on the years yahoo fills in.
"""

import calendar
import logging
import re
import threading
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

URL = "https://www.screener.in/company/{code}/{view}"
TAXONOMY = "screener"
CRORE = 1e7
GAP = 3.0           # seconds between pages
_lock = threading.Lock()
_last = [0.0]
MONTHS = {m: i for i, m in enumerate(calendar.month_abbr) if m}


def _page(code: str, view: str) -> "BeautifulSoup | None":
    for attempt in range(3):
        with _lock:
            wait = _last[0] + GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                resp = requests.get(URL.format(code=code, view=view), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            except (requests.Timeout, requests.ConnectionError):
                resp = None
            _last[0] = time.monotonic()
        if resp is None:
            if attempt == 2:
                raise TimeoutError(f"screener.in kept timing out for {code}")
            time.sleep(30 * (attempt + 1))      # it slows down when busy; give it room
            continue
        if resp.status_code == 429:
            time.sleep(60 * (attempt + 1))
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return BeautifulSoup(resp.text, "html.parser")
    return None


def _number(text: str) -> "float | None":
    text = text.replace(",", "").replace("%", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


def _table(soup: BeautifulSoup, section: str) -> dict:
    """{row label: {period end: value}} for one section of the page."""
    sec = soup.find("section", id=section)
    table = sec.find("table") if sec else None
    if table is None or table.find("thead") is None:
        return {}
    heads = [th.get_text(strip=True) for th in table.find("thead").find_all("th")][1:]
    ends = []
    for h in heads:
        m = re.match(r"([A-Z][a-z]{2}) (\d{4})", h)
        if m:
            year, month = int(m.group(2)), MONTHS[m.group(1)]
            ends.append(pd.Timestamp(year, month, calendar.monthrange(year, month)[1]).date())
        else:
            ends.append(None)                      # ttm
    out = {}
    for tr in table.find("tbody").find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if not cells:
            continue
        label = cells[0].rstrip("+").strip()
        out[label] = {end: _number(v) for end, v in zip(ends, cells[1:]) if end is not None and _number(v) is not None}
    return out


def code_for(symbol: str) -> "str | None":
    code, _, suffix = symbol.upper().partition(".")
    return code if suffix in ("NS", "BO") and code else None


def statements(symbol: str) -> pd.DataFrame:
    code = code_for(symbol)
    if code is None:
        return pd.DataFrame(columns=COLUMNS)
    soup = _page(code, "consolidated/")
    if soup is None or not _table(soup, "profit-loss"):
        soup = _page(code, "")
    if soup is None:
        return pd.DataFrame(columns=COLUMNS)
    return facts_from(_table(soup, "profit-loss"), _table(soup, "balance-sheet"), _table(soup, "cash-flow"))


def _get(rows: dict, *labels):
    for label in labels:
        if label in rows:
            return rows[label]
    return {}


def facts_from(pl: dict, bs: dict, cf: dict) -> pd.DataFrame:
    """screener's rows -> facts in our layout (rupees, not crores)."""
    sales = _get(pl, "Sales", "Revenue")
    is_bank = "Sales" not in pl
    pbt, tax_rate = _get(pl, "Profit before tax"), _get(pl, "Tax %")
    net, eps, payout = _get(pl, "Net Profit"), _get(pl, "EPS in Rs"), _get(pl, "Dividend Payout %")
    interest, dep = _get(pl, "Interest"), _get(pl, "Depreciation")
    capital, reserves = _get(bs, "Equity Capital"), _get(bs, "Reserves")
    borrowings, total = _get(bs, "Borrowings", "Borrowing"), _get(bs, "Total Assets")
    total_side, fixed = _get(bs, "Total Liabilities"), _get(bs, "Fixed Assets")
    cfo, fcf = _get(cf, "Cash from Operating Activity"), _get(cf, "Free Cash Flow")

    rows = []
    for end in sorted(set(sales) | set(net) | set(capital)):
        v = {"revenue": sales.get(end), "pretax_income": pbt.get(end), "net_income": net.get(end),
             "depreciation": dep.get(end), "long_term_debt": borrowings.get(end), "total_assets": total.get(end),
             "ppe": fixed.get(end), "operating_cash_flow": cfo.get(end), "retained_earnings": reserves.get(end)}
        if not is_bank:
            v["interest_expense"] = interest.get(end)
            if pbt.get(end) is not None and interest.get(end) is not None:
                v["operating_income"] = pbt[end] + interest[end]
        if pbt.get(end) is not None and tax_rate.get(end) is not None:
            v["income_tax"] = pbt[end] * tax_rate[end] / 100
        if capital.get(end) is not None and reserves.get(end) is not None:
            v["equity"] = capital[end] + reserves[end]
            if total_side.get(end) is not None:
                v["total_liabilities"] = total_side[end] - v["equity"]
        if cfo.get(end) is not None and fcf.get(end) is not None:
            v["capex"] = max(cfo[end] - fcf[end], 0.0)
        if net.get(end) is not None and payout.get(end) is not None:
            v["dividends_paid"] = net[end] * payout[end] / 100
        money = {k: x * CRORE for k, x in v.items() if x is not None}
        if eps.get(end):
            money["eps_diluted"] = eps[end]
            if money.get("net_income") and money["net_income"] / eps[end] > 0:
                money["shares_diluted"] = money["net_income"] / eps[end]
        filed = (pd.Timestamp(end) + pd.Timedelta(days=60)).date()
        start = (pd.Timestamp(end) - pd.Timedelta(days=364)).date()
        instant = {"long_term_debt", "total_assets", "ppe", "retained_earnings", "equity", "total_liabilities"}
        for field, value in money.items():
            unit = "INR/shares" if field == "eps_diluted" else "shares" if field == "shares_diluted" else "INR"
            rows.append((TAXONOMY, field, unit, None if field in instant else start, end, float(value), "screener",
                         filed, None))
    return pd.DataFrame(rows, columns=COLUMNS)
