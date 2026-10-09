# 09. Portfolio and track record

## Track record (`track.py`)

A backtest on free data flatters itself (no delisted companies, and the model has read the future).
A forward test can't cheat, so every full `python main.py screen` saves the ranking as it stood
that day. The **Track record** page then:

- buys the top ten of each snapshot on paper at that day's close, equal weight;
- marks them to today with dividends, converted to PLN at each day's exchange rate;
- compares that with the MSCI All Country World ETF (`ACWI`), also in PLN;
- holds each pick against its own market's benchmark, in local currency.

Snapshots under a week old are shown but not counted in the averages. It takes months before the
numbers mean anything; the point is that they can't be fitted after the fact.

## Portfolio (`portfolio.py`)

Your trades go in on the **Portfolio** page (ticker, date, buy or sell, shares, price and fees in
the currency the shares trade in). They are stored in `data/portfolio.sqlite`, apart from DuckDB,
because the dashboard holds the database read-only. Prices, dividends and exchange rates come
from what `main.py screen` stored; the screen also prices everything held, even below the gate.

Per position: shares, average cost, value in PLN, weight, return in local currency and in PLN, the
currency effect (the difference between the two), and dividends received. Overall: value, gain,
XIRR (money-weighted, shown after 90 days), dividends, and exposure by currency and market.

### The plan

The plan suggests a target weight for everything held plus the best of the ranking:

1. **Score** = (expected yearly return in PLN minus 8%) × quality / 100. Below 8% scores zero.
2. **Spread** 100% by score, then **cap** each position at 10% and each **cluster** at 25%,
   handing what's cut to the others until nothing moves.
3. **Clusters** join companies in the same industry or whose weekly returns over three years
   correlate above 0.6. Owning five beverage makers is one bet, not five.
4. **Cash**: each position gives up its market's suggested cash share from the Markets page, so a
   very expensive market holds 35% back. Whatever the caps leave over is cash too.

Actions: **buy** (not held, target above 0.5%), **add** or **trim** (target 2 points away from now),
**hold**, **sell** (held, target near zero because the expected return fell below 8% or the
company dropped out of the ranking).

It's a sizing aid, not an order book: nothing is traded, and taxes and fees aren't modelled.

Next: back to **[01 Overview](01-overview.md)**.
