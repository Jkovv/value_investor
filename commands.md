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
# A handful of companies, to try things out
python ingest.py --tickers KO PG MA AAPL MSFT

# The 400 largest, a good first real run (~1 minute)
python ingest.py --limit 400

# Everything on NYSE + Nasdaq (~25 minutes the first time, ~12 after)
python ingest.py

# Only refresh rates, GDP, VIX
python ingest.py --macro-only
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

## Dashboard

```bash
uvicorn app:app
# http://127.0.0.1:8000
```

## Tests

```bash
pytest
```
