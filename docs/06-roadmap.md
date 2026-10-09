# 06. Roadmap

## Backtest (next)

The engine already rebuilds statements as of any date. The backtest walks
forward a month at a time: score with what was public then, buy the top of
the ranking, hold, rebalance by the same rules, and compare with the S&P 500
and MSCI World, in PLN, after costs, the 19% capital gains tax and dividend
withholding.

Limits that will be stated on the results page, not buried:

- XBRL starts around 2009–2011, so ten-year checks only work from ~2020; a
  five-year variant runs from ~2015.
- Yahoo has no prices for delisted companies. Results come as a range:
  delisted-for-cause at −100% and acquisitions at the last price.
- Thresholds come from principles written down before 2010. They will not be
  tuned on the backtest; anything tuned gets a walk-forward split and a held-out period.
- The research agents can't be backtested (the model has read the future).
  Instead the app keeps a paper portfolio from today on.

## More markets

| Source | Covers | History |
|---|---|---|
| filings.xbrl.org (ESEF) | EU/EEA regulated markets + UK, incl. Warsaw main market | ~5 years, annual only |
| EDINET API v2 | Japan | ~10 years |
| OpenDART | Korea | ~10 years |
| yfinance | everything else, as a fallback | ~4 years |

The facts table already carries taxonomy and currency, and `concepts.py`
already maps `ifrs-full`.

## Research agents

Deep agents (planning, sub-agents, a scratch filesystem) on the shortlist
only, reading the 10-K's business, risk and MD&A sections through a local
index, insider transactions (Form 4), proxy statements and the news (Tavily,
DuckDuckGo fallback). Each company gets a report with sources: what the
advantage is and which of the three kinds, competitors, people running it,
opportunities against risks, and the questions from `principles.md` answered.
The model explains; it never computes a number.

## Portfolio

Positions in their own currencies, reported in PLN. ROI per position and
XIRR overall, dividends and FX split out. Sizing by expected return and
quality, capped per position and per cluster of related positions —
clusters from price correlation *and* shared sector, country, currency,
customers and suppliers. The behavioural guardrails in `principles.md` live
here: a written thesis before buying, a "did the thesis change or only the
price?" check before selling, a turnover warning.
