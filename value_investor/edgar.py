"""05 · edgar — the company list, company profiles and raw XBRL facts.

Three endpoints, all free:
    company_tickers_exchange.json   every listed SEC filer with ticker + exchange
    submissions/CIK##########.json  SIC code, fiscal year end, filing history
    companyfacts/CIK##########.json every XBRL fact the company ever filed

Only facts we map in concepts.py and only annual forms are kept, which
cuts a 5 MB companyfacts file down to a few thousand rows.
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


def listed_companies(exchanges=config.DEFAULT_EXCHANGES) -> pd.DataFrame:
    """One row per company (first ticker wins for multi-class issuers)."""
    raw = get_json(TICKERS_URL)
    df = pd.DataFrame(raw["data"], columns=raw["fields"])
    if exchanges:
        df = df[df["exchange"].isin(exchanges)]
    return df.drop_duplicates("cik").reset_index(drop=True)


def profile(cik: int) -> dict:
    sub = get_json(SUBMISSIONS_URL.format(cik=cik))
    recent = sub.get("filings", {}).get("recent", {})
    annual_dates = [
        date for form, date in zip(recent.get("form", []), recent.get("filingDate", []))
        if form in ANNUAL_FORMS
    ]
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
    }


def company_facts(cik: int) -> pd.DataFrame:
    raw = get_json(FACTS_URL.format(cik=cik))
    wanted = concepts.wanted_concepts()
    rows = []
    for taxonomy, items in raw.get("facts", {}).items():
        for concept, body in items.items():
            if (taxonomy, concept) not in wanted:
                continue
            for unit, entries in body.get("units", {}).items():
                for e in entries:
                    if e.get("form") not in ANNUAL_FORMS:
                        continue
                    rows.append((
                        taxonomy, concept, unit, e.get("start"), e["end"],
                        float(e["val"]), e["form"], e["filed"], e.get("accn"),
                    ))
    df = pd.DataFrame(rows, columns=[
        "taxonomy", "concept", "unit", "period_start", "period_end", "value", "form", "filed", "accn",
    ])
    for col in ("period_start", "period_end", "filed"):
        df[col] = pd.to_datetime(df[col]).dt.date
    return df


def reporting_currency(facts: pd.DataFrame) -> "str | None":
    money = facts[~facts["unit"].str.contains("/", na=False) & (facts["unit"] != "shares")]
    if money.empty:
        return None
    return money["unit"].value_counts().idxmax()
