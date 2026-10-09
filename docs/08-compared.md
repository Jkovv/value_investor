# 08. Compared with other projects

Other open-source projects cover parts of the same ground. This is what they do and where the same
thing lives here, or why it doesn't.

| Idea | Seen in | Here |
|---|---|---|
| One agent per famous investor, each giving a buy or sell signal | ai-hedge-fund | The same schools are computed, not role-played: Graham, Lynch, Piotroski, Greenblatt, Altman, an owner-earnings DCF, a dividend discount model and a Monte Carlo range on the **Lenses** tab. Agents then do the qualitative part from sources. |
| Analyst team: fundamentals, news | TradingAgents | Four deep agents per company: filings, competitors, demand trends (alternative data), web. |
| Bull researcher against bear researcher | TradingAgents, FinRobot | Every brief has a **Bull case and bear case** section and must say which one the evidence supports and what would change its mind. |
| Sourced equity research report | FinRobot | The **Research** tab: every claim numbered, the source list added by code rather than by the model. |
| Free-form questions about a ticker | FinRobot | The **Ask** box on the Research tab, answered by an agent with sources. |
| Comparable companies | FinRobot | The **Peers** tab: closest companies in the same industry from any market, with medians and where the company ranks. |
| Quarterly results | FinRobot | The **Quarters** tab: each quarter against a year earlier, trailing twelve months, a flag when the last two quarters slip. |
| Insider trades | TradingAgents | Form 4 for US companies: open-market buys and sells, planned sales marked, cluster buying flagged. |
| DCF, DDM, Monte Carlo | FinRobot | Owner-earnings DCF, dividend discount model and a 5,000-run Monte Carlo of the ten-year projection. |
| Piotroski, Altman, Graham, Magic Formula screens | open-source value screeners | **Lenses** tab per company; **F-score** and **Magic #** columns on the ranking, both sortable. |
| Checklist of a famous investor's rules | open-source value screeners | The full checklist from `knowledge/principles.md`, 20 checks (9 for financials), with the reason for each. |
| Decision log, paper trading, portfolio | ai-hedge-fund, TradingAgents | Left out on purpose. This finds and studies companies; what you buy and how much is yours to decide. |
| Resume an interrupted run | TradingAgents | Research saves after every stage and resumes from there. |
| Market valuation | rarely | Market Cap / GDP for 44 markets, each against its own trend, with a suggested cash share. |
| Coverage | TradingAgents covers several markets through Yahoo; most value screeners are US only | 44 markets, one home listing per company, returns in the currency each listing trades in. |
| Data and model cost | ai-hedge-fund and FinRobot use paid data APIs and hosted models; TradingAgents can run on free data and Ollama | Free: SEC EDGAR, Yahoo Finance, FRED, World Bank, Wikipedia, GDELT, a local model through Ollama, Groq and Hugging Face only as free fallbacks. |
| Backtest | ai-hedge-fund, TradingAgents | Parked on purpose. See [06 Roadmap](06-roadmap.md) for the limits a free backtest runs into. |
| Technical, sentiment and social-media analysts | TradingAgents | Left out on purpose. They answer "where will the price go next week", which this method doesn't ask. |
| Price targets, LBO, crypto | FinRobot, TradingAgents | Left out: a ten-year owner doesn't need a 12-month target, and the rest isn't investing in businesses. |

## What sets this one apart

- A checklist built for long-term ownership, with the quality score and the data coverage kept
  apart, so a perfect score on three years of data doesn't look like a perfect score on ten.
- Splits inferred from restated filings and share counts checked against reported EPS, so
  per-share history holds up where the raw XBRL doesn't. TradingAgents also serves filings as of
  a date; here every statement can be rebuilt as of any past date down to the line.
- A read of the market before a read of the company: the same business is a different buy when
  its market sits far above its own trend.

Next: back to **[01 Overview](01-overview.md)**.
