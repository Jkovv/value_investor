# 05. Market regime

Market Cap / GDP answers one question: **how much cash should be on hand?**
It never decides which company to buy.

## Why not a fixed threshold

The ratio has drifted upward for decades — more profits earned abroad by US
companies, lower rates for most of the period. Against a fixed "overvalued
above 140%" line, the market has looked overvalued for most of the last ten
years, and a rule built on that line would have sat in cash through one of
the best decades on record.

So `macro.py` fits a straight line to the *log* of the ratio since 1947 and
measures how many standard deviations today sits above or below it:

| Distance from trend | Regime | Suggested cash |
|---|---|---|
| below −1.0 σ | cheap | 0% |
| −1.0 to +0.5 σ | fair | 10% |
| +0.5 to +1.5 σ | expensive | 20% |
| above +1.5 σ | very expensive | 35% |

## Inputs

- **Corporate equities** (FRED `NCBEILQ027S`, Fed Z.1) over **GDP** (`GDP`).
  Z.1 is a quarter-end level published with a lag, so the latest value is
  rolled forward with the S&P 500's move since that quarter ended.
- **10y − 2y Treasury spread** — an inverted curve preceded most US recessions.
- **Sahm rule** — the 3-month average unemployment rate against its low of
  the previous 12 months; 0.50 or more has marked the start of recessions.
- **VIX** — spikes near 30 have historically been better moments to buy than to sell.

The cash bands are a starting point. The backtest stage will check them on
index data back to the late 1940s before anything relies on them.

Next: **[06 — Roadmap](06-roadmap.md)**.
