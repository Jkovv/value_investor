"""05 · edgar: company list, profiles and raw xbrl facts, all free.

annual and quarterly forms go to separate tables, so the yearly pipeline
never sees a 10-Q.
"""

import logging

import pandas as pd

from value_investor import concepts, config
from value_investor.http import get_json

logger = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "20-F", "20-F/A", "40-F", "40-F/A"}
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
COLUMNS = ["taxonomy", "concept", "unit", "period_start", "period_end", "value", "form", "filed", "accn"]


def listed_companies(exchanges=config.DEFAULT_EXCHANGES) -> pd.DataFrame:
    """one row per company (first ticker wins for multi-class issuers)."""
    raw = get_json(TICKERS_URL)
    df = pd.DataFrame(raw["data"], columns=raw["fields"])
    if exchanges:
        df = df[df["exchange"].isin(exchanges)]
    return df.drop_duplicates("cik").reset_index(drop=True)


def profile(cik: int) -> dict:
    sub = get_json(SUBMISSIONS_URL.format(cik=cik))
    recent = sub.get("filings", {}).get("recent", {})
    forms = list(zip(recent.get("form", []), recent.get("filingDate", [])))
    annual_dates = [d for form, d in forms if form in ANNUAL_FORMS]
    quarter_dates = [d for form, d in forms if form in QUARTERLY_FORMS]
    address = (sub.get("addresses") or {}).get("business") or {}
    if address.get("isForeignLocation"):
        country = address.get("stateOrCountryDescription")
    else:
        country = "United States"
    tickers = sub.get("tickers") or []
    exchanges = sub.get("exchanges") or []
    return {
        "cik": int(cik),
        "name": sub.get("name"),
        "ticker": tickers[0] if tickers else None,
        "exchange": exchanges[0] if exchanges else None,
        "sic": int(sub["sic"]) if str(sub.get("sic") or "").isdigit() else None,
        "sic_description": sub.get("sicDescription"),
        "country": country,
        "fiscal_year_end": sub.get("fiscalYearEnd"),
        "category": sub.get("category"),
        "last_annual_filed": max(annual_dates) if annual_dates else None,
        "last_quarter_filed": max(quarter_dates) if quarter_dates else None,
    }


def company_facts(cik: int) -> "tuple[pd.DataFrame, pd.DataFrame]":
    """(annual facts, quarterly facts)."""
    raw = get_json(FACTS_URL.format(cik=cik))
    wanted = concepts.wanted_concepts()
    annual, quarterly = [], []
    for taxonomy, items in raw.get("facts", {}).items():
        for concept, body in items.items():
            if (taxonomy, concept) not in wanted:
                continue
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    form = e.get("form")
                    bucket = annual if form in ANNUAL_FORMS else quarterly if form in QUARTERLY_FORMS else None
                    if bucket is None:
                        continue
                    bucket.append((taxonomy, concept, unit, e.get("start"), e["end"],
                                   float(e["val"]), form, e["filed"], e.get("accn")))
    return _frame(annual), _frame(quarterly)


def _frame(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    for col in ("period_start", "period_end", "filed"):
        df[col] = pd.to_datetime(df[col]).dt.date
    return df


def reporting_currency(facts: pd.DataFrame) -> "str | None":
    money = facts[~facts["unit"].str.contains("/", na=False) & (facts["unit"] != "shares")]
    if money.empty:
        return None
    return money["unit"].value_counts().idxmax()
