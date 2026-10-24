# Commands

Every command, in the order you'd run them. Windows paths; swap
`.venv\Scripts\` for `.venv/bin/` elsewhere.

## Setup

```bash
# Virtual environment and dependencies
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Settings: at minimum SEC_USER_AGENT="Your Name your@email.com"
copy .env.example .env
```

## Local model (for the research agents)

```bash
# Install Ollama from ollama.com, then pull the default model (~5 GB)
ollama pull qwen3:8b

# Check the router: prints the backends in order and one reply
python -m value_investor.llm
```

## Data

```bash
# A handful of US companies, to try things out
python ingest.py --tickers KO PG MA AAPL MSFT

# A quick look at a few markets: the 50 largest companies in each
python ingest.py --markets USA POL DEU JPN IND --limit 50

# Only US companies (EDGAR; ~25 minutes the first time, ~12 after)
python ingest.py --us

# Every market outside the US above $1B (Yahoo Finance; a few hours the first time,
# runs politely in the background and only refetches after 30 days)
python ingest.py --world

# Smaller companies too
python ingest.py --world --min-cap 3e8

# Everything
python ingest.py

# Only macro: FRED, World Bank, benchmarks, FX
python ingest.py --macro-only

# Only insider trades (form 4) for ranked US companies
python ingest.py --insiders

# Quarters for stored companies outside the US that don't have them yet
python ingest.py --quarters

# Only the ten-year histories: China, Hong Kong, Taiwan, India and Brazil from their own
# sources, then SEC filings of foreign companies (refetched after 30 days; --refresh forces it)
python ingest.py --history
```

## Screening

```bash
# Score everything ingested, price the gate-passers, print the ranking
python main.py screen

# Just a few, always priced
python main.py screen --tickers KO PG MA

# Last ranking, optionally including companies below the gate
python main.py rank --top 50
python main.py rank --all

# One company in detail
python main.py show KO

# Market regime
python main.py macro
```

## Watchlist

```bash
# Star a company on its page, then: fresh prices for the starred ones and what changed since last time
python main.py digest
python main.py digest --no-refresh    # from the stored prices, fetching nothing

# Every Monday at 8 on Windows (Task Scheduler), with the paths of this folder
schtasks /Create /SC WEEKLY /D MON /ST 08:00 /TN "Value Investor digest" ^
  /TR "C:\path\to\value_investor\.venv\Scripts\python.exe C:\path\to\value_investor\main.py digest"
```

## Checking the work

```bash
# How often each history source agrees with Yahoo Finance, line by line (also on /data)
python main.py audit

# Every company scored again each June since 2010 with only what was known then, against
# what its shares returned next; charts land in docs/img (an hour or two on a laptop)
python main.py study
python main.py study --reuse          # redo the statistics on the last scored panel

# The research briefs, sentence by sentence against their sources (needs GROQ_API_KEY for
# the judge; carries on the next day if the free daily limit runs out)
python main.py evals
python main.py evals --sample 60      # also write 60 sentences to mark by hand
```

## Research

```bash
# A brief for one company (tens of minutes on the local model)
python research.py KO

# The top five of the ranking, one after another
python research.py --top 5

# A run that stopped (laptop asleep, server restarted) resumes on the next run
# of the same ticker; the dashboard offers Resume or Start over

# Much faster with Groq: set GROQ_API_KEY and LLM_PRIMARY=groq in .env
```

Questions about a company are asked on its Research tab.

## Dashboard

```bash
uvicorn app:app --port 8001
# http://127.0.0.1:8001: ranking, research, watchlist, company pages, markets, data

# Showing it to other people: PUBLIC_DASHBOARD=true in .env turns off research runs
# and questions, so nobody else can spend your API credits
```

## Tests

```bash
pytest
```
