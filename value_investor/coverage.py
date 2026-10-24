"""coverage: how many analysts follow a company, and how much of it funds hold.

yahoo's quote summary has both for any listing. a company no analyst covers and few
funds own is one nobody is paid to look at, and its price is set by fewer people.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import duckdb
import pandas as pd
import yfinance as yf

from value_investor import store

logger = logging.getLogger(__name__)

FEW = 3                 # this many analysts or fewer counts as barely covered
THREADS = 4
GAP = 0.3               # seconds between calls, per thread
PAUSE = 120             # seconds to back off when yahoo starts refusing
MAX_AGE = timedelta(days=30)


def quoted_where_followed(symbol: str) -> str:
    """the listing yahoo keeps estimates on: cboe's copy of a london line (TRNL.XC) has none."""
    if symbol.endswith("L.XC"):
        return symbol[:-4] + ".L"
    return symbol


def reading(info: dict) -> "dict | None":
    if not info.get("marketCap") and not info.get("regularMarketPrice"):
        return None
    # yahoo leaves the field out when nobody publishes estimates
    analysts = int(info.get("numberOfAnalystOpinions") or 0)
    institutions = info.get("heldPercentInstitutions")
    if analysts == 0 and (institutions or 0) >= 0.5:
        analysts = None     # funds own most of it: the estimates sit on another listing, not nowhere
    return {"analysts": analysts, "institutions": institutions, "insiders": info.get("heldPercentInsiders")}


def fetch(symbol: str) -> "dict | None":
    try:
        info = yf.Ticker(quoted_where_followed(symbol)).info or {}
    except Exception as exc:
        logger.debug("no quote summary for %s: %s", symbol, exc)
        return None
    return reading(info)


def stale(con) -> list:
    """(cik, ticker) of analysed companies with no reading, or one older than a month."""
    cutoff = datetime.now() - MAX_AGE
    return con.execute(
        "SELECT a.cik, a.ticker FROM analyses a LEFT JOIN coverage c USING (cik) "
        "WHERE a.ticker IS NOT NULL AND (c.fetched_at IS NULL OR c.fetched_at < ?) "
        "ORDER BY a.passes_gate DESC, a.cik", [cutoff]).fetchall()


def _write(rows: list) -> None:
    # short connections, so the dashboard and running briefs can still read in between;
    # if one of them has the file open right now, wait for it
    for _ in range(60):
        try:
            with store.connect() as con:
                for r in rows:
                    con.execute("DELETE FROM coverage WHERE cik = ?", [r["cik"]])
                    con.execute("INSERT INTO coverage VALUES (?, ?, ?, ?, now())",
                                [r["cik"], r["analysts"], r["institutions"], r["insiders"]])
            return
        except duckdb.IOException:
            time.sleep(2)
    raise RuntimeError("the database stayed busy for two minutes")


def refresh(targets: list) -> dict:
    resume_at = [0.0]

    def one(cik, ticker):
        time.sleep(max(GAP, resume_at[0] - time.monotonic()))
        return cik, ticker, fetch(ticker)

    counts, batch, misses = {"read": 0, "missing": 0}, [], 0
    with ThreadPoolExecutor(THREADS) as pool:
        for future in as_completed([pool.submit(one, cik, t) for cik, t in targets]):
            cik, ticker, got = future.result()
            if got is None:
                counts["missing"] += 1
                misses += 1
                if misses >= 10:        # yahoo is turning us away, not ten dead tickers in a row
                    resume_at[0] = time.monotonic() + PAUSE
                    misses = 0
                continue
            misses = 0
            batch.append({"cik": cik, **got})
            counts["read"] += 1
            if len(batch) >= 250:
                _write(batch)
                batch = []
                logger.info("coverage for %d of %d", counts["read"] + counts["missing"], len(targets))
    if batch:
        _write(batch)
    return counts


def load(con) -> pd.DataFrame:
    try:
        return con.execute("SELECT cik, analysts, institutions, insiders FROM coverage").df()
    except duckdb.CatalogException:     # a database from before coverage was kept, opened read-only
        return pd.DataFrame(columns=["cik", "analysts", "institutions", "insiders"])


def one(con, cik: int) -> "dict | None":
    try:
        row = con.execute("SELECT analysts, institutions, insiders FROM coverage WHERE cik = ?", [cik]).fetchone()
    except duckdb.CatalogException:
        return None
    return None if row is None else {"analysts": row[0], "institutions": row[1], "insiders": row[2]}


def off_radar(df: pd.DataFrame, few: int = FEW) -> pd.DataFrame:
    """companies that pass the checklist, have a price, and that few or no analysts follow."""
    keep = df["passes_gate"] & df["expected_return"].notna() & df["analysts"].notna() & (df["analysts"] <= few)
    return df[keep].sort_values("expected_return", ascending=False)


def by_market(df: pd.DataFrame, few: int = FEW, least: int = 10) -> list:
    """per market: analysts on the usual company, the share with none, and the good ones nobody follows.
    thinnest coverage first."""
    read = df[df["analysts"].notna()]
    radar = off_radar(read, few)
    out = []
    for market, g in read.groupby("market"):
        if len(g) < least:
            continue
        found = radar[radar["market"] == market]
        out.append({"market": market, "companies": len(g), "median": float(g["analysts"].median()),
                    "none": float((g["analysts"] == 0).mean()), "off_radar": len(found),
                    "best": float(found["expected_return"].iloc[0]) if len(found) else None})
    return sorted(out, key=lambda r: (r["median"], -r["none"]))
