"""14 · screener: one company end to end, then the ranking.

    facts -> statements -> ratios -> checklist -> score -> valuation, lenses, quarters

only companies that clear the gate get priced. the ranking sorts on expected
return in the currency the shares trade in; a us listing of a foreign company is
scored but ranked through its home listing.
"""

import logging
import re
from dataclasses import dataclass, field

import pandas as pd

from value_investor import (config, fx, insiders, lenses, markets, metrics, prices as px, quarterly, rules,
                            statements, store, valuation)

logger = logging.getLogger(__name__)

YEARLY_COLUMNS = [
    "fiscal_year", "revenue", "gross_margin", "sga_to_gp", "rnd_to_gp", "dep_to_gp", "interest_to_opinc",
    "operating_margin", "net_margin", "eps", "dps", "payout", "roe", "debt_years", "adj_debt_to_equity",
    "capex_to_ni", "fcf", "owner_earnings", "shares", "retained_earnings", "buybacks",
]


@dataclass
class Analysis:
    cik: int
    ticker: str
    name: str
    profile: str
    company: dict
    currency: "str | None" = None
    as_of: "object | None" = None
    yearly: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: dict = field(default_factory=dict)
    checks: list = field(default_factory=list)
    quality: float = 0.0
    completeness: float = 0.0
    valuation: dict = field(default_factory=dict)
    flags: list = field(default_factory=list)
    rankable: bool = True
    lenses: dict = field(default_factory=dict)
    quarters: dict = field(default_factory=dict)
    insiders: "dict | None" = None

    @property
    def market(self) -> "str | None":
        return self.company.get("market")

    @property
    def passes_gate(self) -> bool:
        return (self.rankable and self.quality >= config.MIN_QUALITY
                and self.completeness >= config.MIN_COMPLETENESS
                and self.summary.get("history_years", 0) >= config.MIN_HISTORY_YEARS)

    @property
    def expected_return(self) -> "float | None":
        v = self.valuation
        return v["expected_return"]["mid"] if v.get("available") else None

    def payload(self) -> dict:
        yearly = []
        if not self.yearly.empty:
            y = self.yearly[[c for c in YEARLY_COLUMNS if c in self.yearly.columns]].copy()
            y.index = y.index.strftime("%Y-%m-%d")
            yearly = y.reset_index().to_dict(orient="records")
        return {
            "company": {k: (str(v) if v is not None else None) for k, v in self.company.items()},
            "currency": self.currency,
            "summary": self.summary,
            "checks": [c.to_dict() for c in self.checks],
            "valuation": self.valuation,
            "flags": self.flags,
            "lenses": self.lenses,
            "quarters": self.quarters,
            "insiders": self.insiders,
            "yearly": yearly,
        }

    def row(self) -> dict:
        v = self.valuation
        magic = self.lenses.get("magic") or {}
        return {
            "cik": self.cik, "ticker": self.ticker, "name": self.name,
            "as_of": pd.Timestamp(self.as_of or pd.Timestamp.today()).date(),
            "profile": self.profile, "quality": self.quality, "completeness": self.completeness,
            "history_years": self.summary.get("history_years", 0),
            "price": v.get("price"), "expected_return": self.expected_return,
            "buy_price": v.get("buy_price"), "dividend_yield": v.get("dividend_yield"),
            "passes_gate": self.passes_gate, "market": self.market,
            "country": self.company.get("country"), "currency": v.get("currency") or self.currency,
            "f_score": (self.lenses.get("piotroski") or {}).get("scaled"),
            "earnings_yield": magic.get("earnings_yield"), "return_on_capital": magic.get("return_on_capital"),
            "payload": self.payload(),
        }


def _splits(facts: pd.DataFrame, priced: pd.DataFrame, as_of) -> pd.Series:
    """splits from the filings, plus any newer split the filings can't know about yet."""
    found = statements.inferred_splits(facts, as_of)
    if not priced.empty and not facts.empty:
        filed = pd.to_datetime(facts["filed"])
        if as_of is not None:
            filed = filed[filed <= pd.Timestamp(as_of)]
        late = px.splits(priced)
        late = late[late.index > filed.max()]
        if not late.empty:
            found = pd.concat([found, late]).sort_index()
    return found


FUND_NAME = re.compile(r"\sOrd$|\bPhysical\b|\bFund\b(?! Management)|\bETF\b", re.I)
FUND_SUMMARY = re.compile(r"^[^.]{0,120}?\b(is|operates as) an? (closed[- ]end(ed)?|investment trust|exchange[- ]traded|"
                          r"(listed |externally managed )?investment (company|fund|vehicle))", re.I)


