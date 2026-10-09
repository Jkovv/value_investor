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

## Known gaps

- **Several share classes** (Visa, Hershey, Berkshire): EPS is filed per
  class only, which companyfacts drops. Quality is still scored; valuation
  waits for dimensional XBRL parsing.
- **Foreign filers reporting in their own currency** (TSMC in TWD) are scored
  but not valued yet — that needs the FX rate and the ADR ratio.
- **No cost of sales filed** (payment networks, many services): operating
  margin stands in for gross margin, R&D and depreciation are measured
  against revenue.

Next: **[04 — Checklist & valuation](04-checklist-and-valuation.md)**.
