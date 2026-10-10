# 03. Data pipeline

```
company_tickers_exchange.json ──> who is listed (NYSE + Nasdaq by default)
submissions/CIK.json ──────────> SIC code, country, fiscal year end, last annual filing
companyfacts/CIK.json ─────────> every XBRL fact; we keep ~70 concepts from annual forms
                                  └─> facts table (value, period, form, filed, accession)
```

`ingest.py` fetches with six threads behind one rate limiter (8 requests/s,
under the SEC's 10). A company's facts are only refetched when its last
annual filing date changed. Its filing index is still checked every time,
so a repeat run over the whole market takes ~12 minutes against ~25 for the
first full load.

## From facts to statements (`statements.py`)

**Years are keyed by period end, not by `fy`.** In companyfacts `fy` is the
fiscal year of the *filing*: a 2024 10-K carries 2022 and 2023 comparatives
tagged `fy=2024`.

**Restatements and point-in-time.** The same (concept, period) appears once
per filing. Each one keeps the latest value filed on or before `as_of`, so
`annual_statements(facts, as_of="2016-06-30")` returns exactly what was
public then. That is what makes an honest backtest possible.

**Tags change.** Revenue moved from `SalesRevenueNet` to
`RevenueFromContractWithCustomer…` in 2018. `concepts.py` lists alternatives
per field in order of preference and picks per year, so a mid-history tag
change doesn't drop years. Lines some companies only report in parts (SG&A
as selling + G&A) are summed.

**IFRS.** Foreign filers (20-F) use `ifrs-full`; the same field map covers it,
which is also what ESEF filings from Europe will use.

## Per-share numbers and splits

A share count filed before a stock split is in pre-split units. Instead of
trusting a third-party split calendar, splits are **read off the filings**:
when the same period shows up in two reports at a clean ratio (4.0 for
shares, 0.25 for EPS), that's a split, dated at the first restated filing.
Every number filed before that date is moved into today's units. Verified on
Apple (7:1, 4:1), NVIDIA (4:1, 10:1), Alphabet (20:1), Walmart (3:1),
Tesla (5:1, 3:1) and Coca-Cola (2:1). A split newer than the last annual
filing comes from yfinance.

**Tagging errors.** Some filers tag share counts in millions (McDonald's
from 2024). When a share count disagrees badly with net income / reported
EPS, the implied count wins and the company page says so.

## Every other market (`yahoo.py`)

Outside the US there is no free, uniform source of filings, so all 49 other markets go through
Yahoo Finance the same way: no region gets better treatment than another.

1. **Universe.** Yahoo's screener, market by market, above a market-cap floor
   (`WORLD_MIN_CAP_USD`, $1B by default, converted to local currency).
2. **One listing per company.** The same company trades in many places: NVIDIA in Warsaw,
   Santander in London, a Brazilian receipt on TSMC. A listing is kept only if:
   - it trades in the local currency or the company reports in it;
   - it isn't on a foreign-share segment (London's `.IL` order book, Brazilian `..34.SA` receipts);
   - the company doesn't report in another covered market's own currency (CHF, TWD, CNY...);
   - its headquarters isn't in another covered market whose currency it reports in (Allianz is
     German, wherever it's quoted);
   - and of the listings that survive with the same message-board id, or the same name in one
     country (India's NSE and BSE), the home-currency, most traded one wins.
   US companies are left to EDGAR, which goes back further.
3. **Statements.** Yahoo's annual income statement, balance sheet and cash flow, usually four to
   five years, stored as facts with taxonomy `yahoo` and mapped in `concepts.YAHOO` onto the same
   fields EDGAR uses. From there the pipeline can't tell them apart. Yahoo gives no filing date,
   so one is estimated at period end + 120 days.
4. **Currencies.** Valuation runs in the statement currency. If shares trade in another one (a
   Polish company reporting in euros), prices are converted day by day with Yahoo's FX pairs, and
   price and buy-below are shown in the trading currency. Quotes in subunits (pence, South African
   cents, agorot) are moved to the major unit first.
5. **Refresh.** A company is refetched after 30 days; stored listings that the rules above now say
   belong elsewhere are pruned on every run.

## Known gaps

- **Several share classes** (Visa, Hershey, Berkshire): EPS is filed per
  class only, which companyfacts drops. Quality is still scored; valuation
  waits for dimensional XBRL parsing.
- **US listings of foreign companies reporting in their own currency** (TSMC in TWD) are scored
  but kept out of the ranking; their home listing (2330.TW) is valued instead.
- **History outside the US** is four to five years, so ten-year consistency checks run on a shorter
  window there. The coverage figure and a flag on the company page say so. Official sources
  (ESEF for Europe, EDINET for Japan, DART for Korea) can deepen it later.
- **No cost of sales filed** (payment networks, many services): operating
  margin stands in for gross margin, R&D and depreciation are measured
  against revenue.

Next: **[04 Checklist & valuation](04-checklist-and-valuation.md)**.
