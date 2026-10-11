"""13 · ingestion: edgar and yahoo into duckdb.

threads fetch, the main thread writes. a company is refetched only when it
has filed something new, so re-running over the whole market is cheap.
"""

import logging
import random
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from value_investor import brazil, china, config, edgar, fx, hongkong, india, markets, poland, store, taiwan, yahoo
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


def _fetch(cik: int, known: tuple, refresh: bool):
    prof = edgar.profile(cik)
    if not prof["last_annual_filed"]:
        return prof, None, "no annual report"
    latest = (str(prof["last_annual_filed"]), str(prof["last_quarter_filed"]))
    if not refresh and known == latest:
        return prof, None, "unchanged"
    return prof, edgar.company_facts(cik), "fetched"


def ingest(targets: pd.DataFrame, refresh: bool = False, workers: int = config.SEC_WORKERS) -> dict:
    counts = {"fetched": 0, "unchanged": 0, "no annual report": 0, "no facts": 0, "failed": 0}
    with store.connect() as con:
        known = {int(r.cik): (str(r.last_annual_filed), str(r.last_quarter_filed))
                 for r in store.companies(con).itertuples()}
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
                prof.update(source="sec", market="USA", price_currency="USD")
                existing = store.company(con, cik) or {}
                # keep what yahoo told us about the business; edgar only has the sic code
                for key in ("sector", "industry", "summary", "market_cap"):
                    prof[key] = existing.get(key) if _known(existing.get(key)) else None
                if not _known(existing.get("industry")):
                    prof["sector"] = prof.get("sic_description")
                if outcome == "fetched":
                    annual, quarterly = facts
                    prof["currency"] = edgar.reporting_currency(annual)
                    store.upsert_company(con, prof)
                    store.replace_facts(con, cik, annual)
                    store.replace_quarterly_facts(con, cik, quarterly)
                elif outcome == "unchanged":
                    prof["currency"] = existing.get("currency")
                    store.upsert_company(con, prof)
                counts[outcome] += 1
                if done % 100 == 0 or done == len(futures):
                    logger.info("%d / %d companies  %s", done, len(futures), counts)
    return counts


def _known(v) -> bool:
    return v is not None and not (isinstance(v, float) and v != v)


def tag_industries(con, workers: int = 4) -> int:
    """sector and industry from yahoo for sec filers, so peers can be matched across markets."""
    todo = con.execute("SELECT cik, ticker FROM companies WHERE source = 'sec' AND industry IS NULL "
                       "AND ticker IS NOT NULL").fetchall()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(yahoo.profile, ticker): cik for cik, ticker in todo}
        for fut in as_completed(futures):
            try:
                prof = fut.result()
            except Exception as exc:
                logger.debug("no yahoo profile for CIK %s: %s", futures[fut], exc)
                continue
            if not prof.get("industry"):
                continue
            con.execute("UPDATE companies SET sector = ?, industry = ?, summary = coalesce(summary, ?), "
                        "market_cap = ? WHERE cik = ?",
                        [prof["sector"], prof["industry"], prof.get("summary"), prof.get("market_cap"),
                         futures[fut]])
            done += 1
    return done


WORLD_REFRESH = timedelta(days=30)


def _fetch_yahoo(symbol: str, market: str):
    time.sleep(random.uniform(0.2, 0.8))
    return yahoo.fundamentals(symbol, market)


def ingest_world(iso3s: list, min_cap_usd: float, limit_per_market: "int | None" = None,
                 refresh: bool = False, workers: int = 3) -> dict:
    """every company above the floor in the given markets, one listing each."""
    counts = {"fetched": 0, "fresh": 0, "foreign listing": 0, "no statements": 0, "failed": 0}
    with store.connect() as con:
        listings = yahoo.universe(con, iso3s, min_cap_usd, limit_per_market)
        if "CHN" in iso3s and not limit_per_market:
            listings = _add_missing_china(con, listings, min_cap_usd)
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
                    facts, prof, quarterly = fut.result()
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
                store.replace_quarterly_facts(con, prof["cik"], quarterly)
                counts["fetched"] += 1
                if done % 50 == 0 or done == len(futures):
                    logger.info("%d / %d  %s", done, len(futures), counts)
        pruned = prune_foreign(con)
        if pruned:
            logger.info("dropped %d listings that belong to other markets", len(pruned))
    return counts


