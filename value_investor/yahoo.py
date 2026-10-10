"""18 · yahoo: every listed company outside the us.

the universe is yahoo's screener, region by region, one home listing per
company (the one quoted in the currency it reports in). about five years of
statements and five quarters, stored as facts and run through the same code
as edgar; filing dates are estimated at period end + 120 days.
"""

import logging
import random
import time
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

from value_investor import concepts, fx, markets

logger = logging.getLogger(__name__)

FILING_LAG = timedelta(days=120)
PAGE = 250


# a few exchanges carry their own code instead of the country's: Tadawul is "sr"
# (which is also Suriname's region), Tallinn "tl", Vilnius "vs", Reykjavik "ic"
EXCHANGE_CODES = {"sr": "SAU", "tl": "EST", "vs": "LTU", "ic": "ISL"}


def _market_iso3(market_code: "str | None") -> "str | None":
    code = (market_code or "").split("_")[0]
    if code in EXCHANGE_CODES:
        return EXCHANGE_CODES[code]
    m = markets.BY_REGION.get(code)
    return m.iso3 if m else None


def screen_region(region: str, min_cap_local: float, limit: "int | None" = None) -> list:
    query = yf.EquityQuery("and", [
        yf.EquityQuery("eq", ["region", region]),
        yf.EquityQuery("gt", ["intradaymarketcap", min_cap_local]),
    ])
    out, offset = [], 0
    while True:
        try:
            page = yf.screen(query, offset=offset, size=PAGE, sortField="intradaymarketcap", sortAsc=False)
        except Exception as exc:
            logger.warning("screener failed for %s at %d: %s", region, offset, exc)
            break
        quotes = page.get("quotes", [])
        out.extend(q for q in quotes if q.get("quoteType") == "EQUITY")
        offset += len(quotes)
        if not quotes or offset >= page.get("total", 0) or (limit and len(out) >= limit):
            break
        time.sleep(0.5)
    return out[:limit] if limit else out


def screener_floor(currency: str, min_cap_usd: float, usd_to_local: float) -> float:
    """the size floor in the screener's units. where shares are quoted in pence, cents or
    fils (London, Johannesburg, Tel Aviv, Kuwait), the screener's market cap is too."""
    unit = next((d for major, d in fx.SUBUNITS.values() if major == currency), 1.0)
    return min_cap_usd * usd_to_local * unit


