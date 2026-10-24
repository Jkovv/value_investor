"""twelve years of statements for krx listings, from the fss's dart.

every annual report (사업보고서) filed with dart since 2011 comes with its
statements in xbrl, three years each: the year and the two before it. dart's
public website finds a company by its stock code, lists its annual reports and
hands out the xbrl without an api key, so four reports (2025, 2022, 2019, 2016)
cover twelve years. the tags are ifrs, plus dart's own for a few korean lines
(operating income, buybacks), and the year as last restated is kept. banks,
insurers and brokers only file xbrl from 2023, so they keep yahoo's years.
"""

import io
import logging
import re
import threading
import time
import zipfile
from datetime import date

import pandas as pd
import requests

from value_investor import concepts
from value_investor.china import in_todays_units, splits_of
from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

BASE = "https://dart.fss.or.kr"
TAXONOMY = "dart"
GAP = 1.5           # seconds between requests
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
_lock = threading.Lock()
_last = [0.0]
_session: list = []

# dart's own tags, tried after the ifrs ones in concepts.py
EXTRA = {
    "operating_income": ["OperatingIncomeLoss"],
    "receivables": ["ShortTermTradeReceivable"],
    "long_term_debt": [("sum", ["LongTermBorrowingsGross", "BondsIssued"])],
    "buybacks": ["AcquisitionOfTreasuryShares", "PurchaseOfTreasuryShares"],
    "depreciation": ["DepreciationExpense", "AdjustmentsForDepreciationExpense"],
    "eps_diluted": ["BasicEarningsLossPerShare"],
}
LEAD = {"operating_income"}         # dart's operating income is the one korean filers always tag
# korean sg&a includes r&d; checked against yahoo it never matched, so yahoo's years stand
LEFT_OUT = {"sga"}
# a company without minority holders tags its profit as the group's (yuhan)
NET_INCOME = ("ProfitLossAttributableToOwnersOfParent", "ProfitLoss")
CTX = re.compile(r'<(?:xbrli:)?context\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</(?:xbrli:)?context>', re.S)
UNIT = re.compile(r'<(?:xbrli:)?unit\b[^>]*\bid="([^"]+)"[^>]*>(.*?)</(?:xbrli:)?unit>', re.S)
FACT = re.compile(r'<(?:ifrs-full|ifrs|dart):(\w+)\b([^>]*?)>([^<]*)</(?:ifrs-full|ifrs|dart):\1>')


def code_for(symbol: str) -> "str | None":
    code, _, suffix = symbol.upper().partition(".")
    return code if suffix in ("KS", "KQ") and code else None


def _http() -> requests.Session:
    if not _session:
        s = requests.Session()
        s.headers["User-Agent"] = AGENT
        s.get(BASE + "/dsab007/main.do", timeout=30)
        _session.append(s)
    return _session[0]


