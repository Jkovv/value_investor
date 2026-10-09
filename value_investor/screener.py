"""14 · screener — one company end to end, then the ranking.

    facts -> statements -> yearly ratios -> summary -> checklist -> score
    summary + prices -> valuation

Prices are only fetched for companies that clear the quality gate, unless
asked otherwise: there's no point pricing a business we wouldn't own.
The ranking sorts the gate-passers by expected annual return.
"""

import logging
from dataclasses import dataclass, field

import pandas as pd

from value_investor import config, macro, metrics, prices as px, rules, statements, store, valuation

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

    @property
    def passes_gate(self) -> bool:
        return (self.quality >= config.MIN_QUALITY and self.completeness >= config.MIN_COMPLETENESS
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
            "yearly": yearly,
        }

    def row(self) -> dict:
        v = self.valuation
        return {
            "cik": self.cik, "ticker": self.ticker, "name": self.name,
            "as_of": pd.Timestamp(self.as_of or pd.Timestamp.today()).date(),
            "profile": self.profile, "quality": self.quality, "completeness": self.completeness,
            "history_years": self.summary.get("history_years", 0),
            "price": v.get("price"), "expected_return": self.expected_return,
            "buy_price": v.get("buy_price"), "dividend_yield": v.get("dividend_yield"),
            "passes_gate": self.passes_gate, "payload": self.payload(),
        }


def _splits(facts: pd.DataFrame, priced: pd.DataFrame, as_of) -> pd.Series:
    """Splits from the filings, plus any newer split the filings can't know about yet."""
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

    priced = px.until(px.ensure(con, a.ticker), as_of) if (with_prices and a.ticker) else pd.DataFrame()
    splits = _splits(facts, priced, as_of)
    a.yearly = metrics.yearly(table, splits=splits)
    a.summary = metrics.summary(a.yearly)
    a.checks = rules.evaluate(a.summary, profile)
    a.quality, a.completeness = rules.score(a.checks)

    if profile == "financial":
        a.flags.append("financial company: shorter checklist")
    if a.summary.get("history_years", 0) < config.HISTORY_YEARS:
        a.flags.append(f"only {a.summary.get('history_years', 0)} years of XBRL history")
    if a.summary.get("shares_corrected"):
        a.flags.append("some share counts were rebuilt from net income / reported EPS (tagging error in the filing)")
    if a.yearly["eps"].isna().all():
        a.flags.append("no company-wide per-share data filed (usually several share classes)")
    shares = a.yearly["shares"].dropna()
    jumps = (shares / shares.shift(1)).dropna()
    if not jumps.empty and (jumps.max() > 1.8 or jumps.min() < 0.55):
        a.flags.append("unexplained jump in share count; per-share history may be off")

    if with_prices is None:
        with_prices = a.passes_gate
        if with_prices and a.ticker:
            return analyze(con, cik, as_of=as_of, with_prices=True, bond_yield=bond_yield)

    if with_prices:
        if a.currency and a.currency != "USD":
            a.valuation = {"available": False, "reason": f"reports in {a.currency}; ADR/FX valuation comes later"}
        else:
            a.valuation = valuation.value(a.yearly, a.summary, priced, bond_yield)
            if a.valuation.get("available") and a.summary.get("shares"):
                cap = a.valuation["price"] * a.summary["shares"]
                last = a.yearly.iloc[-1]
                net_buyback = (last.get("buybacks") or 0) - (last.get("stock_issued") or 0)
                a.valuation["market_cap"] = cap
                a.valuation["shareholder_yield"] = a.valuation["dividend_yield"] + net_buyback / cap
    return a


def run(ciks=None, as_of=None, with_prices: "bool | None" = None) -> pd.DataFrame:
    with store.connect() as con:
        if ciks is None:
            ciks = store.companies(con)["cik"].tolist()
        bond_yield, _ = macro.latest(con, "treasury_10y", as_of)
        bond_yield = bond_yield / 100.0 if bond_yield is not None else None
        results = []
        for i, cik in enumerate(ciks, start=1):
            try:
                a = analyze(con, int(cik), as_of=as_of, with_prices=with_prices, bond_yield=bond_yield)
                store.save_analysis(con, a.row())
            except Exception as exc:
                logger.warning("analysis failed for CIK %s: %s", cik, exc)
                continue
            results.append(a)
            if i % 250 == 0:
                logger.info("analysed %d / %d", i, len(ciks))
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
    df = df.assign(_has_return=df["expected_return"].notna())
    return (df.sort_values(["_has_return", "expected_return", "quality"], ascending=[False, False, False])
              .drop(columns="_has_return").reset_index(drop=True))
