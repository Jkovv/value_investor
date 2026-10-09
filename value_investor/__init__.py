"""Value investor.

Modules are numbered in reading order, starting at config.py (01):

    01 config          settings and screening thresholds
    02 logging_config  console logging for the entry points
    03 http            rate-limited client for the SEC APIs
    04 store           DuckDB schema and reads/writes
    05 edgar           company list, profiles and XBRL facts from EDGAR
    06 concepts        XBRL concept -> canonical field mapping
    07 statements      facts -> annual statements, point-in-time
    08 prices          prices, dividends and splits (yfinance)
    09 macro           rates, Market Cap / GDP and the cash regime (FRED)
    10 metrics         yearly ratios and multi-year summary
    11 rules           the quality checklist and its score
    12 valuation       projected return, buy price, sell signal
    13 ingestion       EDGAR -> DuckDB, only what changed
    14 screener        one company end to end, and the ranking
    15 llm             model router: local Ollama, Groq / Hugging Face fallback
    16 tracing         optional LangSmith tracing
    17 fx              exchange rates and quote subunits (pence, cents, agorot)
    18 yahoo           every non-US market: universe, home listings, statements
    19 markets         44 markets, Market Cap / GDP each, inflation and bond yields
    20 research_tools  what the research agents may read
    21 prompts         the agents' briefs
    22 research        the deep research agent

Entry points live at the repo root: ingest.py, main.py, research.py, app.py.
"""
