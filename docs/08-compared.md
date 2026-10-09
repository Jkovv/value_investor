# 08. Compared with other projects

Other open-source projects cover parts of the same ground. This is what they do and where the same
thing lives here, or why it doesn't.

| Idea | Seen in | Here |
|---|---|---|
| One agent per famous investor, each giving a buy or sell signal | ai-hedge-fund | The same schools are computed, not role-played: Graham, Lynch, Piotroski, Greenblatt, Altman and an owner-earnings DCF on the **Lenses** tab. Numbers from a formula can't be made up; one research agent then writes the qualitative part from sources. |
| Bull researcher against bear researcher | TradingAgents | Every research brief has a **Bull case and bear case** section and has to say which one the evidence supports and what would change its mind. |
| Sourced equity research report | FinRobot | The **Research** tab: annual report sections and the web, every claim numbered, the source list added by code rather than by the model. |
| Piotroski, Altman, Graham, Magic Formula screens | open-source value screeners | **Lenses** tab per company; **F-score** and **Magic #** columns on the ranking, both sortable. |
| Checklist of a famous investor's rules | open-source value screeners | The full checklist from `knowledge/principles.md`, 20 checks (9 for financials), with the reason for each. |
| DCF fair value | most screeners | Owner-earnings DCF, next to the ten-year equity-bond projection that drives the ranking. |
| Market valuation | rarely | Market Cap / GDP for 44 markets, each against its own trend, with a suggested cash share. |
| Coverage | mostly US only | 44 markets, one home listing per company, returns converted to one currency with purchasing-power parity. |
| Data and model cost | paid data APIs beyond a handful of tickers, paid LLMs | Free: SEC EDGAR, Yahoo Finance, FRED, World Bank, a local model through Ollama, Groq and Hugging Face only as free fallbacks. |
| Backtest | ai-hedge-fund | Parked on purpose, see [06 Roadmap](06-roadmap.md) for the limits a free backtest runs into. |
| Paper trading and portfolio | ai-hedge-fund | Roadmap: portfolio in several currencies with sizing that keeps positions independent. |
| Technical, sentiment and social-media analysts | TradingAgents | Left out on purpose. They answer "where will the price go next week", which this method doesn't ask. |
| Insider trades | some | Asked of the web researcher today; Form 4 parsing is on the roadmap. |

## What is only here

- Point-in-time statements: every number can be rebuilt as of any past date, so nothing leaks from
  the future once a backtest is added.
- Splits inferred from restated filings, share counts checked against reported EPS, so per-share
  history holds up where the raw XBRL doesn't.
- The quality score and the coverage score are kept apart, so a perfect score on three years of
  data doesn't look like a perfect score on ten.
- A read of the market before a read of the company: the same business is a different buy when
  its market sits far above its own trend.
