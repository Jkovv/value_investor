"""13 · ingestion: pull profiles and facts from EDGAR into DuckDB.

Threads fetch (the SEC limiter keeps them polite), the main thread writes.
A company is refetched only when it has filed a new annual report since the
last run, so re-running over the whole market is cheap.
"""

import logging
import random
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from value_investor import config, edgar, fx, markets, store, yahoo
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
                prof.update(source="sec", market="USA", price_currency="USD", sector=prof.get("sic_description"))
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


WORLD_REFRESH = timedelta(days=30)


def _fetch_yahoo(symbol: str, market: str):
    time.sleep(random.uniform(0.2, 0.8))
    return yahoo.fundamentals(symbol, market)


def ingest_world(iso3s: list, min_cap_usd: float, limit_per_market: "int | None" = None,
                 refresh: bool = False, workers: int = 3) -> dict:
    """Every company above the floor in the given markets, one listing each."""
    counts = {"fetched": 0, "fresh": 0, "foreign listing": 0, "no statements": 0, "failed": 0}
    with store.connect() as con:
        listings = yahoo.universe(con, iso3s, min_cap_usd, limit_per_market)
        if listings.empty:
            return counts
        existing = store.companies(con)
        updated = {r.ticker: r.facts_updated_at for r in existing.itertuples() if r.source == "yahoo"}
        now = datetime.now()
        todo = [r for r in listings.itertuples()
                if refresh or updated.get(r.symbol) is None or now - updated[r.symbol] > WORLD_REFRESH]
        counts["fresh"] = len(listings) - len(todo)
        logger.info("%d companies across %d markets, %d to fetch", len(listings), listings["market"].nunique(), len(todo))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_yahoo, r.symbol, r.market): r for r in todo}
            for done, fut in enumerate(as_completed(futures), start=1):
                r = futures[fut]
                try:
                    facts, prof = fut.result()
                except Exception as exc:
                    counts["failed"] += 1
                    logger.warning("%s failed: %s", r.symbol, exc)
                    continue
                if prof.get("home_market"):
                    counts["foreign listing"] += 1
                    continue
                if facts.empty:
                    counts["no statements"] += 1
                    continue
                prof.update(
                    cik=store.entity_id(con, f"yahoo:{r.symbol}"), ticker=r.symbol, exchange=r.exchange,
                    source="yahoo", market=r.market, name=prof.get("name") or r.name,
                    price_currency=prof.get("price_currency") or r.currency,
                    market_cap=prof.get("market_cap") or r.market_cap,
                )
                store.upsert_company(con, prof)
                store.replace_facts(con, prof["cik"], facts)
                counts["fetched"] += 1
                if done % 50 == 0 or done == len(futures):
                    logger.info("%d / %d  %s", done, len(futures), counts)
        pruned = prune_foreign(con)
        if pruned:
            logger.info("dropped %d listings that belong to other markets", len(pruned))
    return counts


def prune_foreign(con) -> list:
    """Drop stored Yahoo listings that the current rules say belong to another market."""
    gone = []
    for r in store.companies(con).itertuples():
        if r.source != "yahoo" or r.market not in markets.BY_ISO:
            continue
        local = markets.BY_ISO[r.market].currency
        quote = fx.major(r.price_currency)[0]
        foreign_currency = r.currency not in ("USD", "EUR", local) and r.currency in {m.currency for m in markets.MARKETS}
        wrong_market = quote != local and r.currency != local
        moved = yahoo.home_elsewhere({"country": r.country, "financialCurrency": r.currency}, r.market)
        if foreign_currency or wrong_market or moved:
            for table in ("facts", "analyses", "companies"):
                con.execute(f"DELETE FROM {table} WHERE cik = ?", [int(r.cik)])
            gone.append(r.ticker)
    return gone
