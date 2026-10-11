"""33 · poland: annual statements for gpw listings, from biznesradar.

biznesradar.pl shows each company's profit and loss, balance sheet and cash
flow year by year, most of them back to the mid 2000s, with the date each
report came out (robots.txt allows the report pages). figures are in thousands
of zloty, also for companies that report in euros or dollars, so a company's
years are only kept when its net income agrees with yahoo's in the same currency.
"""

import calendar
import logging
import re
import threading
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from value_investor import statements as stmts
from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

URL = "https://www.biznesradar.pl/{page}/{slug}"
PAGES = {
    "pl": "raporty-finansowe-rachunek-zyskow-i-strat",
    "bs": "raporty-finansowe-bilans",
    "cf": "raporty-finansowe-przeplywy-pieniezne",
    "shares": "wskazniki-wartosci-rynkowej",
}
TAXONOMY = "biznesradar"
GAP = 2.0           # seconds between pages
TOLERANCE = 0.03
_lock = threading.Lock()
_last = [0.0]
MONTHS = {"sty": 1, "lut": 2, "mar": 3, "kwi": 4, "maj": 5, "cze": 6, "lip": 7, "sie": 8, "wrz": 9, "paź": 10,
          "lis": 11, "gru": 12}
SCALE = {"tys.": 1e3, "mln": 1e6}
# a bank's revenue is everything it earns before costs and loan losses
BANK_INCOME = ("IncomeNetIntrestIncome", "IncomeNetFeeExpense", "IncomeDividendIncome", "IncomeRealisedGains",
               "IncomeNetOtherFinIncome", "IncomeNetOtherOperatingIncome")
INSTANT = {"total_assets", "current_assets", "cash", "short_term_investments", "receivables", "inventory", "ppe",
           "goodwill", "intangibles", "current_liabilities", "short_term_debt", "long_term_debt", "equity",
           "equity_incl_nci", "total_liabilities", "retained_earnings", "treasury_stock"}


def code_for(symbol: str) -> "str | None":
    code, _, suffix = symbol.upper().partition(".")
    return code if suffix == "WA" and code else None


def _get(url: str) -> "requests.Response | None":
    for attempt in range(3):
        with _lock:
            wait = _last[0] + GAP - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            try:
                resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            except (requests.Timeout, requests.ConnectionError):
                resp = None
            _last[0] = time.monotonic()
        if resp is None or resp.status_code in (429, 503):
            time.sleep(30 * (attempt + 1))
            continue
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp
    raise TimeoutError(f"biznesradar kept refusing {url}")


def _page(page: str, slug: str) -> "tuple[BeautifulSoup | None, str]":
    """the yearly view of a page, and the company's slug on the site. an old ticker
    (PKN) redirects to the company's name (ORLEN) and loses the yearly switch."""
    resp = _get(URL.format(page=PAGES[page], slug=f"{slug},Y"))
    if resp is None:
        return None, slug
    final = resp.url.rstrip("/").rsplit("/", 1)[-1]
    if not final.endswith(",Y"):
        slug = final
        resp = _get(URL.format(page=PAGES[page], slug=f"{slug},Y"))
        if resp is None:
            return None, slug
    return BeautifulSoup(resp.content, "html.parser"), final.removesuffix(",Y")


def period_end(head: str):
    """'2025 (gru 25)' -> 2025-12-31; trailing four quarters ('O4K') -> None."""
    m = re.match(r"^\d{4}(?:/Q\d)?\s*\((\w{3}) (\d{2})\)", head)
    if not m or m.group(1) not in MONTHS:
        return None
    year, month = 2000 + int(m.group(2)), MONTHS[m.group(1)]
    return pd.Timestamp(year, month, calendar.monthrange(year, month)[1]).date()


