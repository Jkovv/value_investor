# Investment principles

The rules this system scores against, written down once. `value_investor/config.py`
holds the same thresholds as numbers; the research agents read this file as their
brief. When the two disagree, fix both.

## The one idea

Own businesses with a **durable competitive advantage**, bought at a price that
leaves a good return even if the future is merely as good as the past.

A durable advantage shows up in the financial statements as *consistency*: high
margins year after year, little debt, little need to reinvest, earnings that rise
without drama. A single great year proves nothing. Everything below is measured
over ten years.

Three kinds of business tend to have one:

1. **A unique product** that owns a piece of the customer's mind — people ask for it
   by name and pay more for it.
2. **A unique service** that is institution-specific rather than people-specific — the
   customer can't easily leave, and the value doesn't walk out with a star employee.
3. **The low-cost buyer and seller** of something the public keeps needing — winning
   on volume, not margin.

## Income statement

| Measure | Good | Grey | Poor | Why |
|---|---|---|---|---|
| Gross margin | > 40% | 20–40% | < 20% | Pricing power. Under 20% usually means a commodity fight. |
| Gross margin swing (std dev) | < 5 pp | 5–10 pp | > 10 pp | The advantage has to hold every year, not on average. |
| SG&A / gross profit | < 30% | 30–80% | > 80% | Near 100% means the business has to shout to sell. |
| R&D / gross profit | < 10% | 10–30% | > 30% | An edge that must be re-invented every year isn't durable. |
| Depreciation / gross profit | < 10% | 10–20% | > 20% | Heavy plant that wears out eats the margin. |
| Interest / operating income | < 15% | 15–30% | > 30% | In any industry, the lowest ratio usually marks the strongest company. |
| Net margin | > 20% | 10–20% | < 10% | For banks a high margin can mean high risk — read it differently. |
| EPS | rising in ≥ 70% of years, no losses | | | Look at net earnings too: buybacks can lift EPS on their own. |

When a company files no cost of sales (payment networks, many service firms),
operating margin stands in for gross margin (> 25% good, < 12% poor), and R&D and
depreciation are measured against revenue at half the thresholds.

**Taxes paid** should look like the statutory rate. A company that reports one
profit to shareholders and a much smaller one to the tax office is probably being
creative with one of them.

**One-offs** — gains or losses on selling assets, restructuring charges — are not
earning power. Look through them.

## Balance sheet

- **Cash and marketable securities** are what carries a company through a bad stretch.
  Lots of cash and little debt: it survives. Little cash and a pile of debt: it may not.
- **Long-term debt** should be payable from **three to four years** of net earnings;
  under one year is the strict version.
- **Liabilities / equity, with treasury stock added back** to equity, under 0.8.
  (Buybacks shrink book equity; adding treasury stock back stops a generous
  repurchase programme looking like leverage.) Doesn't apply to financial companies.
- **No preferred stock.** Strong businesses rarely need it.
- **Retained earnings growing.** This is the pile the future compounds from.
- **Return on equity above 15%, most years.** If equity is negative because of
  buybacks, judge the return on equity with treasury stock added back.
- **Treasury stock and a falling share count** are good signs; a share count that
  keeps rising while earnings don't means the business is funding itself by selling
  pieces of the owners.
- The **current ratio** is not a useful test here: great businesses often run below 1
  because their earning power replaces a cash buffer.
- **Very high return on assets** can mean the business is cheap to copy. Capital is a
  barrier to entry; ask what it would cost a well-funded rival to compete.

## Cash flow

- **Capital expenditure / net earnings over ten years:** under 25% is the mark of a
  durable advantage, under 50% still worth a look, above that the business eats its
  own earnings.
- **Free cash flow should roughly match net income.** Earnings that never turn into
  cash are a warning.
- **Buybacks over dividends** as the way surplus cash comes back — but only when the
  price is below what the business is worth.
- **Owner earnings** = net income + depreciation − the capital spending needed just to
  stand still. Maintenance capex is estimated: total capex minus what new sales needed.
- **Return on retained earnings** = EPS gained over the decade / EPS kept in the
  business over the decade. Above 15% means management turns retained profit into
  more profit.

## Valuation

Treat the share as a bond whose coupon is EPS and whose coupon grows.

1. **Initial return** = EPS / price. Compare it with the 10-year government bond
   yield. Pre-tax earnings / price is the fairer comparison, since bond yields are
   quoted before tax.
2. **Growth** = the lower of what EPS did over ten years (smoothed at both ends) and what
   ROE × (1 − payout ratio) can sustain. Capped at 15%.
3. **EPS in ten years** = EPS × (1 + growth)¹⁰.
4. **Price in ten years** = that EPS × the P/E the market historically paid for this
   company — low, average and high, which gives a range rather than a point.
5. **Expected annual return** = ((future price + dividends collected) / price today)^(1/10) − 1.
   The ranking sorts on this.
6. **Buy below** = (future price + dividends) / 1.15¹⁰ — the most we can pay and
   still compound at 15% a year.

## When to buy

- In a bear market, or when a great business makes a **one-time, solvable** mistake
  and the market punishes it as if it were permanent.
- Ask why the price fell: a market panic, a recession, or a curable problem of the
  company's own? Only those three. A business in structural decline is not cheap.
- Don't buy because "it already fell so much". Falling is not a valuation.

## When to sell

Generally never. Sell when:

- a much better opportunity needs the money,
- the business is losing its advantage (the checklist score falls filing after filing), or
- the market has gone euphoric: **P/E at or above 40** is the sell line. In a raging
  bull market, park the money in short government bonds and wait.

## The market as a whole

Market cap / GDP measures how expensive the whole market is. It decides **how much
cash to hold**, never which company to buy. Because the ratio has drifted upward for
decades, read it against its own long-run trend, not against a fixed line.

Other context worth watching: the 10-year minus 2-year yield (an inverted curve has
preceded most recessions), the Sahm rule (unemployment rising fast), the VIX, and the
trend in public debt. Corrections of 10% come roughly every two years and bear markets
of 25%+ every six or so — have cash ready for them.

## Building the portfolio

- **Independence over count.** Positions should not depend on each other: different
  industries, countries, currencies, customers and suppliers. Price correlation alone
  is not enough — in a crash correlations go to one.
- A handful to fifteen positions. A small portfolio can be very concentrated if each
  business is understood; ten to thirty is the textbook range for spreading risk.
- Mix types of business (steady compounders, fast growers, turnarounds) so they don't
  all react to the same news.
- Cap any single position and any single cluster of related positions.

## Management and honesty

- Are directors **buying** shares with their own money (not receiving them as pay)?
- Managers should be motivated by the business, not by the money.
- Ask insiders of competitors: if you had to short one rival for ten years, which one?
- **Red flags:** declining earnings, management turmoil, accounting irregularities,
  heavy use of EBITDA in place of earnings (it hides depreciation, which is a real cost).

## Thinking

- **Circle of competence.** If the business can't be explained in a paragraph, pass.
- **Invert.** Before buying, list what would kill the company. Then avoid that.
- **Keep it simple.** Prefer a business an idiot could run, because one day one will.
- **Ignore the swings.** A falling price on a good business is an offer, not a verdict.

## Behaviour (guardrails, not score)

These don't enter the score. They shape how the app asks you to act.

- Write the thesis down before buying; it's the only defence against "I knew it all along".
- Before selling, ask whether the thesis changed or only the price did — people sell
  winners too early and hold losers too long.
- Trading more makes results worse. The app warns when turnover climbs.
- When nearly every analyst says buy, the trade is crowded.
- Show what a business is worth before showing what it costs, so the price isn't the anchor.
