"""value investor. modules are numbered in reading order:

    01 config          settings and thresholds
    02 logging_config  console logging
    03 http            rate-limited client for the sec apis
    04 store           duckdb schema, reads and writes
    05 edgar           company list, profiles and xbrl facts
    06 concepts        xbrl tag -> statement line
    07 statements      facts -> annual statements, point in time
    08 prices          prices, dividends, splits
    09 macro           us rates and Market Cap / GDP
    10 metrics         yearly ratios and the ten-year summary
    11 rules           the quality checklist and its score
    12 valuation       expected return, buy price, sell signal
    13 ingestion       edgar and yahoo into duckdb
    14 screener        one company end to end, and the ranking
    15 llm             model router: ollama first, groq and hugging face after
    16 tracing         optional langsmith tracing
    17 fx              exchange rates and quote subunits
    18 yahoo           every market outside the us
    19 markets         44 markets, Market Cap / GDP each
    20 research_tools  what the agents may read
    21 prompts         the agents' briefs
    22 research        the deep agents, and questions
    23 lenses          Piotroski, Altman, Graham, Lynch, Magic Formula, dcf, ddm, Monte Carlo
    24 quarterly       the last quarters against a year earlier
    25 insiders        form 4 buys and sells
    26 peers           the closest companies in the same industry

entry points sit at the repo root: ingest.py, main.py, research.py, app.py.
"""