def _number(text: str) -> "float | None":
    text = re.sub(r"\s", "", text).replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def table(soup: "BeautifulSoup | None") -> "tuple[dict, dict, str | None]":
    """({row field: {period end: value}}, {period end: report date}, currency) for one page."""
    t = soup.find("table", class_="report-table") if soup else None
    if t is None:
        return {}, {}, None
    note = soup.find("div", class_="report-disclaimer-above")
    note = note.get_text(" ", strip=True) if note else ""
    scale = next((v for k, v in SCALE.items() if k in note), 1.0)
    currency = (re.search(r"\b([A-Z]{3})\b", note) or [None, None])[1]
    ends = [period_end(th.get_text(" ", strip=True)) for th in t.find_all("th", class_="thq")]
    rows, filed = {}, {}
    for tr in t.find_all("tr"):
        field = tr.get("data-field")
        if not field:
            continue
        cells = tr.find_all("td")[1:len(ends) + 1]
        texts = [c.find("span", class_="value") for c in cells]
        texts = [s.get_text(" ", strip=True) if s else "" for s in texts]
        if field == "PrimaryReport":
            filed = {e: pd.Timestamp(x).date() for e, x in zip(ends, texts) if e and re.match(r"\d{4}-\d\d-\d\d", x)}
            continue
        values = {e: _number(x) for e, x in zip(ends, texts) if e}
        rows[field] = {e: v * scale for e, v in values.items() if v is not None}
    return rows, filed, currency


def statements(symbol: str) -> pd.DataFrame:
    code = code_for(symbol)
    if code is None:
        return pd.DataFrame(columns=COLUMNS)
    soup, slug = _page("pl", code)
    pl, filed, currency = table(soup)
    if not pl or not currency:
        return pd.DataFrame(columns=COLUMNS)
    bs, _, _ = table(_page("bs", slug)[0])
    cf, _, _ = table(_page("cf", slug)[0])
    ratios, _, _ = table(_page("shares", slug)[0])
    facts = facts_from(pl, bs, cf, ratios.get("ShareAmount", {}), filed, currency)
    try:
        import yfinance as yf
        splits =[(pd.Timestamp(d).date(), float(r)) for d, r in yf.Ticker(symbol).splits.items() if r and r > 0]
    except Exception:
        splits = []
    return in_todays_units(facts, splits)


def in_todays_units(facts: pd.DataFrame, splits: list) -> pd.DataFrame:
    """share counts are as they stood at each year end; a split after that moves them."""
    if not splits or facts.empty:
        return facts
    from value_investor.china import bonus_factors
    facts = facts.copy()
    shares = facts[facts["concept"] == "shares_diluted"].set_index("period_end")["value"].to_dict()
    factors = bonus_factors(shares, splits)
    for concept, op in (("shares_diluted", lambda v, f: v * f), ("eps_diluted", lambda v, f: v / f)):
        mask = facts["concept"] == concept
        facts.loc[mask, "value"] = [op(v, factors.get(e, 1.0)) for v, e in zip(facts.loc[mask, "value"], facts.loc[mask, "period_end"])]
    return facts


def _plus(*values) -> "float | None":
    present = [v for v in values if v is not None]
    return sum(present) if present else None