def universe(con, iso3s: list, min_cap_usd: float, limit_per_market: "int | None" = None) -> pd.DataFrame:
    """one row per company, at its home listing, for the given markets."""
    rows = []
    wanted = [markets.BY_ISO[i] for i in iso3s if i in markets.BY_ISO and i != "USA"]
    for m in wanted + [markets.BY_ISO["USA"]]:
        quotes = screen_region(m.region, screener_floor(m.currency, min_cap_usd, fx.rate(con, "USD", m.currency) or 1.0))
        logger.info("%s: %d listings above the floor", m.name, len(quotes))
        for q in quotes:
            rows.append({
                "symbol": q["symbol"], "name": q.get("longName") or q.get("shortName"),
                "market_code": q.get("market"), "exchange": q.get("fullExchangeName") or q.get("exchange"),
                "currency": q.get("currency"), "financial_currency": q.get("financialCurrency"),
                "market_cap": q.get("marketCap"), "board": q.get("messageBoardId") or q["symbol"],
                "turnover": (q.get("averageDailyVolume3Month") or 0) * (q.get("regularMarketPrice") or 0),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["market"] = df["market_code"].map(_market_iso3)
    # foreign-share segments: London's International Order Book, Brazilian depositary receipts.
    df = df[~df["symbol"].str.endswith(".IL") & ~df["symbol"].str.contains(r"3[1-5]\.SA$", regex=True)]
    american = set(df[(df["market"] == "USA") & (df["financial_currency"] == "USD")]["board"])
    df = df[~df["board"].isin(american) & (df["market"] != "USA") & df["market"].notna()]

    # A listing belongs to its market if it trades in the local currency or the
    # company reports in it. Toyota quoted in yen in London, a Brazilian receipt
    # on TSMC, Santander in pence: all someone else's company.
    local = df["market"].map(lambda iso: markets.BY_ISO[iso].currency)
    quote = df["currency"].map(lambda c: fx.major(c)[0])
    df = df[(quote == local) | (df["financial_currency"] == local)]
    # reporting in another market's own currency (CHF, TWD, CNY...) gives it away
    # as a foreign company. USD and EUR are too common to judge this way; the
    # headquarters check in fundamentals() catches those.
    local, quote = local.loc[df.index], quote.loc[df.index]
    foreign_ccy = (df["financial_currency"] != local) & ~df["financial_currency"].isin(["USD", "EUR"]) \
        & df["financial_currency"].isin({m.currency for m in markets.MARKETS})
    df = df[~foreign_ccy]
    quote = quote.loc[df.index]

    df["home"] = quote.loc[df.index] == df["financial_currency"]
    df = df.sort_values(["home", "turnover"], ascending=False).drop_duplicates("board")
    # twin exchanges in one country (NSE and BSE in India) get separate board ids.
    df["name_key"] = df["name"].fillna(df["symbol"]).str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    df = df.drop_duplicates(["market", "name_key"]).drop(columns="name_key")
    df = df.sort_values(["market", "market_cap"], ascending=[True, False])
    if limit_per_market:
        df = df.groupby("market", group_keys=False).head(limit_per_market)
    return df.reset_index(drop=True)


def _wanted_rows() -> set:
    rows = set()
    for alts in concepts.YAHOO.values():
        for alt in alts:
            rows.update(alt[1] if isinstance(alt, tuple) else [alt])
    return rows


WANTED = _wanted_rows()
COLUMNS = ["taxonomy", "concept", "unit", "period_start", "period_end", "value", "form", "filed", "accn"]
INCOME_LIKE = "duration"
BALANCE = "instant"


def _facts_from(frame: pd.DataFrame, kind: str, currency: str, days: int = 364) -> list:
    out = []
    if frame is None or frame.empty:
        return out
    today = date.today()
    for row_name in frame.index:
        if row_name not in WANTED:
            continue
        if row_name in concepts.YAHOO_PER_SHARE_ROWS:
            unit = f"{currency}/shares"
        elif row_name in concepts.YAHOO_SHARE_ROWS:
            unit = "shares"
        else:
            unit = currency
        for end, value in frame.loc[row_name].items():
            if pd.isna(value):
                continue
            end = pd.Timestamp(end).date()
            start = end - timedelta(days=days) if kind == INCOME_LIKE else None
            filed = min(end + FILING_LAG, today)
            out.append(("yahoo", row_name, unit, start, end, float(value), "yahoo", filed, None))
    return out


COUNTRY_ALIASES = {"Czech Republic": "CZE", "Korea": "KOR", "Republic of Korea": "KOR", "UK": "GBR",
                   "Great Britain": "GBR", "Viet Nam": "VNM", "Türkiye": "TUR"}
COUNTRY_TO_ISO = {m.name: m.iso3 for m in markets.MARKETS} | COUNTRY_ALIASES
EURO_MEMBERS = {m.iso3 for m in markets.MARKETS if m.currency == "EUR"}


def home_elsewhere(info: dict, market: "str | None") -> "str | None":
    """the other covered market a listing really belongs to, if any.

    Allianz quoted in zloty is still a German company: headquartered in a
    market we cover and reporting in that market's currency.
    """
    hq = COUNTRY_TO_ISO.get(info.get("country"))
    if not hq or not market or hq == market:
        return None
    reports = info.get("financialCurrency")
    hq_currency = markets.BY_ISO[hq].currency
    if reports == hq_currency or (reports == "EUR" and hq in EURO_MEMBERS):
        return hq
    return None


def fundamentals(symbol: str, market: "str | None" = None, retries: int = 3) -> tuple:
    for attempt in range(retries + 1):
        try:
            t = yf.Ticker(symbol)
            info = t.info or {}
            elsewhere = home_elsewhere(info, market)
            if elsewhere:
                return pd.DataFrame(), {"home_market": elsewhere}, pd.DataFrame()
            currency = info.get("financialCurrency") or fx.major(info.get("currency"))[0]
            rows = (_facts_from(t.income_stmt, INCOME_LIKE, currency)
                    + _facts_from(t.cashflow, INCOME_LIKE, currency)
                    + _facts_from(t.balance_sheet, BALANCE, currency))
            quarter_rows = _quarter_rows(t, currency)
            break
        except Exception as exc:
            if attempt == retries:
                raise
            wait = 20 * (attempt + 1) + random.random() * 5
            logger.info("Yahoo throttled %s (%s); waiting %.0fs", symbol, type(exc).__name__, wait)
            time.sleep(wait)
    facts = pd.DataFrame(rows, columns=COLUMNS)
    prof = {
        "name": info.get("longName") or info.get("shortName"),
        "country": info.get("country"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "summary": info.get("longBusinessSummary"),
        "currency": currency,
        "price_currency": info.get("currency"),
        "market_cap": info.get("marketCap"),
        "fiscal_year_end": None,
        "last_annual_filed": max(facts["filed"]) if not facts.empty else None,
    }
    return facts, prof, pd.DataFrame(quarter_rows, columns=COLUMNS)


def _quarter_rows(t, currency: str) -> list:
    return (_facts_from(t.quarterly_income_stmt, INCOME_LIKE, currency, days=91)
            + _facts_from(t.quarterly_cashflow, INCOME_LIKE, currency, days=91)
            + _facts_from(t.quarterly_balance_sheet, BALANCE, currency))


def quarterly(symbol: str) -> pd.DataFrame:
    """the last five or so quarters, for companies stored before quarters were kept."""
    t = yf.Ticker(symbol)
    info = t.info or {}
    currency = info.get("financialCurrency") or fx.major(info.get("currency"))[0]
    return pd.DataFrame(_quarter_rows(t, currency), columns=COLUMNS)


def profile(symbol: str) -> dict:
    """sector, industry and size for a ticker we already have statements for."""
    info = yf.Ticker(symbol).info or {}
    return {"sector": info.get("sector"), "industry": info.get("industry"),
            "summary": info.get("longBusinessSummary"), "market_cap": info.get("marketCap")}
