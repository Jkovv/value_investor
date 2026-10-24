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

Two more things keep a company out of the ranking. Funds and trusts (investment trusts, closed-end
funds, physical metal trusts) are scored but not ranked: their earnings are gains on what they
hold, so a checklist for operating businesses says nothing about them. And a P/E under 3 on a
company that passes the checklist is treated as bad data (a mislabelled statement currency or a
broken share count), so it gets no valuation.

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

## What the price assumes

The ten-year projection run backwards (`valuation.implied_growth`): the yearly EPS growth today's
price needs to return 15% a year, with the same exit P/E and dividends. It sits on the company page
next to the growth of the last decade and the growth the projection used:

- needed below what the projection uses: room for things to go worse than planned;
- needed within the last decade's growth: the business has to keep its best pace;
- needed above the last decade's growth: the price is a bet on a better decade than the last.

The sum is per unit of price, so the currency drops out and it works for every listing.

## Moat (`moat.py`)

The books sort durable advantages three ways, and each leaves its own mark on ten years of
statements:

| Kind | What it is | What the numbers show |
|---|---|---|
| Unique product | people come back for it and pay up: a brand | gross margin of 40% or more, moving less than 5 points, net margin of 10% or more, no loss years |
| Unique service | others can't easily do without it: a toll bridge | no cost of sales filed, operating margin of 25% or more and steady, capex under half of earnings |
| Low-cost operator | buys and sells cheaper than anyone, year after year | a thin margin that moves less than 3 points, ROE above 15% in 80% of years, EPS up in 70%, fast asset turnover |
| None | | none of the above: margins that swing, loss years, capex that eats the profit |

Banks, insurers and REITs aren't classified, and neither are companies with under five years.
The company page lists the signs behind the call; the ranking has a **Moat** column; and the
research writer is told which kind the numbers point to, to confirm or dispute from the sources.
The numbers only point: a high, steady gross margin can also come from a patent that runs out.

## Watchlist

A star on the company page puts it on the watchlist (`data/watchlist.json`): a ticker and the day
it went on, no positions and no amounts. `python main.py digest` fetches fresh prices for those
companies, scores them again and records what changed since the previous digest: entered or left
the buy zone, a new sell signal, insiders buying (clustered or not), falling below the gate. Each
digest is saved in `data/digests/`; the **Watchlist** page shows the latest changes and sorts the
companies by how far the price is above buy below.

## Off the radar (`coverage.py`)

`python ingest.py --coverage` reads two numbers from Yahoo Finance for every analysed company: how
many analysts publish estimates for it, and how much of it institutions hold. A company that passes
the checklist, has a price, and that three analysts or fewer follow is **off the radar**: fewer
people set its price, so a careful reading of the statements is worth more there. The page of that
name lists them by expected return and ranks the markets by how thinly they are covered; the
ranking has an **Analysts** column and a switch for three or fewer; the research writer is told the
count, so a brief can weigh it under *Why it might be cheap*.

What the counts can't do:

- Yahoo's analysts are those in its data vendor's feed. A Polish or Israeli broker that publishes
  only locally isn't counted, so zero means nobody in the international feed, not nobody at all.
- A second listing (a Cboe copy of a London line, a Toronto share whose estimates sit on the US
  one) can show zero analysts for a company thirty follow. London copies are read on the London
  line; a zero on a company funds own more than half of is treated as unknown.
- There is no free record of past counts, so whether off-the-radar companies did better can't be
  tested on the past the way the ranking is in [09](09-evidence.md).

Next: **[05 Market regime](05-market-regime.md)**.
