"""28 · taiwan: ten years of statements for twse and tpex listings, from finmind.

finmind republishes the exchanges' filings (mops) as an open api: free, no key
needed (an optional FINMIND_TOKEN raises the hourly limit). income lines are
single quarters, so a year is the sum of four; cash flow is year to date, so
a year is december's figure; the balance sheet is read at december.
"""

import logging
import os
import threading
import time
from datetime import date

import pandas as pd
import requests
import yfinance as yf

from value_investor.china import bonus_factors
from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

URL = "https://api.finmindtrade.com/api/v4/data"
TAXONOMY = "finmind"
YEARS = 10
GAP = 4.0           # seconds between calls; finmind's free tier is a few hundred an hour
_lock = threading.Lock()
_last = [0.0]

INCOME = {
    "revenue": ["Revenue"],
    "cost_of_revenue": ["CostOfGoodsSold"],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncome"],
    "pretax_income": ["PreTaxIncome"],
    "income_tax": ["TAX"],
    # finmind's income dataset names net income to the parent after the equity line it feeds
    "net_income": ["EquityAttributableToOwnersOfParent", "IncomeAfterTaxes"],
    "eps_diluted": ["EPS"],
}
BALANCE = {
    "cash": [["CashAndCashEquivalents"]],
    "receivables": [["AccountsReceivableNet"]],
    "inventory": [["Inventories"]],
    "current_assets": [["CurrentAssets"]],
    "ppe": [["PropertyPlantAndEquipment"]],
    "intangibles": [["IntangibleAssets"]],
    "total_assets": [["TotalAssets"]],
    "current_liabilities": [["CurrentLiabilities"]],
    "short_term_debt": [["ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings"]],
    "long_term_debt": [["LongtermBorrowings", "BondsPayable"]],
    "total_liabilities": [["Liabilities"]],
    "liabilities_and_equity": [["TotalLiabilitiesEquity"]],
    "equity": [["EquityAttributableToOwnersOfParent"]],
    "equity_incl_nci": [["Equity"]],
    "retained_earnings": [["RetainedEarnings"]],
    "treasury_stock": [["TreasuryStock"]],
}
CASH = {
    "operating_cash_flow": [["CashFlowsFromOperatingActivities"]],
    "capex": [["PropertyAndPlantAndEquipment"]],
    "depreciation": [["Depreciation", "AmortizationExpense"]],
    "interest_expense": [["InterestExpense"]],
}


def _get(dataset: str, code: str, start: str) -> pd.DataFrame:
    params = {"dataset": dataset, "data_id": code, "start_date": start}
    token = os.getenv("FINMIND_TOKEN")
    if token:
        params["token"] = token
    for _ in range(4):
        with _lock:
            wait = _last[0] + GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            resp = requests.get(URL, params=params, timeout=60)
            _last[0] = time.monotonic()
        if resp.status_code in (402, 429):
            logger.info("finmind hourly limit reached; waiting ten minutes")
            time.sleep(600)
            continue
        resp.raise_for_status()
        return pd.DataFrame(resp.json().get("data") or [])
    return pd.DataFrame()


def _pick(row: pd.Series, groups: list) -> "float | None":
    for group in groups:
        parts = [row.get(n) for n in group]
        parts = [float(p) for p in parts if p is not None and not pd.isna(p)]
        if parts:
            return sum(parts)
    return None


def statements(symbol: str, years: int = YEARS) -> pd.DataFrame:
    code, _, suffix = symbol.upper().partition(".")
    if suffix not in ("TW", "TWO") or not code.isdigit():
        return pd.DataFrame(columns=COLUMNS)
    first = date.today().year - years - 1
    start = f"{first}-01-01"
    frames = {name: _get(name, code, start) for name in
              ("TaiwanStockFinancialStatements", "TaiwanStockBalanceSheet", "TaiwanStockCashFlowsStatement")}
    try:
        splits = [(pd.Timestamp(d).date(), float(r)) for d, r in yf.Ticker(symbol).splits.items() if r and r > 0]
    except Exception:
        splits = []
    return facts_from(*frames.values(), splits=splits)


def _wide(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    wide = frame.pivot_table(index="date", columns="type", values="value", aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    return wide


def facts_from(income: pd.DataFrame, balance: pd.DataFrame, cash: pd.DataFrame, splits=None) -> pd.DataFrame:
    """finmind's long tables -> one fact per line and year, in our layout and today's share units."""
    inc, bal, cf = _wide(income), _wide(balance), _wide(cash)
    if inc.empty:
        return pd.DataFrame(columns=COLUMNS)
    years: dict = {}
    for year, quarters in inc.groupby(inc.index.year):
        if len(quarters) != 4:
            continue
        end = date(year, 12, 31)
        row = {}
        for field, names in INCOME.items():
            for name in names:
                if name in quarters and quarters[name].notna().all():
                    row[field] = float(quarters[name].sum())
                    break
        dec = pd.Timestamp(end)
        if not bal.empty and dec in bal.index:
            row.update({f: _pick(bal.loc[dec], groups) for f, groups in BALANCE.items()})
        if not cf.empty and dec in cf.index:
            row.update({f: _pick(cf.loc[dec], groups) for f, groups in CASH.items()})
        if row.get("capex") is not None:
            row["capex"] = abs(row["capex"])
        years[end] = row
    counts = {end: (r["net_income"] / r["eps_diluted"]) if r.get("eps_diluted") and r.get("net_income")
              and r["net_income"] / r["eps_diluted"] > 0 else None for end, r in years.items()}
    factors = bonus_factors(counts, splits or [])
    out = []
    for end, row in years.items():
        factor = factors.get(end, 1.0)
        if counts.get(end):
            row["shares_diluted"] = counts[end] * factor
        if row.get("eps_diluted"):
            row["eps_diluted"] /= factor
        filed = (pd.Timestamp(end) + pd.Timedelta(days=90)).date()
        start = (pd.Timestamp(end) - pd.Timedelta(days=364)).date()
        for field, value in row.items():
            if value is None:
                continue
            unit = "TWD/shares" if field == "eps_diluted" else "shares" if field == "shares_diluted" else "TWD"
            instant = field in BALANCE
            out.append((TAXONOMY, field, unit, None if instant else start, end, float(value), "finmind", filed, None))
    return pd.DataFrame(out, columns=COLUMNS)
