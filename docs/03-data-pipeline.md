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

Yahoo's screener misses some big names (Kweichow Moutai and about fifty other A-shares), so the
Chinese universe is topped up from EastMoney's valuation table. A foreign listing that shares a
message board with a US one is kept only if it trades at least half as much: HSBC in Hong Kong and
Shell in London stay, Apple in Frankfurt goes.

## Ten years outside the US

Yahoo stops at four or five years, which is too short for a ten-year checklist. Where a market has
a free source that goes further, its statements are stored next to Yahoo's under their own taxonomy
(`ingest.py --history`, part of every full run):

| Market | Source | Years | Notes |
|---|---|---|---|
| China | EastMoney F10 | 10 | full statements, real filing dates |
| Hong Kong | EastMoney HK indicators | up to 20 | headline lines only; the currency is settled by matching net income with Yahoo's |
| Taiwan | FinMind (exchange filings) | 10+ | quarters summed into years; a free token raises the hourly limit |
| India | Screener.in | 12 | consolidated where published; coarser lines, no cost of sales |
| Brazil | CVM open data (DFP) | 11 | full statements, real filing dates; banks read by account name |
| Poland | Biznesradar | up to 20 | full statements as the site shows them, real report dates; it converts euro and dollar reporters into zloty, so a company is kept only when net income matches Yahoo's in Yahoo's currency |
| Japan | IRBANK (EDINET filings) | up to 19 | headline lines, to the hundred million yen; IRBANK's debt and SG&A share left out, they didn't hold up against Yahoo; equity is book value per share times shares; REITs (half-year periods) stay on Yahoo |
| South Korea | DART, the FSS's filing system | 12 | XBRL of every third annual report, three years each, from the public website without an API key; consolidated where published; SG&A left to Yahoo (Korean SG&A includes R&D); banks, insurers and brokers only file XBRL from 2023 and stay on Yahoo |
| Anywhere | SEC 20-F / 40-F / 10-K | 10+ | home listings of companies that also file with the SEC (Toyota, ASML, HDFC Bank), linked only when revenue or net income agrees |

Per-share numbers are moved into today's units with the bonus issues and splits found in the jump
of the share count implied by net income over EPS. When sources overlap, SEC filings lead, then the
source with the most years; Yahoo only fills lines and years the others don't have. Biznesradar,
IRBANK and DART are kept for a company only when their net income matches Yahoo's, in Yahoo's
currency, for at least half the years both have. The ranking can be limited to companies with ten
full years.

The Polish, Japanese and Korean sources are read from public pages, paced at one request every
1.5 to 3 seconds, so a first run takes about 20 minutes for Poland and an hour or two each for Japan
and Korea. After that a company is refetched every 30 days.

## Known gaps

- **Several share classes** (Visa, Hershey, Berkshire): EPS is filed per
  class only, which companyfacts drops. Quality is still scored; valuation
  waits for dimensional XBRL parsing.
- **US listings of foreign companies reporting in their own currency** (TSMC in TWD) are scored
  but kept out of the ranking; their home listing (2330.TW) is valued instead.
- **History in the markets without a local source** (Europe, Canada, Australia and the rest) is four
  to five years unless the company files with the SEC, so ten-year checks run on a shorter window
  there. The years of history show in the ranking and on the company page.
- **No cost of sales filed** (payment networks, many services): operating
  margin stands in for gross margin, R&D and depreciation are measured
  against revenue.

Next: **[04 Checklist & valuation](04-checklist-and-valuation.md)**.