def facts_from(pl: dict, bs: dict, cf: dict, shares: dict, filed: dict, currency: str) -> pd.DataFrame:
    """biznesradar's rows -> facts in our layout."""
    bank = "IncomeNetIntrestIncome" in pl
    at = lambda rows, field, end: rows.get(field, {}).get(end)
    rows = []
    for end in sorted(set(pl.get("IncomeShareholderNetProfit", {})) | set(pl.get("IncomeRevenues", {}))):
        p = lambda f: at(pl, f, end)
        b = lambda f: at(bs, f, end)
        c = lambda f: at(cf, f, end)
        v = {"net_income": p("IncomeShareholderNetProfit"),
             "pretax_income": p("IncomeBeforeTaxProfit") if p("IncomeBeforeTaxProfit") is not None else p("IncomeBeforTaxProfit"),
             "depreciation": c("CashflowAmortization"), "total_assets": b("BalanceTotalAssets"),
             "ppe": b("BalanceProperty"), "goodwill": b("BalanceGoodwill"),
             "operating_cash_flow": c("CashflowOperatingCashflow"), "stock_issued": c("CashflowShareCapitalCash")}
        if bank:
            v["revenue"] = _plus(*(p(f) for f in BANK_INCOME))
            v["cash"] = b("BalanceCashWithCentralBank")
            v["long_term_debt"] = _plus(b("BalanceDebtSecurities"), b("BalanceSubodinatedLiabilities"))
            v["equity"] = b("BalanceOwnCapital")
            v["equity_incl_nci"] = b("BalanceTotalCapital")
            v["total_liabilities"] = b("BalanceTotalLiabilities")
        else:
            v["revenue"] = p("IncomeRevenues")
            if p("IncomeCostOfSales"):
                v["cost_of_revenue"] = abs(p("IncomeCostOfSales"))
            sga = _plus(p("IncomeDistributionExpenses"), p("IncomeAdministrativExpenses"))
            if sga:
                v["sga"] = abs(sga)
            v["operating_income"] = p("IncomeEBIT")
            if p("IncomeFinanceCosts"):
                v["interest_expense"] = abs(p("IncomeFinanceCosts"))
            v["cash"] = b("BalanceCash")
            if b("BalanceCurrentInvestments") is not None and b("BalanceCash") is not None:
                v["short_term_investments"] = max(b("BalanceCurrentInvestments") - b("BalanceCash"), 0.0)
            v["current_assets"] = b("BalanceCurrentAssets")
            v["receivables"] = b("BalanceCurrentReceivables")
            v["inventory"] = b("BalanceInventory")
            v["current_liabilities"] = b("BalanceCurrentLiabilities")
            v["short_term_debt"] = _plus(b("BalanceCurrentBorrowings"), b("BalanceCurrentObligations"))
            v["long_term_debt"] = _plus(b("BalanceNoncurrentBorrowings"), b("BalanceNoncurrentObligations"))
            v["equity"] = b("BalanceCapital")
            if v["equity"] is not None:
                v["equity_incl_nci"] = v["equity"] + (b("BalanceNonshareCapital") or 0.0)
                if v["total_assets"] is not None:
                    v["total_liabilities"] = v["total_assets"] - v["equity_incl_nci"]
        if b("BalanceIntangibleAssets") is not None:
            v["intangibles"] = b("BalanceIntangibleAssets") - (v["goodwill"] or 0.0)
        # polish companies move kept profits into reserve capital, so everything above the
        # share capital is what the business has kept
        if v["equity"] is not None and b("BalanceShareCapital") is not None:
            v["retained_earnings"] = v["equity"] - b("BalanceShareCapital")
        if b("BalanceOwnShares"):
            v["treasury_stock"] = abs(b("BalanceOwnShares"))
        net_total, gone = p("IncomeNetProfit"), p("IncomeDiscontinuedProfit") or 0.0
        if v["pretax_income"] is not None and net_total is not None:
            v["income_tax"] = v["pretax_income"] - (net_total - gone)
        for field, line in (("capex", "CashflowCapex"), ("dividends_paid", "CashflowDividend"),
                            ("buybacks", "CashflowStockBuyback")):
            if c(line) is not None:
                v[field] = abs(c(line))
        count = shares.get(end)
        if count and v["net_income"] is not None:
            v["shares_diluted"] = count
            v["eps_diluted"] = v["net_income"] / count
        when = filed.get(end) or (pd.Timestamp(end) + pd.Timedelta(days=120)).date()
        start = (pd.Timestamp(end) - pd.Timedelta(days=364)).date()
        for field, value in v.items():
            if value is None:
                continue
            unit = f"{currency}/shares" if field == "eps_diluted" else "shares" if field == "shares_diluted" else currency
            rows.append((TAXONOMY, field, unit, None if field in INSTANT else start, end, float(value), "biznesradar",
                         when, None))
    return pd.DataFrame(rows, columns=COLUMNS)


def agrees(con, cik: int, facts: pd.DataFrame) -> pd.DataFrame:
    """the facts, if net income matches yahoo's, in yahoo's currency, for at least half the
    years both have. biznesradar converts euro and dollar reporters into zloty, and keeps a
    year as first reported where yahoo has it restated (orlen's 2022)."""
    if facts.empty:
        return facts
    from value_investor import store
    yahoo = store.load_facts(con, cik)
    ours = stmts.annual_statements(yahoo[yahoo["taxonomy"] == "yahoo"])
    if ours.empty or ours.attrs.get("currency") not in set(facts["unit"]):
        return facts.iloc[0:0]
    ni = facts[facts["concept"] == "net_income"]
    mine = {(e.year, e.month): v for e, v in zip(pd.to_datetime(ni["period_end"]), ni["value"])}
    hits = [abs(mine[(end.year, end.month)] / value - 1) <= TOLERANCE
            for end, value in ours["net_income"].dropna().items() if (end.year, end.month) in mine and value]
    return facts if hits and sum(hits) >= max(1, len(hits) // 2) else facts.iloc[0:0]
