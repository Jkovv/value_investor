"""research.py: run the deep research agent on one or more companies.

  python research.py KO                 # one company
  python research.py PKN.WA ASML.AS     # several, one after another
  python research.py --top 5            # the top five of the current ranking

on the local model a brief takes a while (think tens of minutes on a laptop);
with GROQ_API_KEY set and LLM_PRIMARY=groq it takes a few minutes.
reports land in data/research/<TICKER>.md and show up on the company page.
"""

import argparse

from value_investor import llm, research, screener, store
from value_investor.logging_config import configure_logging


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("tickers", nargs="*")
    parser.add_argument("--top", type=int, help="research the top N of the ranking")
    args = parser.parse_args()

    tickers = [t.upper() for t in args.tickers]
    names = {}
    with store.connect(read_only=True) as con:
        if args.top:
            ranked = screener.ranking(con).head(args.top)
            tickers += ranked["ticker"].tolist()
        for t in tickers:
            cik = store.find_cik(con, t)
            names[t] = (store.company(con, cik) or {}).get("name") if cik else None
    if not tickers:
        parser.error("give tickers or --top N")

    print("Model backends, in order:", ", ".join(llm.backends()))
    for t in tickers:
        if names.get(t) is None:
            print(f"{t}: not in the database, skipping (run ingest.py and main.py screen first)")
            continue
        print(f"Researching {names[t]} ({t})...")
        text = research.run(t, names[t])
        if text:
            print(f"  done: {research.report_path(t)}")
        else:
            print(f"  failed: {(research.status(t) or {}).get('error')}")


if __name__ == "__main__":
    main()
