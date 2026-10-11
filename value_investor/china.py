"""27 · china: ten years of statements for shanghai, shenzhen and beijing listings.

yahoo stops at four years. eastmoney's f10 pages (the data behind akshare)
go back to the listing, are free and need no key. the json endpoints take
at most five report dates per call, so ten years is two calls a statement.
values come in yuan, already consolidated; the announcement date is the
filing date, so history stays point in time.
"""

import logging
import time
from datetime import date

import pandas as pd
import requests
import yfinance as yf
from bs4 import BeautifulSoup

from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

BASE = "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/"
DATACENTER = "https://datacenter-web.eastmoney.com/api/data/v1/get"
STATEMENTS = ("lrbAjaxNew", "zcfzbAjaxNew", "xjllbAjaxNew")
TAXONOMY = "eastmoney"
YEARS = 10
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://emweb.securities.eastmoney.com/"}

# our line -> eastmoney fields, added up; the first group with any value wins
FIELDS = {
    "revenue": [["TOTAL_OPERATE_INCOME"], ["OPERATE_INCOME"]],
    "cost_of_revenue": [["OPERATE_COST"]],
    "sga": [["SALE_EXPENSE", "MANAGE_EXPENSE"]],
    "rnd": [["RESEARCH_EXPENSE"]],
    "operating_income": [["OPERATE_PROFIT"]],
    "interest_expense": [["FE_INTEREST_EXPENSE"], ["INTEREST_EXPENSE"]],
    "pretax_income": [["TOTAL_PROFIT"]],
    "income_tax": [["INCOME_TAX"]],
    "net_income": [["PARENT_NETPROFIT"], ["NETPROFIT"]],
    "eps_diluted": [["DILUTED_EPS"], ["BASIC_EPS"]],
    "cash": [["MONETARYFUNDS"]],
    "short_term_investments": [["TRADE_FINASSET_NOTFVTPL"], ["TRADE_FINASSET"]],
    "receivables": [["ACCOUNTS_RECE"], ["NOTE_ACCOUNTS_RECE"]],
    "inventory": [["INVENTORY"]],
    "current_assets": [["TOTAL_CURRENT_ASSETS"]],
    "ppe": [["FIXED_ASSET"]],
    "goodwill": [["GOODWILL"]],
    "intangibles": [["INTANGIBLE_ASSET"]],
    "total_assets": [["TOTAL_ASSETS"]],
    "current_liabilities": [["TOTAL_CURRENT_LIAB"]],
    "short_term_debt": [["SHORT_LOAN", "NONCURRENT_LIAB_1YEAR"]],
    "long_term_debt": [["LONG_LOAN", "BOND_PAYABLE"]],
    "total_liabilities": [["TOTAL_LIABILITIES"]],
    "liabilities_and_equity": [["TOTAL_LIAB_EQUITY"]],
    "equity": [["TOTAL_PARENT_EQUITY"]],
    "equity_incl_nci": [["TOTAL_EQUITY"]],
    # retained earnings in china sit in two lines: the statutory surplus reserve and the rest
    "retained_earnings": [["UNASSIGN_RPOFIT", "SURPLUS_RESERVE"]],
    "treasury_stock": [["TREASURY_SHARES"]],
    "operating_cash_flow": [["NETCASH_OPERATE"]],
    "capex": [["CONSTRUCT_LONG_ASSET"]],
    "depreciation": [["FA_IR_DEPR", "IA_AMORTIZE", "USERIGHT_ASSET_AMORTIZE"]],
    "stock_issued": [["ACCEPT_INVEST_CASH"]],
}
INSTANT = {"cash", "short_term_investments", "receivables", "inventory", "current_assets", "ppe", "goodwill",
           "intangibles", "total_assets", "current_liabilities", "short_term_debt", "long_term_debt",
           "total_liabilities", "liabilities_and_equity", "equity", "equity_incl_nci", "retained_earnings",
           "treasury_stock"}


