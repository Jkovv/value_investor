"""13 · ingestion — pull profiles and facts from EDGAR into DuckDB.

Threads fetch (the SEC limiter keeps them polite), the main thread writes.
A company is refetched only when it has filed a new annual report since the
last run, so re-running over the whole market is cheap.
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from value_investor import config, edgar, store
from value_investor.http import NotFound

logger = logging.getLogger(__name__)


def resolve(tickers=None, exchanges=config.DEFAULT_EXCHANGES, limit=None) -> pd.DataFrame:
    listed = edgar.listed_companies(exchanges=None if tickers else exchanges)
    if tickers:
        wanted = {t.upper().replace(".", "-") for t in tickers}
        found = listed[listed["ticker"].str.upper().isin(wanted)]
        missing = wanted - set(found["ticker"].str.upper())
        if missing:
            logger.warning("not found on EDGAR: %s", ", ".join(sorted(missing)))
        return found.drop_duplicates("cik").reset_index(drop=True)
    return listed.head(limit) if limit else listed


def _fetch(cik: int, known_filed, refresh: bool):
    prof = edgar.profile(cik)
    if not prof["last_annual_filed"]:
        return prof, None, "no annual report"
    if not refresh and known_filed is not None and str(known_filed) == str(prof["last_annual_filed"]):
        return prof, None, "unchanged"
    facts = edgar.company_facts(cik)
    return prof, facts, "fetched"


def ingest(targets: pd.DataFrame, refresh: bool = False, workers: int = config.SEC_WORKERS) -> dict:
    counts = {"fetched": 0, "unchanged": 0, "no annual report": 0, "no facts": 0, "failed": 0}
    with store.connect() as con:
        known = {int(r.cik): r.last_annual_filed for r in store.companies(con).itertuples()}
        listed_ticker = {int(r.cik): (r.ticker, r.exchange) for r in targets.itertuples()}

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_fetch, int(cik), known.get(int(cik)), refresh): int(cik)
                for cik in targets["cik"]
            }
            for done, fut in enumerate(as_completed(futures), start=1):
                cik = futures[fut]
                try:
                    prof, facts, outcome = fut.result()
                except NotFound:
                    counts["no facts"] += 1
                    continue
                except Exception as exc:
                    counts["failed"] += 1
                    logger.warning("CIK %s failed: %s", cik, exc)
                    continue

                ticker, exchange = listed_ticker.get(cik, (None, None))
                prof["ticker"] = ticker or prof["ticker"]
                prof["exchange"] = exchange or prof["exchange"]
                if outcome == "fetched":
                    prof["currency"] = edgar.reporting_currency(facts)
                    store.upsert_company(con, prof)
                    store.replace_facts(con, cik, facts)
                elif outcome == "unchanged":
                    existing = store.company(con, cik) or {}
                    prof["currency"] = existing.get("currency")
                    store.upsert_company(con, prof)
                counts[outcome] += 1
                if done % 100 == 0 or done == len(futures):
                    logger.info("%d / %d companies  %s", done, len(futures), counts)
    return counts