def looks_like_fund(name: "str | None", industry: "str | None", summary: "str | None") -> bool:
    """investment trusts, closed-end funds and metal trusts: their earnings are gains on what
    they hold, so a checklist built for operating businesses says nothing about them."""
    name, summary = name or "", summary or ""
    if "Physical" in name and ("Trust" in name or "Fund" in name):
        return True
    if isinstance(industry, str) and industry not in ("", "Asset Management"):
        return False
    if "real estate investment trust" in summary.lower():
        return False
    return bool(FUND_NAME.search(name) or FUND_SUMMARY.search(summary))


def _name_key(name: "str | None") -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    drop = {"ltd", "limited", "inc", "plc", "sa", "ag", "nv", "co", "corp", "corporation", "the", "group", "holdings"}
    return " ".join(w for w in words if w not in drop)


def _home_listing(con, name: "str | None") -> "str | None":
    """the Yahoo home listing of a company we also hold through an SEC filing, if any."""
    key = _name_key(name)
    if not key:
        return None
    rows = con.execute("SELECT ticker, name FROM companies WHERE source = 'yahoo'").fetchall()
    for ticker, other in rows:
        if _name_key(other) == key:
            return ticker
    return None


def _value(con, a: "Analysis", priced: pd.DataFrame, bond_yield) -> dict:
    """valuation in statement currency, then price and buy price back in the quote currency."""
    quoted, quote_ccy = fx.to_major(priced, a.company.get("price_currency") or "USD")
    work = quoted
    if quote_ccy and a.currency and quote_ccy != a.currency:
        work = fx.convert_prices(con, quoted, quote_ccy, a.currency)
        if work is None or work.empty:
            return {"available": False, "reason": f"no {quote_ccy}/{a.currency} exchange rate"}
    v = valuation.value(a.yearly, a.summary, work, bond_yield)
    if not v.get("available"):
        return v
    if a.summary.get("shares"):
        cap = v["price"] * a.summary["shares"]
        last = a.yearly.iloc[-1]
        net_buyback = (last.get("buybacks") or 0) - (last.get("stock_issued") or 0)
        v["market_cap"] = cap
        v["shareholder_yield"] = v["dividend_yield"] + net_buyback / cap
    if quote_ccy != a.currency:
        rate = fx.rate(con, a.currency, quote_ccy) or 1.0
        v["price"] = px.last_close(quoted)[0]
        v["buy_price"] *= rate
        v["statement_currency"] = a.currency
    v["currency"] = quote_ccy
    return v


def analyze(con, cik: int, as_of=None, with_prices: "bool | None" = None, bond_yield=None) -> Analysis:
    comp = store.company(con, cik) or {"cik": cik}
    profile = rules.profile_for(comp.get("sic"))
    a = Analysis(cik=cik, ticker=comp.get("ticker"), name=comp.get("name"), profile=profile,
                 company=comp, as_of=as_of)

    facts = store.load_facts(con, cik)
    table = statements.annual_statements(facts, as_of=as_of)
    if table.empty:
        a.flags.append("no usable annual statements")
        return a
    a.currency = table.attrs.get("currency")
    source = comp.get("source") or "sec"

    priced = px.until(px.ensure(con, a.ticker), as_of) if (with_prices and a.ticker) else pd.DataFrame()
    splits = _splits(facts, priced, as_of)
    a.yearly = metrics.yearly(table, splits=splits)
    a.summary = metrics.summary(a.yearly)
    a.checks = rules.evaluate(a.summary, profile)
    a.quality, a.completeness = rules.score(a.checks)

    if profile == "financial":
        a.flags.append("financial company: shorter checklist")
    if a.summary.get("history_years", 0) < config.HISTORY_YEARS:
        where = "Yahoo Finance" if source == "yahoo" else "XBRL"
        a.flags.append(f"only {a.summary.get('history_years', 0)} years of {where} history")
    if source == "yahoo":
        a.flags.append("statements from Yahoo Finance; filing dates estimated")
    if a.summary.get("shares_corrected"):
        a.flags.append("some share counts were rebuilt from net income / reported EPS (tagging error in the filing)")
    if a.yearly["eps"].isna().all():
        a.flags.append("no company-wide per-share data filed (usually several share classes)")
    shares = a.yearly["shares"].dropna()
    jumps = (shares / shares.shift(1)).dropna()
    if not jumps.empty and (jumps.max() > 1.8 or jumps.min() < 0.55):
        a.flags.append("unexplained jump in share count; per-share history may be off")
    if source == "sec" and a.currency and a.currency != "USD":
        a.rankable = False
        a.flags.append(f"reports in {a.currency}; ranked through its home listing, not this US one")
    elif source == "sec" and comp.get("country") not in (None, "United States"):
        home = _home_listing(con, comp.get("name"))
        if home:
            a.rankable = False
            a.flags.append(f"US listing of a foreign company; ranked through its home listing {home}")
    if looks_like_fund(comp.get("name"), comp.get("industry"), comp.get("summary")):
        a.rankable = False
        a.flags.append("a fund or trust that holds other assets; the checklist is for operating businesses, so it isn't ranked")

    if with_prices is None:
        with_prices = a.passes_gate
        if with_prices and a.ticker:
            return analyze(con, cik, as_of=as_of, with_prices=True, bond_yield=bond_yield)

    if with_prices:
        if not a.rankable:
            a.valuation = {"available": False, "reason": f"reports in {a.currency}; see its home listing"}
        else:
            if bond_yield is None:
                bond_yield = markets.bond_yield(con, a.market, as_of)
            a.valuation = _value(con, a, priced, bond_yield)

    v = a.valuation
    to_quote = (fx.rate(con, a.currency, v["currency"]) or 1.0) if v.get("statement_currency") else 1.0
    a.lenses = lenses.compute(table, a.yearly, a.summary, v, profile, comp.get("sector"), comp.get("sic"), to_quote)
    a.quarters = _quarters(con, a, facts, as_of, to_quote)
    if source == "sec" and as_of is None:
        a.insiders = insiders.summary(con, cik)
    return a