def yahoo_symbol(code: str) -> str:
    """600519 -> 600519.SS; shenzhen codes start 0/2/3, beijing 4/8/92."""
    if code.startswith(("6", "9")) and not code.startswith("92"):
        return f"{code}.SS"
    if code.startswith(("4", "8", "92")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def universe(min_cap_cny: float) -> pd.DataFrame:
    """every a-share above the floor, from eastmoney's valuation table.
    yahoo's screener misses some of the largest (moutai, ping an, agricultural bank)."""
    base = {"reportName": "RPT_VALUEANALYSIS_DET", "source": "WEB", "client": "WEB",
            "columns": "SECURITY_CODE,SECURITY_NAME_ABBR,TRADE_DATE,TOTAL_MARKET_CAP"}
    latest = requests.get(DATACENTER, headers=HEADERS, timeout=30, params=dict(
        base, sortColumns="TRADE_DATE", sortTypes="-1", pageSize=1, pageNumber=1)).json()
    day = latest["result"]["data"][0]["TRADE_DATE"][:10]
    rows, page = [], 1
    while True:
        data = requests.get(DATACENTER, headers=HEADERS, timeout=30, params=dict(
            base, sortColumns="TOTAL_MARKET_CAP", sortTypes="-1", pageSize=500, pageNumber=page,
            filter=f"(TRADE_DATE='{day}')")).json()["result"]["data"]
        rows += [r for r in data if (r.get("TOTAL_MARKET_CAP") or 0) >= min_cap_cny]
        if not data or (data[-1].get("TOTAL_MARKET_CAP") or 0) < min_cap_cny:
            break
        page += 1
        time.sleep(0.3)
    return pd.DataFrame({"symbol": [yahoo_symbol(r["SECURITY_CODE"]) for r in rows],
                         "market_cap": [float(r["TOTAL_MARKET_CAP"]) for r in rows]})


def em_code(symbol: str) -> "str | None":
    """600519.SS -> SH600519, 000858.SZ -> SZ000858, 830799.BJ -> BJ830799."""
    code, _, suffix = symbol.upper().partition(".")
    prefix = {"SS": "SH", "SZ": "SZ", "BJ": "BJ"}.get(suffix)
    return f"{prefix}{code}" if prefix and code.isdigit() else None


def _company_type(code: str) -> str:
    """eastmoney files banks, insurers and brokers under their own statement layouts."""
    html = requests.get(BASE + "Index", params={"type": "web", "code": code.lower()}, headers=HEADERS, timeout=30).text
    found = BeautifulSoup(html, "html.parser").find(attrs={"id": "hidctype"})
    return found["value"] if found else "4"


def _get(statement: str, code: str, ctype: str, dates: list, retries: int = 3) -> list:
    for attempt in range(retries + 1):
        try:
            r = requests.get(BASE + statement, headers=HEADERS, timeout=30, params={
                "companyType": ctype, "reportDateType": 1, "reportType": 1, "dates": ",".join(dates), "code": code})
            return r.json().get("data") or []
        except (requests.RequestException, ValueError):
            if attempt == retries:
                raise
            time.sleep(3 * (attempt + 1))
    return []


def _value(record: dict, groups: list) -> "float | None":
    for group in groups:
        parts = [record.get(name) for name in group]
        parts = [float(p) for p in parts if isinstance(p, (int, float))]
        if parts:
            return sum(parts)
    return None


def statements(symbol: str, years: int = YEARS) -> pd.DataFrame:
    """annual facts for one a-share listing, in our facts layout."""
    code = em_code(symbol)
    if code is None:
        return pd.DataFrame(columns=COLUMNS)
    last = date.today().year - 1
    dates = [f"{y}-12-31" for y in range(last, last - years, -1)]
    chunks = [dates[i:i + 5] for i in range(0, len(dates), 5)]
    try:
        ctype = _company_type(code)
    except requests.RequestException:
        ctype = "4"
    records: dict = {}
    for statement in STATEMENTS:
        for chunk in chunks:
            for row in _get(statement, code, ctype, chunk):
                key = str(row.get("REPORT_DATE", ""))[:10]
                merged = records.setdefault(key, {})
                merged.update({k: v for k, v in row.items() if v is not None})
    try:
        splits = [(pd.Timestamp(d).date(), float(r)) for d, r in yf.Ticker(symbol).splits.items() if r and r > 0]
    except Exception:
        splits = []
    return facts_from(records, splits)


def bonus_factors(counts: dict, splits: list) -> dict:
    """year end -> how many of today's shares one share of that year became.

    bonus shares (送转股) work like splits, and yahoo lists them as such. eastmoney
    restates the year just before an issue (from the next report's comparatives)
    but not the ones before that, so the date alone can't say which years to adjust.
    the share count can: walking back from the latest year, a year-on-year jump that
    matches a listed ratio is where the old units start."""
    ends = sorted(e for e, n in counts.items() if n)
    factors, factor = {}, 1.0
    pending = sorted(splits, reverse=True)
    if ends:
        factors[ends[-1]] = 1.0
    for later, earlier in zip(reversed(ends), reversed(ends[:-1])):
        jump = counts[later] / counts[earlier]
        for when, ratio in pending:
            if when > earlier and abs(jump / ratio - 1) < 0.08:
                factor *= ratio
                pending.remove((when, ratio))
                break
        factors[earlier] = factor
    return factors


def in_todays_units(facts: pd.DataFrame, splits: list) -> pd.DataFrame:
    """share counts, eps and dividends per share of each year, moved into today's shares.
    for the local sources outside china that give yearly counts as they stood."""
    if not splits or facts.empty:
        return facts
    facts = facts.copy()
    shares = facts[facts["concept"] == "shares_diluted"].set_index("period_end")["value"].to_dict()
    factors = bonus_factors(shares, splits)
    for concept, op in (("shares_diluted", lambda v, f: v * f), ("eps_diluted", lambda v, f: v / f),
                        ("dps_declared", lambda v, f: v / f)):
        mask = facts["concept"] == concept
        facts.loc[mask, "value"] = [op(v, factors.get(e, 1.0)) for v, e in zip(facts.loc[mask, "value"], facts.loc[mask, "period_end"])]
    return facts


def splits_of(symbol: str) -> list:
    """(date, ratio) of every split and bonus issue yahoo knows for a listing."""
    try:
        return [(pd.Timestamp(d).date(), float(r)) for d, r in yf.Ticker(symbol).splits.items() if r and r > 0]
    except Exception:
        return []


def _shares(rec: dict) -> "float | None":
    """the share count behind the year's eps (net income / eps). the year-end share capital
    is the fallback: it can lag a restated eps by one bonus issue."""
    eps = _value(rec, FIELDS["eps_diluted"])
    ni = _value(rec, FIELDS["net_income"])
    if eps and ni and abs(eps) > 1e-6 and ni / eps > 0:
        return ni / eps
    return _value(rec, [["SHARE_CAPITAL"]])


def facts_from(records: dict, splits: "list | None" = None) -> pd.DataFrame:
    """{report date: merged eastmoney record} -> facts rows (taxonomy 'eastmoney', concept = our field).
    per-share figures and share counts come out in today's share units."""
    counts = {pd.Timestamp(k).date(): _shares(r) for k, r in records.items() if k}
    factors = bonus_factors(counts, splits or [])
    out = []
    for end_text, rec in records.items():
        if not end_text:
            continue
        end = pd.Timestamp(end_text).date()
        filed = pd.Timestamp(str(rec.get("NOTICE_DATE") or "")[:10] or end_text).date()
        if filed <= end:
            filed = (pd.Timestamp(end) + pd.Timedelta(days=120)).date()
        currency = rec.get("CURRENCY") or "CNY"
        start = (pd.Timestamp(end) - pd.Timedelta(days=364)).date()
        values = {field: _value(rec, groups) for field, groups in FIELDS.items()}
        # what was paid out in cash, less what went to minority holders and to lenders
        paid = _value(rec, [["ASSIGN_DIVIDEND_PORFIT"]])
        if paid is not None:
            paid -= (_value(rec, [["SUBSIDIARY_PAY_DIVIDEND"]]) or 0) + (values.get("interest_expense") or 0)
            values["dividends_paid"] = max(paid, 0.0)
        if counts.get(end):
            values["shares_diluted"] = counts[end]
        factor = factors.get(end, 1.0)
        if values.get("shares_diluted"):
            values["shares_diluted"] *= factor
        if values.get("eps_diluted"):
            values["eps_diluted"] /= factor
        for field, value in values.items():
            if value is None:
                continue
            unit = f"{currency}/shares" if field == "eps_diluted" else "shares" if field == "shares_diluted" else currency
            out.append((TAXONOMY, field, unit, None if field in INSTANT else start, end, float(value), "eastmoney",
                        filed, None))
    return pd.DataFrame(out, columns=COLUMNS)
