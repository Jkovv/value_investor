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

## Portfolio, next steps

Positions, returns in PLN, XIRR, dividends, currency effect and a sizing plan are in (see
[09 Portfolio and track record](09-portfolio-and-track-record.md)). Still to come: clusters that
also use shared customers and suppliers, and the behavioural guardrails from `principles.md`: a
written thesis before buying, a "did the thesis change or only the price?" check before selling,
a turnover warning.

## Alerts

A scheduled run (ingest, screen, then a short digest of what entered or left the buy zone, new
sell signals, new insider buying). Insider trades themselves are in: US only, since EDGAR is the
one free and complete source.

## Backtest (parked)

The engine can rebuild statements as of any date, so a backtest is possible for US companies
(XBRL from ~2009). Parked for now. When it comes back, three limits apply: free price data has no
delisted companies (survivorship bias, so results come as a range), XBRL history makes ten-year
checks possible only from ~2020, and the agents can't be backtested honestly because the model has
read the future; a paper portfolio from today on is the fair test for them.

Next: **[07 Research agents](07-research-agents.md)**.
