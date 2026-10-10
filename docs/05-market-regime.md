# 05. Markets

Market Cap / GDP answers one question per market: **how much cash should be on hand there?**
It never decides which company to buy.

## Every market against its own trend

Levels can't be compared across countries. Hong Kong sits above 1,000% and Switzerland above 200%
because of who chooses to list there, not because they are always expensive; Germany sits low
because many large German companies are family or state owned. So `markets.py` reads each market
only against itself: it fits a straight line to the *log* of that market's own history and measures
how many standard deviations today is above or below it.

| Distance from own trend | Reading | Suggested cash |
|---|---|---|
| below −1.0 σ | cheap | 0% |
| −1.0 to +0.5 σ | fair | 10% |
| +0.5 to +1.5 σ | expensive | 20% |
| above +1.5 σ | very expensive | 35% |

## Where the numbers come from

- **United States:** the Fed's Z.1 corporate equities over GDP (FRED), quarterly since 1947, rolled
  forward with the S&P 500 since the last quarter end.
- **The other 49 markets:** the World Bank's *market capitalization of listed domestic companies
  (% of GDP)*, annual. The last annual point is rolled forward to today with the local benchmark
  index (or a country ETF converted to local currency where Yahoo has no index: Poland's WIG20 ETF,
  and US-listed country ETFs for Chile, Saudi Arabia, Thailand, the Philippines and Vietnam) and
  divided by nominal GDP growth since then.

Each reading carries a confidence label shown in the dashboard:

| Label | Meaning |
|---|---|
| current | last World Bank figure is at most two years old |
| since 20xx, rolled | two to five years old, rolled forward |
| since 20xx, rough | the World Bank stopped publishing for this market years ago (France, Italy, the Netherlands, Belgium, Ireland, Portugal, Norway); rolled forward a long way |
| stale | old and nothing to roll it forward with (Sweden, Denmark, Finland) |

Taiwan, Iceland, Estonia and Lithuania have no World Bank series at all and show as missing; their
companies are still screened.

## Also on the page

- Local **10-year government bond yields** from the OECD series on FRED where they exist; they're
  the bar a company's earnings yield is compared against on its own page.
- US **yield curve** (10y less 2y), **Sahm rule** and **VIX**.

Next: **[06 Roadmap](06-roadmap.md)**.
