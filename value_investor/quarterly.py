"""24 · quarterly: the last quarters, each against the same one a year earlier.

10-Qs file three-month and year-to-date figures and there's no 10-Q for the
fourth quarter, so missing quarters come from running totals (Q4 = year
minus nine months). yahoo gives five quarters directly.
"""

import pandas as pd

from value_investor import concepts, statements

FIELDS = ("revenue", "gross_profit", "operating_income", "net_income", "eps_diluted",
          "operating_cash_flow", "capex")
# wide enough for 12- and 16-week retail quarters (PepsiCo files 84, 84, 84 and 112 days)
QUARTER = (75, 120)
RUNNING = ((160, 200), (245, 285), (330, 400))
YEAR = (330, 400)


def _within(days: int, span: tuple) -> bool:
    return span[0] <= days <= span[1]


def _prepared(quarterly: pd.DataFrame, annual: pd.DataFrame, currency: str, as_of) -> pd.DataFrame:
    f = pd.concat([quarterly, annual], ignore_index=True) if not annual.empty else quarterly.copy()
    if f.empty:
        return f
    f = f[f["period_start"].notna() & f["unit"].isin({currency, f"{currency}/shares"})].copy()
    for col in ("period_start", "period_end", "filed"):
        f[col] = pd.to_datetime(f[col])
    if as_of is not None:
        f = f[f["filed"] <= pd.Timestamp(as_of)]
    f["days"] = (f["period_end"] - f["period_start"]).dt.days
    return (f.sort_values("filed")
             .drop_duplicates(["taxonomy", "concept", "period_start", "period_end"], keep="last"))


def _values(f: pd.DataFrame, field: str, taxonomies: list) -> dict:
    """(start, end) -> value, taking the first tag in preference order that has the period."""
    by_concept = {(t, c): dict(zip(zip(g["period_start"], g["period_end"]), g["value"]))
                  for (t, c), g in f.groupby(["taxonomy", "concept"])}
    out: dict = {}
    for taxonomy in taxonomies:
        for alt in concepts.alternatives(field, taxonomy):
            names = alt[1] if isinstance(alt, tuple) else [alt]
            parts = [by_concept.get((taxonomy, n), {}) for n in names]
            for period in set().union(*parts) if parts else ():
                if period in out:
                    continue
                if isinstance(alt, tuple):
                    out[period] = sum(p[period] for p in parts if period in p)
                else:
                    out[period] = parts[0][period]
    return out


def _quarters(values: dict) -> dict:
    """quarter end -> value, direct where filed, else from running totals."""
    direct = {end: v for (start, end), v in values.items() if _within((end - start).days, QUARTER)}
    out = dict(direct)
    years: dict = {}
    for (start, end), v in values.items():
        days = (end - start).days
        if _within(days, QUARTER) or any(_within(days, span) for span in RUNNING):
            years.setdefault(start, {})[end] = v
    for start, running in years.items():
        # only fiscal years: a run that starts here must reach a full year or be a known quarter
        if not any(_within((end - start).days, YEAR) for end in running) and len(running) < 2:
            continue
        before, before_end = 0.0, start
        for end in sorted(running):
            if end not in out and _within((end - before_end).days, QUARTER):
                out[end] = running[end] - before
            before, before_end = running[end], end
    return out


def table(quarterly: pd.DataFrame, annual: pd.DataFrame, currency: "str | None", as_of=None) -> pd.DataFrame:
    if quarterly is None or quarterly.empty or not currency:
        return pd.DataFrame()
    f = _prepared(quarterly, annual if annual is not None else pd.DataFrame(), currency, as_of)
    if f.empty:
        return pd.DataFrame()
    taxonomies = statements._taxonomy_order(f)
    columns = {field: _quarters(_values(f, field, taxonomies)) for field in FIELDS}
    ends = sorted(set(columns["revenue"]) | set(columns["net_income"]))
    if not ends:
        return pd.DataFrame()
    t = pd.DataFrame({field: [columns[field].get(e) for e in ends] for field in FIELDS},
                     index=pd.DatetimeIndex(ends)).astype(float)
    # neighbouring ends a few days apart are the same quarter tagged twice
    t = t[~(t.index.to_series().diff().dt.days < 40)]
    t["capex"] = t["capex"].abs()
    t["gross_margin"] = t["gross_profit"] / t["revenue"]
    t["operating_margin"] = t["operating_income"] / t["revenue"]
    t["fcf"] = t["operating_cash_flow"] - t["capex"].fillna(0)
    for col in ("revenue", "net_income", "operating_income"):
        t[f"{col}_yoy"] = [_yoy(t[col], end) for end in t.index]
    return t


def _yoy(s: pd.Series, end) -> "float | None":
    now = s.get(end)
    then = s[(s.index >= end - pd.Timedelta(days=390)) & (s.index <= end - pd.Timedelta(days=340))].dropna()
    if now is None or pd.isna(now) or then.empty or then.iloc[-1] <= 0:
        return None
    return float(now / then.iloc[-1] - 1)


def _num(v) -> "float | None":
    return None if v is None or pd.isna(v) else float(v)


def summary(t: pd.DataFrame, annual_net_income: "float | None" = None) -> dict:
    if t.empty:
        return {}
    last = t.iloc[-1]
    s = {"last_end": t.index[-1].date().isoformat(), "quarters": len(t),
         "revenue_yoy": _num(last.revenue_yoy), "net_income_yoy": _num(last.net_income_yoy),
         "gross_margin": _num(last.gross_margin), "operating_margin": _num(last.operating_margin)}
    year = t.tail(4)
    if len(year) == 4 and 250 <= (year.index[-1] - year.index[0]).days <= 300:
        for col in ("revenue", "net_income", "operating_cash_flow", "fcf"):
            s[f"ttm_{col}"] = _num(year[col].sum(min_count=4))
        if annual_net_income and annual_net_income > 0 and s.get("ttm_net_income") is not None:
            s["ttm_vs_year"] = s["ttm_net_income"] / annual_net_income - 1
    recent = t.tail(4)
    rev, ni = recent["revenue_yoy"].dropna(), recent["net_income_yoy"].dropna()
    s["revenue_up"], s["revenue_known"] = int((rev > 0).sum()), len(rev)
    s["net_income_up"], s["net_income_known"] = int((ni > 0).sum()), len(ni)
    s["trend"] = trend(t)
    s["stale"] = (pd.Timestamp.today() - t.index[-1]).days > 200
    return s


def trend(t: pd.DataFrame) -> "str | None":
    """growing, mixed or slipping, from the last two quarters against a year earlier."""
    last2 = t.tail(2)
    rev, ni = last2["revenue_yoy"], last2["net_income_yoy"]
    if rev.notna().sum() < 2 and ni.notna().sum() < 2:
        return None
    if (ni.notna().all() and (ni < -0.05).all()) or (rev.notna().all() and (rev < 0).all()):
        return "slipping"
    if rev.notna().all() and (rev > 0).all() and ni.notna().all() and (ni > 0).all():
        return "growing"
    return "mixed"


def rows(t: pd.DataFrame, n: int) -> list:
    keep = ["revenue", "gross_margin", "operating_margin", "net_income", "eps_diluted", "fcf",
            "revenue_yoy", "net_income_yoy"]
    out = t.tail(n)[keep].copy()
    out.index = out.index.strftime("%Y-%m-%d")
    return [{k: (None if pd.isna(v) else float(v)) for k, v in r.items()} | {"end": end}
            for end, r in out.iterrows()]
