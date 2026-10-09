# Value Investor

Finds businesses with a durable competitive advantage in 44 stock markets, prices what they'd
return over ten years at today's price, ranks them in one currency, and sends a research agent to
read up on the ones worth a closer look. Everything runs locally and costs nothing: filings come
from SEC EDGAR, statements for the rest of the world and prices from Yahoo Finance, macro series
from FRED and the World Bank, and the agents run on a local model through Ollama.

The rules it scores against are written out in **[knowledge/principles.md](knowledge/principles.md)**.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate              # source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env              # then set SEC_USER_AGENT to your name + email
ollama pull qwen3:8b                # for the research agents

python ingest.py --markets USA POL DEU JPN --limit 50   # a quick taste
python main.py screen                                   # score, price the ones that pass, rank
uvicorn app:app                                         # dashboard at http://127.0.0.1:8000
python research.py --top 3                              # research briefs for the top three
```

`.env` needs only `SEC_USER_AGENT`. `GROQ_API_KEY`, `HF_TOKEN` and `TAVILY_API_KEY` are optional
and only matter for the research agents.

## The scripts

| Command | What it does |
|---|---|
| `python ingest.py` | Every market: US companies from EDGAR, every other market from Yahoo Finance (one home listing per company, above a $1B floor), plus FRED, World Bank and benchmark series. Only fetches what can have changed. `--us`, `--world`, `--markets`, `--tickers`, `--min-cap`, `--limit`, `--refresh`, `--macro-only`. |
| `python main.py screen` | Scores every ingested company, prices the ones that pass the gate and ranks them by expected return in your base currency. |
| `python main.py rank` | Prints the last ranking. `--all` includes companies below the gate. |
| `python main.py show KO` | Checklist, valuation steps and ten years of ratios for one company. |
| `python main.py macro` | US rates, the yield curve, Sahm rule and Market Cap / GDP. |
| `python research.py KO` | Deep research agent: reads the annual report and the web, writes a sourced brief. `--top N` for the top of the ranking. |
| `uvicorn app:app` | The dashboard: ranking, company pages with a Research tab, all markets. |
| `python -m value_investor.llm` | Checks the model router (local Ollama first, then Groq / Hugging Face if keyed). |
| `pytest` | The test suite. |

## Documentation

Read `docs/` in order:

[01 Overview](docs/01-overview.md) ·
[02 Tech stack](docs/02-tech-stack.md) ·
[03 Data pipeline](docs/03-data-pipeline.md) ·
[04 Checklist & valuation](docs/04-checklist-and-valuation.md) ·
[05 Markets](docs/05-market-regime.md) ·
[06 Roadmap](docs/06-roadmap.md) ·
[07 Research agents](docs/07-research-agents.md)

Every command, in order: **[commands.md](commands.md)**.
