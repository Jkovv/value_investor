"""ingest.py: pull filings and statements for every market, plus macro series, into DuckDB.

US companies come from SEC EDGAR (10+ years of XBRL). Everything else comes
from Yahoo Finance (about five years), one home listing per company. Both are
idempotent: a company is only refetched when something new can exist.

  python ingest.py                          # the whole world (US + every other market)
  python ingest.py --us                     # only US companies (EDGAR)
  python ingest.py --world                  # only non-US markets
  python ingest.py --markets POL DEU JPN    # specific markets (ISO-3 codes)
  python ingest.py --tickers KO AAPL        # specific US tickers
  python ingest.py --min-cap 2e9            # raise the market-cap floor (USD, non-US markets)
  python ingest.py --limit 30               # cap companies per market, for a quick look
  python ingest.py --macro-only             # rates, GDP, Market Cap / GDP, inflation
"""

import argparse

from value_investor import config, ingestion, macro, markets, store
from value_investor.logging_config import configure_logging


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--us", action="store_true", help="only US companies from EDGAR")
    parser.add_argument("--world", action="store_true", help="only non-US markets from Yahoo Finance")
    parser.add_argument("--markets", nargs="+", help="ISO-3 market codes, e.g. POL DEU JPN (USA = EDGAR)")
    parser.add_argument("--tickers", nargs="+", help="specific US tickers")
    parser.add_argument("--min-cap", type=float, default=config.WORLD_MIN_CAP_USD,
                        help="market-cap floor in USD for non-US markets")
    parser.add_argument("--limit", type=int, help="cap companies per market")
    parser.add_argument("--refresh", action="store_true", help="refetch even when nothing new is expected")
    parser.add_argument("--macro-only", action="store_true", help="skip companies, refresh macro series only")
    args = parser.parse_args()

    store.init()
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

    if do_world:
        iso3s = [m for m in (wanted or [m.iso3 for m in markets.MARKETS]) if m != "USA"]
        print(f"{len(iso3s)} markets outside the US from Yahoo Finance, floor ${args.min_cap:,.0f}...")
        counts = ingestion.ingest_world(iso3s, args.min_cap, args.limit, refresh=args.refresh)
        print("  done:", ", ".join(f"{k} {v}" for k, v in counts.items() if v))

    print("Ingestion complete.")


if __name__ == "__main__":
    main()