def _quarters(con, a: "Analysis", facts: pd.DataFrame, as_of, to_quote: float) -> dict:
    qt = quarterly.table(store.load_quarterly_facts(con, a.cik), facts, a.currency, as_of)
    if qt.empty:
        return {}
    summary = quarterly.summary(qt, a.summary.get("net_income"))
    v, shares = a.valuation, a.summary.get("shares")
    ttm = summary.get("ttm_net_income")
    if v.get("available") and ttm and ttm > 0 and shares:
        summary["pe_ttm"] = v["price"] / to_quote / (ttm / shares)
    if summary.get("trend") == "slipping" and not summary.get("stale"):
        a.flags.append("sales or profit fell against a year earlier in each of the last two quarters")
    return {"summary": summary, "rows": quarterly.rows(qt, config.QUARTERS_SHOWN)}


def run(ciks=None, as_of=None, with_prices: "bool | None" = None) -> pd.DataFrame:
    with store.connect() as con:
        if ciks is None:
            ciks = store.companies(con)["cik"].tolist()
        results = []
        for i, cik in enumerate(ciks, start=1):
            try:
                a = analyze(con, int(cik), as_of=as_of, with_prices=with_prices)
                store.save_analysis(con, a.row())
            except Exception as exc:
                logger.warning("analysis failed for CIK %s: %s", cik, exc)
                continue
            results.append(a)
            if i % 250 == 0:
                logger.info("analysed %d / %d", i, len(ciks))
        # peers are matched on size in dollars; the dashboard can't fetch rates itself
        currencies = [r[0] for r in con.execute("SELECT DISTINCT price_currency FROM companies").fetchall()]
        fx.ensure_pairs(con, currencies, ["USD"])
    return to_frame(results)


def to_frame(results: list) -> pd.DataFrame:
    rows = [{k: v for k, v in a.row().items() if k != "payload"} for a in results]
    return pd.DataFrame(rows)


def ranking(con, only_gate: bool = True) -> pd.DataFrame:
    df = store.analyses(con)
    if df.empty:
        return df
    if only_gate:
        df = df[df["passes_gate"]]
    df = df.assign(_has=df["expected_return"].notna(), magic_rank=magic_rank(df))
    return (df.sort_values(["_has", "expected_return", "quality"], ascending=[False, False, False])
              .drop(columns=["_has"]).reset_index(drop=True))


def magic_rank(df: pd.DataFrame) -> pd.Series:
    """greenblatt's ranking: place on earnings yield plus place on return on
    capital, lowest total first. only companies with both numbers take part."""
    if "earnings_yield" not in df:
        return pd.Series(pd.NA, index=df.index, dtype="Int64")
    both = df["earnings_yield"].notna() & df["return_on_capital"].notna()
    places = (df.loc[both, "earnings_yield"].rank(ascending=False)
              + df.loc[both, "return_on_capital"].rank(ascending=False))
    return places.rank(method="min").astype("Int64").reindex(df.index)
