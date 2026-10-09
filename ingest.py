"""ingest.py — pull filings (EDGAR) and macro series (FRED) into DuckDB.

Idempotent: companies with no new annual report since the last run are
skipped, so re-running over the whole market only fetches what changed.

  python ingest.py                     # every NYSE + Nasdaq company (~25 min the first time)
  python ingest.py --tickers KO AAPL   # just these
  python ingest.py --limit 300         # first 300 of the listed universe
  python ingest.py --refresh           # refetch even if nothing new was filed
  python ingest.py --macro-only        # only rates, GDP, market cap, VIX
"""

import argparse

from value_investor import config, ingestion, macro, store
from value_investor.logging_config import configure_logging


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", nargs="+", help="only these tickers")
    parser.add_argument("--exchanges", nargs="+", default=list(config.DEFAULT_EXCHANGES))
    parser.add_argument("--limit", type=int, help="cap the number of companies")
    parser.add_argument("--refresh", action="store_true", help="refetch facts even when unchanged")
    parser.add_argument("--macro-only", action="store_true", help="skip companies, refresh FRED series only")
    args = parser.parse_args()

    store.init()
    if not args.macro_only:
        config.check_sec_user_agent()
        targets = ingestion.resolve(tickers=args.tickers, exchanges=args.exchanges, limit=args.limit)
        print(f"Ingesting {len(targets)} companies from EDGAR...")
        counts = ingestion.ingest(targets, refresh=args.refresh)
        print("Done:", ", ".join(f"{k} {v}" for k, v in counts.items() if v))

    print("Refreshing macro series from FRED...")
    with store.connect() as con:
        macro.refresh(con)
    print("Ingestion complete.")


if __name__ == "__main__":
    main()
