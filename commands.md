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

# Only insider trades (form 4) for ranked US companies and anything you hold
python ingest.py --insiders

# Quarters for stored companies outside the US that don't have them yet
python ingest.py --quarters
```

## Screening

```bash
# Score everything ingested, price the gate-passers, print the ranking,
# save a snapshot for the track record, refresh prices for what you hold
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
# http://127.0.0.1:8001: ranking, company pages, markets, portfolio, track record

# Showing it to other people: PUBLIC_DASHBOARD=true in .env turns off research runs,
# questions and the portfolio, so nobody else can spend your API credits or see your trades
```

## Tests

```bash
pytest
```
