# Value Investor

Finds businesses with a durable competitive advantage, prices what they'd
return over ten years at today's price, and ranks them. Everything runs
locally and costs nothing: filings come straight from SEC EDGAR, prices from
Yahoo Finance, macro series from FRED, and the research agents (next stage)
run on a local model through Ollama.

The rules it scores against are written out in
**[knowledge/principles.md](knowledge/principles.md)**.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate              # source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env              # then set SEC_USER_AGENT to your name + email

python ingest.py --tickers KO PG MA AAPL   # or no flags for every NYSE + Nasdaq company
python main.py screen                      # score, price the ones that pass, rank
uvicorn app:app                            # dashboard at http://127.0.0.1:8000
```

`.env` needs only `SEC_USER_AGENT`. `GROQ_API_KEY`, `HF_TOKEN` and
`TAVILY_API_KEY` are optional and only matter for the research agents.

## The scripts

| Command | What it does |
|---|---|
| `python ingest.py` | Pulls filings for every NYSE + Nasdaq company into `data/value_investor.duckdb`, plus FRED series. Skips companies with no new annual report, so re-runs are quick. `--tickers`, `--limit`, `--refresh`, `--macro-only`. |
| `python main.py screen` | Scores every ingested company; prices the ones that pass the gate and ranks them by expected return. `--tickers` to do a few (always priced). |
| `python main.py rank` | Prints the last ranking. `--all` includes companies below the gate. |
| `python main.py show KO` | Checklist, valuation steps and ten years of ratios for one company. |
| `python main.py macro` | Rates, the yield curve, Sahm rule and Market Cap / GDP with the suggested cash share. |
| `uvicorn app:app` | The dashboard: ranking, company pages, market page. |
| `python -m value_investor.llm` | Checks the model router (local Ollama first, then Groq / Hugging Face if keyed). |
| `pytest` | The test suite. |

## Documentation

Read `docs/` in order:

[01 Overview](docs/01-overview.md) ·
[02 Tech stack](docs/02-tech-stack.md) ·
[03 Data pipeline](docs/03-data-pipeline.md) ·
[04 Checklist & valuation](docs/04-checklist-and-valuation.md) ·
[05 Market regime](docs/05-market-regime.md) ·
[06 Roadmap](docs/06-roadmap.md)

Every command, in order: **[commands.md](commands.md)**.
