# 04. Checklist & valuation

## The checklist (`rules.py`)

Twenty checks, one per principle in `knowledge/principles.md`, grouped into
income statement, balance sheet and cash flow. Each lands on **pass**,
**watch**, **fail** or **no data**, and carries a weight.

- **Quality** = weighted points over the checks that could run (pass 1,
  watch ½, fail 0), 0-100.
- **Coverage** = the share of the checklist's weight that could run at all.

Keeping the two apart matters: a company with three years of data and a
perfect score is not the same as one with ten.

**The gate:** quality ≥ 70, coverage ≥ 60%, at least four years of history
(Yahoo gives four or five outside the US).
Only gate-passers get priced and ranked.

Banks, insurers, brokers and REITs (SIC 6000-6799) get a shorter list:
margins, leverage and capex describe industrial businesses and say little
about a balance sheet that *is* the product.

## The valuation (`valuation.py`)

The share is treated as a bond whose coupon is EPS, and the coupon grows.

| Step | Formula |
|---|---|
| Initial return | EPS / price, shown against the 10y Treasury |
| Growth *g* | min(smoothed 10y EPS growth, median ROE × (1 − payout)), clipped to 0-15% |
| EPS in year 10 | EPS × (1 + g)¹⁰ |
| P/E | average of each year's low / mean / high price over that year's EPS, last ten years, clipped to 5-35 |
| Value in year 10 | EPS₁₀ × P/E + dividends collected on the way |
| Expected return | (value₁₀ / price)^(1/10) − 1, for low / mid / high P/E |
| Buy below | value₁₀ (mid) / 1.15¹⁰ |
| Sell line | P/E today ≥ 40 |

The ranking sorts on the mid expected return. The low-to-high range is on the
company page; a wide range means the market has priced this company very
differently over the decade.

**Read the top of the ranking with suspicion.** A high expected return often
means the stock is cheap against its *own* past, which can be an
opportunity or a business whose best years are behind it. That question is
exactly what the research agents are for.

## Other lenses (`lenses.py`)

The checklist is one school. The **Lenses** tab on a company page shows the others, worked out from
the same statements and kept out of the quality score on purpose: when they disagree with the
checklist, that's the thing to look into.

| Lens | What it says | Read it as |
|---|---|---|
| Piotroski F-score | nine yes/no tests on the last two years: profitability, leverage, liquidity, dilution, margins, turnover | 7 to 9 strong, 4 to 6 average, 0 to 3 weak; tests without data are skipped and the score scaled to nine |
| Altman Z-score | 1.2 WC/TA + 1.4 RE/TA + 3.3 EBIT/TA + 0.6 MV/TL + 1.0 Sales/TA | above 3 safe, under 1.8 distress; fitted on manufacturers, not shown for financials |
| Graham | √(22.5 × EPS × BVPS) plus the defensive-investor tests over ten years | the most a defensive investor should pay |
| Owner-earnings DCF | three-year average owner earnings a share, growth fading to 2.5% by year ten, discounted at the bond yield + 5 points (at least 9%) | half or more of the value usually sits past year ten, so it's a range |
| Lynch | slow grower, stalwart, fast grower, cyclical or turnaround; PEG and dividend-adjusted PEG | PEG under 1 cheap for the growth, over 2 dear |
| Magic Formula | EBIT / enterprise value and EBIT / (net working capital + net fixed assets) | the ranking's **Magic #** column is the combined place on both among ranked companies |
| Dividend discount | today's dividend, growing at the slower of its own history and the projection, fading to 2.5%, same discount as the DCF | only fair to companies that pay out most of what they earn |
| Monte Carlo | the ten-year projection run 5,000 times, growth drawn around the projected rate and the exit P/E between the company's own historical low and high | the spread of yearly returns, the chance of reaching 15% and the chance of a loss |

The ranking also carries the **F-score** column, so both can be sorted on.

Next: **[05 Market regime](05-market-regime.md)**.
