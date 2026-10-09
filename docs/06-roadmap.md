# 06. Roadmap

## Deeper history outside the US

Yahoo gives every market four to five years. Official XBRL sources can add depth market by market,
feeding the same facts table:

| Source | Covers | History | Needs |
|---|---|---|---|
| filings.xbrl.org (ESEF) | EU/EEA regulated markets + UK, including Warsaw | from FY2020, annual | nothing |
| EDINET API v2 | Japan | ~10 years | a free key (phone verification) |
| OpenDART | Korea | ~10 years | a free key |

`concepts.py` already maps `ifrs-full`, which ESEF uses.

## Portfolio

Positions in their own currencies, reported in PLN. ROI per position and XIRR overall, dividends
and FX split out. Sizing by expected return and quality, capped per position and per cluster of
related positions; clusters from price correlation *and* shared sector, country, currency,
customers and suppliers. The suggested cash share per market from the Markets page feeds the
overall cash level. The behavioural guardrails in `principles.md` live here: a written thesis
before buying, a "did the thesis change or only the price?" check before selling, a turnover warning.

## Insider trades and alerts

Form 4 filings from EDGAR give every insider purchase and sale for US companies, free; open-market
buying by several insiders at once is one of the good signs in `principles.md`. Next to it, a
scheduled run (ingest, screen, then a short digest of what entered or left the buy zone and any
new sell signals).

## Backtest (parked)

The engine can rebuild statements as of any date, so a backtest is possible for US companies
(XBRL from ~2009). Parked for now. When it comes back, three limits apply: free price data has no
delisted companies (survivorship bias, so results come as a range), XBRL history makes ten-year
checks possible only from ~2020, and the agents can't be backtested honestly because the model has
read the future; a paper portfolio from today on is the fair test for them.

Next: **[07 Research agents](07-research-agents.md)**.
