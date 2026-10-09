"""ingest.py: filings, statements, prices and macro series for every market, into duckdb.

us companies come from sec edgar (10+ years of xbrl, plus 10-qs and form 4s).
everything else comes from yahoo finance (about five years and five quarters),
one home listing per company. re-running only fetches what can have changed.

  python ingest.py                          # the whole world
  python ingest.py --us                     # us companies only (edgar)
  python ingest.py --world                  # every other market
  python ingest.py --markets POL DEU JPN    # specific markets (iso-3 codes)
  python ingest.py --tickers KO AAPL        # specific us tickers
  python ingest.py --min-cap 2e9            # higher market-cap floor (usd, outside the us)
  python ingest.py --limit 30               # cap companies per market, for a quick look
  python ingest.py --insiders               # form 4s only, for ranked us companies
  python ingest.py --quarters               # quarters for stored non-us companies that lack them
  python ingest.py --macro-only             # rates, gdp, market cap / gdp, inflation
"""

import argparse

from value_investor import config, ingestion, insiders, macro, markets, store
from value_investor.logging_config import configure_logging


def insider_targets(con) -> list:
    """us companies that pass the gate."""
    return sorted(r[0] for r in con.execute(
        "SELECT a.cik FROM analyses a JOIN companies c USING (cik) WHERE a.passes_gate AND c.source = 'sec'").fetchall())


def refresh_insiders() -> None:
    with store.connect() as con:
        targets = insider_targets(con)
        if not targets:
            print("No ranked US companies yet; run main.py screen first, then ingest.py --insiders.")
            return
        print(f"Form 4s for {len(targets)} US companies...")
        counts = insiders.refresh(con, targets)
    print("  done:", ", ".join(f"{k} {v}" for k, v in counts.items() if v))


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--us", action="store_true", help="only us companies from edgar")
    parser.add_argument("--world", action="store_true", help="only non-us markets from yahoo finance")
    parser.add_argument("--markets", nargs="+", help="iso-3 market codes, e.g. POL DEU JPN (USA = edgar)")
    parser.add_argument("--tickers", nargs="+", help="specific us tickers")
    parser.add_argument("--min-cap", type=float, default=config.WORLD_MIN_CAP_USD,
                        help="market-cap floor in usd for non-us markets")
    parser.add_argument("--limit", type=int, help="cap companies per market")
    parser.add_argument("--refresh", action="store_true", help="refetch even when nothing new is expected")
    parser.add_argument("--insiders", action="store_true", help="only form 4s")
    parser.add_argument("--quarters", action="store_true", help="only quarters for stored non-us companies")
    parser.add_argument("--macro-only", action="store_true", help="skip companies, refresh macro series only")
    args = parser.parse_args()

    store.init()
    if args.insiders:
        config.check_sec_user_agent()
        refresh_insiders()
        return
    if args.quarters:
        with store.connect() as con:
            print(f"Quarters for {ingestion.world_quarters(con)} companies outside the US.")
        return

    print("Refreshing macro series (FRED, World Bank, benchmarks)...")
    with store.connect() as con:
        macro.refresh(con)
        markets.refresh(con)
    if args.macro_only:
        print("Ingestion complete.")
        return

    wanted = [m.upper() for m in args.markets] if args.markets else None
    do_us = bool(args.tickers) or args.us or (not args.world and (wanted is None or "USA" in wanted))
    do_world = not args.us and not args.tickers and (args.world or wanted is None or any(m != "USA" for m in wanted))

    if do_us:
        config.check_sec_user_agent()
        targets = ingestion.resolve(tickers=args.tickers, limit=args.limit)
        print(f"United States: {len(targets)} companies from EDGAR...")
        counts = ingestion.ingest(targets, refresh=args.refresh)
        print("  done:", ", ".join(f"{k} {v}" for k, v in counts.items() if v))
        with store.connect() as con:
            print(f"  industry labels from Yahoo for {ingestion.tag_industries(con)} companies")
        refresh_insiders()

    if do_world:
        iso3s = [m for m in (wanted or [m.iso3 for m in markets.MARKETS]) if m != "USA"]
        print(f"{len(iso3s)} markets outside the US from Yahoo Finance, floor ${args.min_cap:,.0f}...")
        counts = ingestion.ingest_world(iso3s, args.min_cap, args.limit, refresh=args.refresh)
        print("  done:", ", ".join(f"{k} {v}" for k, v in counts.items() if v))
        with store.connect() as con:
            ingestion.world_quarters(con)

    print("Ingestion complete.")


if __name__ == "__main__":
    main()
