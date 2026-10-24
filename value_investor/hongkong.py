"""up to twenty years of statements for hkex listings, from eastmoney.

eastmoney's hong kong main-indicator table gives the headline lines (revenue,
profits, eps, assets, equity, operating cash flow) for every year in one call,
and its statement tables fill in capex, depreciation, dividends paid, debt and
working capital. its currency label says hkd even when the figures are in yuan,
so the currency is settled by matching the years both have against yahoo's,
and the figures are moved into yahoo's currency.
"""

import logging

import pandas as pd
import requests

from value_investor import fx, statements as stmts
from value_investor.china import HEADERS
from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

URL = "https://datacenter.eastmoney.com/securities/api/data/v1/get"
TAXONOMY = "eastmoney-hk"
TOLERANCE = 0.03

FIELDS = {
    "revenue": "OPERATE_INCOME",
    "gross_profit": "GROSS_PROFIT",
    "operating_income": "OPERATE_PROFIT",
    "pretax_income": "PRETAX_PROFIT",
    "net_income": "HOLDER_PROFIT",
    "eps_diluted": "DILUTED_EPS",
    "total_assets": "TOTAL_ASSETS",
    "total_liabilities": "TOTAL_LIABILITIES",
    "equity": "TOTAL_PARENT_EQUITY",
    "operating_cash_flow": "NETCASH_OPERATE",
    "cash": "END_CASH",
}
# statement lines by eastmoney's standard item names, added up
REPORTS = ("RPT_HKF10_FN_INCOME_PC", "RPT_HKF10_FN_BALANCE_PC", "RPT_HKF10_FN_CASHFLOW_PC")
LINES = {
    "interest_expense": ["融资成本"],
    "income_tax": ["税项"],
    "depreciation": ["加:折旧及摊销"],
    "capex": ["购建固定资产", "购建无形资产及其他资产"],
    "dividends_paid": ["已付股息(融资)"],
    "inventory": ["存货"],
    "receivables": ["应收帐款"],
    "current_assets": ["流动资产合计"],
    "current_liabilities": ["流动负债合计"],
    "ppe": ["固定资产"],
    "goodwill": ["商誉"],
    "intangibles": ["无形资产"],
    "short_term_debt": ["短期贷款"],
    "long_term_debt": ["长期贷款"],
    "equity_incl_nci": ["总权益"],
}
POSITIVE = {"interest_expense", "income_tax", "depreciation", "capex", "dividends_paid"}
INSTANT = {"total_assets", "total_liabilities", "equity", "cash", "inventory", "receivables", "current_assets",
           "current_liabilities", "ppe", "goodwill", "intangibles", "short_term_debt", "long_term_debt",
           "equity_incl_nci"}


def secucode(symbol: str) -> "str | None":
    code, _, suffix = symbol.upper().partition(".")
    return f"{int(code):05d}.HK" if suffix == "HK" and code.isdigit() else None


def _get(report: str, code: str, columns: str, sort: str, page: int = 1, size: int = 500) -> dict:
    params = {"reportName": report, "columns": columns, "quoteColumns": "",
              "filter": f'(SECUCODE="{code}")(DATE_TYPE_CODE="001")', "pageNumber": page, "pageSize": size,
              "sortTypes": "-1", "sortColumns": sort, "source": "F10", "client": "PC"}
    return requests.get(URL, params=params, headers=HEADERS, timeout=30).json().get("result") or {}


def records(symbol: str) -> list:
    code = secucode(symbol)
    if code is None:
        return []
    return _get("RPT_HKF10_FN_MAININDICATOR", code, "ALL", "STD_REPORT_DATE", size=30).get("data") or []


def lines(symbol: str) -> dict:
    """{period end: {our field: value}} from the three statement tables."""
    code = secucode(symbol)
    out: dict = {}
    if code is None:
        return out
    wanted = {name: field for field, names in LINES.items() for name in names}
    for report in REPORTS:
        page, pages = 1, 1
        while page <= pages:
            result = _get(report, code, "REPORT_DATE,STD_ITEM_NAME,AMOUNT", "REPORT_DATE", page)
            pages = result.get("pages") or 1
            for row in result.get("data") or []:
                field = wanted.get(row.get("STD_ITEM_NAME"))
                if field is None or row.get("AMOUNT") is None:
                    continue
                end = pd.Timestamp(str(row["REPORT_DATE"])[:10]).date()
                year = out.setdefault(end, {})
                year[field] = year.get(field, 0.0) + float(row["AMOUNT"])
            page += 1
    return out