def _add_missing_china(con, listings: pd.DataFrame, min_cap_usd: float) -> pd.DataFrame:
    """a-shares yahoo's screener leaves out, from eastmoney's full list."""
    try:
        full = china.universe(min_cap_usd * (fx.rate(con, "USD", "CNY") or 7.2))
    except Exception as exc:
        logger.warning("eastmoney a-share list failed: %s", exc)
        return listings
    have = set(listings["symbol"]) if not listings.empty else set()
    extra = full[~full["symbol"].isin(have)]
    if extra.empty:
        return listings
    logger.info("China: %d a-shares the yahoo screener missed", len(extra))
    extra = extra.assign(name=None, exchange=extra["symbol"].str[-2:].map({"SS": "Shanghai", "SZ": "Shenzhen", "BJ": "Beijing"}),
                         currency="CNY", financial_currency="CNY", board=extra["symbol"], turnover=0.0, market="CHN",
                         market_code="cn_market")
    return pd.concat([listings, extra[[c for c in listings.columns if c in extra.columns]]], ignore_index=True)


def prune_foreign(con) -> list:
    """drop stored Yahoo listings that the current rules say belong to another market."""
    gone = []
    for r in store.companies(con).itertuples():
        if r.source != "yahoo" or r.market not in markets.BY_ISO:
            continue
        local = markets.BY_ISO[r.market].currency
        quote = fx.major(r.price_currency)[0]
        foreign_currency = (r.currency not in ("USD", "EUR", local) and r.currency in {m.currency for m in markets.MARKETS}
                            and (r.market, r.currency) not in yahoo.OWN_FOREIGN_CURRENCY)
        wrong_market = quote != local and r.currency != local
        moved = yahoo.home_elsewhere({"country": r.country, "financialCurrency": r.currency}, r.market)
        if foreign_currency or wrong_market or moved:
            for table in ("facts", "quarterly_facts", "analyses", "companies"):
                con.execute(f"DELETE FROM {table} WHERE cik = ?", [int(r.cik)])
            gone.append(r.ticker)
    return gone


def world_quarters(con, workers: int = 3) -> int:
    """quarterly statements for stored yahoo companies that have none yet."""
    todo = con.execute("SELECT ticker, cik FROM companies c WHERE source = 'yahoo' AND NOT EXISTS "
                       "(SELECT 1 FROM quarterly_facts q WHERE q.cik = c.cik)").fetchall()
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(yahoo.quarterly, ticker): cik for ticker, cik in todo}
        for fut in as_completed(futures):
            try:
                frame = fut.result()
            except Exception as exc:
                logger.warning("quarters failed for CIK %s: %s", futures[fut], exc)
                continue
            if not frame.empty:
                store.replace_quarterly_facts(con, futures[fut], frame)
                done += 1
    return done


# sources with a longer history than yahoo's four years, and the markets they cover
# source: (fetch for one ticker, markets, threads, check against what's stored or None)
HISTORY_SOURCES = {
    "eastmoney": (china.statements, ("CHN",), 4, None),
    "finmind": (taiwan.statements, ("TWN",), 2, None),       # paced inside; more threads wouldn't help
    "screener": (india.statements, ("IND",), 2, None),
    "eastmoney-hk": (hongkong.statements, ("HKG",), 4, hongkong.settle),
    "cvm": (brazil.statements, ("BRA",), 4, None),
    "biznesradar": (poland.statements, ("POL",), 1, poland.agrees),      # paced inside
}
HISTORY_REFRESH = timedelta(days=30)


def extend_history(con, source: str, refresh: bool = False, tickers=None) -> dict:
    """ten years of statements from a market's own free source, stored next to yahoo's."""
    fetch, covered, workers, check = HISTORY_SOURCES[source]
    done = store.fetched(con, source)
    rows = con.execute(f"SELECT cik, ticker FROM companies WHERE source = 'yahoo' AND market IN "
                       f"({', '.join('?' * len(covered))})", list(covered)).fetchall()
    if tickers:
        rows = [r for r in rows if r[1] in set(tickers)]
    now = datetime.now()
    todo = [(cik, t) for cik, t in rows if refresh or cik not in done or now - done[cik] > HISTORY_REFRESH]
    counts = {"companies": len(rows), "fresh": len(rows) - len(todo), "fetched": 0, "empty": 0, "failed": 0}
    logger.info("%s: %d companies, %d to fetch", source, len(rows), len(todo))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, ticker): (cik, ticker) for cik, ticker in todo}
        for i, fut in enumerate(as_completed(futures), start=1):
            cik, ticker = futures[fut]
            try:
                facts = fut.result()
                if check is not None:
                    facts = check(con, cik, facts)
            except Exception as exc:
                logger.warning("%s failed for %s: %s", source, ticker, exc)
                counts["failed"] += 1
                continue
            years = int(facts["period_end"].nunique()) if not facts.empty else 0
            if years:
                store.replace_facts(con, cik, facts, taxonomies=[source])
                counts["fetched"] += 1
            else:
                counts["empty"] += 1
            store.mark_fetched(con, cik, source, years)
            if i % 100 == 0 or i == len(futures):
                logger.info("%s: %d / %d  %s", source, i, len(futures), counts)
    return counts
