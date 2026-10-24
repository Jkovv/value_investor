"""home listings that also file 20-F, 40-F or 10-K reports with the sec.

large companies listed in the us through adrs (toyota, infosys, sap, petrobras,
canadian banks) file xbrl with the sec, about ten years of it. those facts can
lengthen the four years yahoo gives their home listing. names are matched
loosely, then a match only counts if the sec's revenue for a shared year agrees
with yahoo's: argan sa in paris and argan inc in the us share a name, not a business.
"""

import logging
import re

import pandas as pd

from value_investor import edgar, fx, statements, store
from value_investor.http import NotFound

logger = logging.getLogger(__name__)

SOURCE = "sec-foreign"
SKIP_MARKETS = {"USA", "CHN", "TWN"}      # their own sources go further back
STOP = {"co", "company", "corp", "corporation", "inc", "incorporated", "ltd", "limited", "plc", "sa", "ag", "nv",
        "se", "spa", "ab", "asa", "oyj", "kk", "holdings", "holding", "group", "the", "de", "cv", "sab", "bhd",
        "berhad", "tbk", "pt", "pcl", "public", "adr", "ads", "as", "a", "s", "l", "p", "tr", "n", "v"}
TOLERANCE = 0.06


def name_key(name: "str | None") -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and ")).split()
    return " ".join(w for w in words if w not in STOP)


def candidates(con) -> list:
    """(cik of our yahoo company, its ticker, sec cik) pairs whose names agree."""
    listed = edgar.listed_companies(exchanges=None)
    by_key: dict = {}
    for r in listed.itertuples():
        key = name_key(r.name)
        if len(key) >= 4:
            by_key.setdefault(key, set()).add(int(r.cik))
    rows = con.execute("SELECT cik, ticker, name, market FROM companies WHERE source = 'yahoo'").fetchall()
    out = []
    for cik, ticker, name, market in rows:
        if market in SKIP_MARKETS:
            continue
        for sec_cik in by_key.get(name_key(name), ()):
            out.append((int(cik), ticker, sec_cik))
    return out


def _ratios(con, ours: pd.DataFrame, theirs: pd.DataFrame, line: str):
    """their figure over ours for each year both report, raw and in our currency."""
    if line not in ours or line not in theirs:
        return
    a, b = ours[line].dropna(), theirs[line].dropna()
    a_ccy, b_ccy = ours.attrs.get("currency"), theirs.attrs.get("currency")
    for end, value in a.items():
        near = b[(b.index >= end - pd.Timedelta(days=10)) & (b.index <= end + pd.Timedelta(days=10))]
        if near.empty or not value:
            continue
        other = float(near.iloc[0])
        yield other / value
        if a_ccy != b_ccy:
            rate = fx.rate(con, b_ccy, a_ccy, when=end)
            if rate:
                yield other * rate / value


def agrees(con, ours: pd.DataFrame, theirs: pd.DataFrame) -> bool:
    """same business if revenue or net income matches for a year both report. banks define
    revenue differently in sec filings, so net income has to be enough. a raw match with the
    currencies apart means yahoo's currency label is wrong (vale's dollars marked as reais)."""
    if ours.empty or theirs.empty:
        return False
    return any(abs(r - 1) <= TOLERANCE for line in ("revenue", "net_income") for r in _ratios(con, ours, theirs, line))


def link(con) -> dict:
    """attach sec filings to the matching home listings."""
    counts = {"candidates": 0, "linked": 0, "no filings": 0, "different business": 0}
    pairs = candidates(con)
    counts["candidates"] = len(pairs)
    done = store.fetched(con, SOURCE)
    for cik, ticker, sec_cik in pairs:
        if cik in done:
            continue
        try:
            annual, _ = edgar.company_facts(sec_cik)
        except NotFound:
            counts["no filings"] += 1
            store.mark_fetched(con, cik, SOURCE, 0)
            continue
        except Exception as exc:
            logger.warning("sec facts failed for %s (CIK %s): %s", ticker, sec_cik, exc)
            continue
        theirs = statements.annual_statements(annual)
        ours = statements.annual_statements(store.load_facts(con, cik))
        if theirs.empty or not agrees(con, ours, theirs):
            counts["different business"] += 1
            store.mark_fetched(con, cik, SOURCE, 0)
            continue
        store.replace_facts(con, cik, annual, taxonomies=sorted(annual["taxonomy"].unique()))
        store.mark_fetched(con, cik, SOURCE, len(theirs))
        counts["linked"] += 1
        logger.info("%s: %d years from SEC filer %s", ticker, len(theirs), sec_cik)
    return counts