def statements(symbol: str) -> pd.DataFrame:
    """facts with a placeholder currency; settle() picks the real one before storing."""
    facts = facts_from(records(symbol), "XXX", lines(symbol))
    if facts.empty:
        return facts
    try:
        import yfinance as yf
        from value_investor.china import bonus_factors
        splits = [(pd.Timestamp(d).date(), float(r)) for d, r in yf.Ticker(symbol).splits.items() if r and r > 0]
    except Exception:
        splits = []
    if splits:
        shares = facts[facts["concept"] == "shares_diluted"].set_index("period_end")["value"].to_dict()
        factors = bonus_factors(shares, splits)
        for concept, op in (("shares_diluted", lambda v, f: v * f), ("eps_diluted", lambda v, f: v / f)):
            mask = facts["concept"] == concept
            facts.loc[mask, "value"] = [op(v, factors.get(e, 1.0)) for v, e in
                                        zip(facts.loc[mask, "value"], facts.loc[mask, "period_end"])]
    return facts


def facts_from(rows: list, currency: str, extra: "dict | None" = None) -> pd.DataFrame:
    out = []
    for rec in rows:
        # std_report_date files every year under december; report_date is when it really ended
        end = pd.Timestamp(str(rec.get("REPORT_DATE") or rec.get("STD_REPORT_DATE"))[:10]).date()
        start = (pd.Timestamp(str(rec["START_DATE"])[:10]).date() if rec.get("START_DATE")
                 else (pd.Timestamp(end) - pd.Timedelta(days=364)).date())
        filed = (pd.Timestamp(end) + pd.Timedelta(days=90)).date()     # annual results are due within three months
        values = {field: rec.get(key) for field, key in FIELDS.items()}
        if values["eps_diluted"] is None:
            values["eps_diluted"] = rec.get("BASIC_EPS")
        pbt, rate = rec.get("PRETAX_PROFIT"), rec.get("TAX_EBT")
        if pbt is not None and rate is not None:
            values["income_tax"] = pbt * rate / 100
        if rec.get("HOLDER_PROFIT") and rec.get("DIVI_RATIO") is not None:
            values["dividends_paid"] = rec["HOLDER_PROFIT"] * rec["DIVI_RATIO"]
        for field, value in ((extra or {}).get(end) or {}).items():
            values[field] = abs(value) if field in POSITIVE else value
        eps, ni = values.get("eps_diluted"), values.get("net_income")
        if eps and ni and ni / eps > 0:
            values["shares_diluted"] = ni / eps
        for field, value in values.items():
            if value is None:
                continue
            unit = f"{currency}/shares" if field == "eps_diluted" else "shares" if field == "shares_diluted" else currency
            out.append((TAXONOMY, field, unit, None if field in INSTANT else start, end, float(value),
                        "eastmoney", filed, None))
    # a year can come twice (a restated report); the newest row is first
    return pd.DataFrame(out, columns=COLUMNS).drop_duplicates(["concept", "period_end"], keep="first")


def settle(con, cik: int, facts: pd.DataFrame) -> pd.DataFrame:
    """eastmoney gives some companies in hkd and others in yuan, whatever they report in, so
    the currency that makes net income agree with yahoo's in the years both have is the one,
    and the figures are moved into yahoo's currency at each year end. nothing is kept if no
    currency agrees."""
    if facts.empty:
        return facts
    from value_investor import store
    ours = stmts.annual_statements(store.load_facts(con, cik))
    if ours.empty:
        return facts.iloc[0:0]
    target = ours.attrs.get("currency")
    ni = facts[facts["concept"] == "net_income"]
    mine = pd.Series(ni["value"].to_numpy(), index=pd.to_datetime(ni["period_end"]))
    theirs = ours["net_income"].dropna()
    ends = pd.to_datetime(facts["period_end"]).unique()
    for candidate in dict.fromkeys([target, "HKD", "CNY", "USD"]):
        rates = {end: 1.0 if candidate == target else fx.rate(con, candidate, target, when=end) for end in ends}
        hits = [abs(mine[end] * rates[end] / value - 1) <= TOLERANCE
                for end, value in theirs.items() if end in mine.index and value and rates.get(end)]
        if hits and sum(hits) >= max(1, len(hits) // 2):
            out = facts.copy()
            rate = pd.to_datetime(out["period_end"]).map(rates)
            out = out[rate.notna().to_numpy()]
            rate = rate[rate.notna()].to_numpy()
            money = (out["unit"] != "shares").to_numpy()
            out.loc[money, "value"] = out.loc[money, "value"].to_numpy() * rate[money]
            out["unit"] = out["unit"].str.replace("XXX", target)
            return out
    return facts.iloc[0:0]
