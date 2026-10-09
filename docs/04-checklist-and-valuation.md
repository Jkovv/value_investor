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

**The gate:** quality ≥ 70, coverage ≥ 60%, at least five years of history.
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

Next: **[05 Market regime](05-market-regime.md)**.