def _call(method: str, path: str, **kw) -> requests.Response:
    for attempt in range(3):
        with _lock:
            wait = _last[0] + GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                resp = _http().request(method, BASE + path, timeout=120, **kw)
            except (requests.Timeout, requests.ConnectionError):
                resp = None
            _last[0] = time.monotonic()
        if resp is None or resp.status_code in (403, 429, 503):
            time.sleep(60 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp
    raise TimeoutError(f"dart kept refusing {path}")


def corp_code(stock: str) -> "str | None":
    """dart's own company code for a stock code (005930 -> 00126380)."""
    text = _call("POST", "/corp/searchExistAll.ax", data={"textCrpNm": stock}).text.strip()
    code = text.split(",")[0].strip()
    return code if code.isdigit() else None


def annual_reports(corp: str, stock: str) -> list:
    """[(receipt number, fiscal year end)] of the annual reports of the last ten years, the
    latest version of each, newest first. dart searches at most ten years at a time."""
    today = date.today()
    form = {"currentPage": 1, "maxResults": 50, "maxLinks": 10, "sort": "date", "series": "desc",
            "textCrpCik": corp, "textCrpNm": stock, "startDate": f"{today.year - 9}0101",
            "endDate": today.strftime("%Y%m%d"), "finalReport": "recent", "publicType": "A001",
            "businessCode": "all", "autoSearch": "N", "option": "corp"}
    html = _call("POST", "/dsab007/detailSearch.ax", data=form).text
    out = []
    for rcp, title in re.findall(r'rcpNo=(\d{14})[^>]*>\s*(.*?)</a>', html, re.S):
        m = re.search(r"\((\d{4})\.(\d{2})\)", title)
        if m and "사업보고서" in title:
            end = (pd.Timestamp(int(m.group(1)), int(m.group(2)), 1) + pd.offsets.MonthEnd(0)).date()
            out.append((rcp, end))
    return sorted(set(out), key=lambda r: r[1], reverse=True)


def xbrl(rcp: str) -> "str | None":
    """the xbrl instance of one report, or None when the report carries none."""
    viewer = _call("GET", f"/dsaf001/main.do?rcpNo={rcp}").text
    m = re.search(r"openPdfDownload\('(\d+)', '(\d+)'\)", viewer)
    if not m:
        return None
    # the download answers empty without the download window as referer
    popup = f"/pdf/download/main.do?rcp_no={rcp}&dcm_no={m.group(2)}"
    resp = _call("GET", f"/pdf/download/ifrs.do?rcp_no={rcp}&dcm_no={m.group(2)}&lang=ko",
                 headers={"Referer": BASE + popup})
    if not resp.content.startswith(b"PK"):
        return None
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    names = [n for n in z.namelist() if n.endswith(".xbrl")]
    return z.read(names[0]).decode("utf-8", "replace") if names else None


def parse(text: str) -> "tuple[dict, str | None]":
    """{tag: {(start, end): value}} for the group's own statements, and their currency.
    consolidated where the company publishes it (no dimension, or the consolidated member),
    the company alone otherwise."""
    contexts = {}
    for cid, body in CTX.findall(text):
        dims = [d.strip().split(":")[-1] for d in re.findall(r"<[\w:]*explicitMember\b[^>]*>([^<]+)<", body)]
        dims = [d for d in dims if d != "OrdinarySharesMember"]       # eps of the common shares (hyundai)
        start = re.search(r"startDate>([^<]+)<", body)
        end = re.search(r"(?:endDate|instant)>([^<]+)<", body)
        if end is None or len(dims) > 1:
            continue
        scope = "group" if not dims or dims[0] == "ConsolidatedMember" else (
            "alone" if dims[0] == "SeparateMember" else None)
        if scope:
            contexts[cid] = (scope, start.group(1).strip() if start else None, end.group(1).strip())
    units = {uid: re.findall(r"iso4217:([A-Z]{3})", body) for uid, body in UNIT.findall(text)}
    found = {"group": {}, "alone": {}}
    money = {"group": None, "alone": None}
    for tag, attrs, value in FACT.findall(text):
        ref = re.search(r'contextRef="([^"]+)"', attrs)
        unit = re.search(r'unitRef="([^"]+)"', attrs)
        if not ref or ref.group(1) not in contexts:
            continue
        try:
            number = float(value.strip())
        except ValueError:
            continue
        scope, start, end = contexts[ref.group(1)]
        found[scope].setdefault(tag, {})[(start, end)] = number
        codes = units.get(unit.group(1), []) if unit else []
        if len(codes) == 1 and tag in NET_INCOME:
            money[scope] = codes[0]
    scope = "group" if any(found["group"].get(t) for t in NET_INCOME) else "alone"
    return found[scope], money[scope]


def _alternatives(field: str) -> list:
    ifrs = concepts.alternatives(field, concepts.I)
    extra = EXTRA.get(field, [])
    return extra + ifrs if field in LEAD else ifrs + extra


def _value(tags: dict, alt, period):
    if isinstance(alt, tuple):
        parts = [tags.get(n, {}).get(period) for n in alt[1]]
        parts = [p for p in parts if p is not None]
        return sum(parts) if parts else None
    return tags.get(alt, {}).get(period)


def facts_from(tags: dict, currency: str, filed) -> pd.DataFrame:
    """one report's tags -> facts for each of its years, in our layout."""
    years = {}
    for tag in NET_INCOME:
        for (start, end) in tags.get(tag, {}):
            if start and 330 <= (pd.Timestamp(end) - pd.Timestamp(start)).days <= 400:
                years[end] = start
    rows = []
    for end, start in years.items():
        v = {}
        for field in concepts.FIELDS:
            if field in LEFT_OUT:
                continue
            period = (None, end) if concepts.kind(field) == concepts.INSTANT else (start, end)
            for alt in _alternatives(field):
                value = _value(tags, alt, period)
                if value is not None:
                    v[field] = value
                    break
        if v.get("net_income") and v.get("eps_diluted") and v["net_income"] / v["eps_diluted"] > 0:
            v["shares_diluted"] = v["net_income"] / v["eps_diluted"]
        for field, value in v.items():
            unit = (f"{currency}/shares" if field in concepts.PER_SHARE
                    else "shares" if field in concepts.SHARE_COUNTS else currency)
            instant = concepts.kind(field) == concepts.INSTANT
            rows.append((TAXONOMY, field, unit, None if instant else pd.Timestamp(start).date(),
                         pd.Timestamp(end).date(), float(value), "dart", filed, None))
    return pd.DataFrame(rows, columns=COLUMNS)


def statements(symbol: str) -> pd.DataFrame:
    stock = code_for(symbol)
    if stock is None:
        return pd.DataFrame(columns=COLUMNS)
    corp = corp_code(stock)
    if corp is None:
        return pd.DataFrame(columns=COLUMNS)
    frames, covered = [], set()
    for rcp, end in annual_reports(corp, stock):
        if end in covered:
            continue
        text = xbrl(rcp)
        if text is None:
            continue
        tags, currency = parse(text)
        if not currency:
            continue
        filed = date(int(rcp[:4]), int(rcp[4:6]), int(rcp[6:8]))
        facts = facts_from(tags, currency, filed)
        if facts.empty:
            continue
        frames.append(facts)
        covered.update(facts["period_end"])
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    facts = pd.concat(frames, ignore_index=True)
    # a year in two reports keeps the later report's figure
    facts = facts.sort_values("filed").drop_duplicates(["concept", "period_end"], keep="last")
    return in_todays_units(facts.reset_index(drop=True), splits_of(symbol))
