"""07 · statements — raw facts -> one row per fiscal year.

Two traps in companyfacts drive the design:

  * `fy` is the fiscal year of the *filing*, not of the number. A 10-K for
    2024 carries 2022 and 2023 comparatives tagged fy=2024. Years are keyed
    by period end date instead.
  * Numbers get restated. Each (concept, period) keeps the latest value
    filed on or before `as_of`, so a backtest sees what was known then and
    today's run sees the restated figure.

Per-share values and share counts keep their filing date (`*_filed`),
because a number filed before a stock split is in pre-split units.
metrics.py uses that to put everything into today's share units.
"""

import pandas as pd

from value_investor import concepts

YEAR_MIN_DAYS = 330
YEAR_MAX_DAYS = 400
INSTANT_TOLERANCE_DAYS = 7

TRACK_FILED = concepts.PER_SHARE | concepts.SHARE_COUNTS


def _taxonomy_order(facts: pd.DataFrame) -> list:
    anchors = facts[facts["concept"].isin(["NetIncomeLoss", "ProfitLoss", "ProfitLossAttributableToOwnersOfParent"])]
    if anchors.empty:
        anchors = facts
    latest = anchors.sort_values("filed").iloc[-1]["taxonomy"]
    others = [t for t in ("us-gaap", "ifrs-full") if t != latest]
    return [latest] + others


def _currency(facts: pd.DataFrame, taxonomy: str) -> "str | None":
    pool = facts[(facts["taxonomy"] == taxonomy) & ~facts["unit"].str.contains("/", na=False)
                 & (facts["unit"] != "shares")]
    if pool.empty:
        return None
    return pool["unit"].value_counts().idxmax()


def _index(frame: pd.DataFrame, duration: bool) -> dict:
    """(taxonomy, concept) -> {period_end: (value, filed)}."""
    out: dict = {}
    for row in frame.itertuples(index=False):
        bucket = out.setdefault((row.taxonomy, row.concept), {})
        if duration:
            current = bucket.get(row.period_end)
            closeness = abs(row.days - 365)
            if current is not None and current[2] < closeness:
                continue
            bucket[row.period_end] = (row.value, row.filed, closeness)
        else:
            bucket[row.period_end] = (row.value, row.filed, 0)
    return out


def _lookup(index: dict, key: tuple, end, tolerance: int):
    bucket = index.get(key)
    if not bucket:
        return None
    hit = bucket.get(end)
    if hit is not None or tolerance == 0:
        return hit
    best = None
    for other_end, hit in bucket.items():
        gap = abs((other_end - end).days)
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, hit)
    return None if best is None else best[1]


def _pick(field: str, end, taxonomies: list, index: dict):
    is_instant = concepts.kind(field) == concepts.INSTANT
    tolerance = INSTANT_TOLERANCE_DAYS if is_instant else 0
    for taxonomy in taxonomies:
        for alt in concepts.alternatives(field, taxonomy):
            if isinstance(alt, tuple):
                parts = [_lookup(index, (taxonomy, name), end, tolerance) for name in alt[1]]
                parts = [p for p in parts if p is not None]
                if parts:
                    return sum(p[0] for p in parts), max(p[1] for p in parts)
                continue
            hit = _lookup(index, (taxonomy, alt), end, tolerance)
            if hit is not None:
                return hit[0], hit[1]
    return None, None


def _fiscal_year_ends(index: dict, taxonomies: list) -> list:
    ends = set()
    for taxonomy in taxonomies:
        for field in ("net_income", "revenue"):
            for alt in concepts.alternatives(field, taxonomy):
                if isinstance(alt, str):
                    ends.update(index.get((taxonomy, alt), {}).keys())
    kept: list = []
    for end in sorted(ends):
        # A fiscal-year change leaves two overlapping "years"; keep the later one.
        while kept and (end - kept[-1]).days < 300:
            kept.pop()
        kept.append(end)
    return kept


SPLIT_RATIOS = (1.5, 2, 2.5, 3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30, 40, 50, 100)
SHARE_CONCEPTS = {"WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic",
                  "WeightedAverageNumberOfShareOutstandingBasicAndDiluted", "AdjustedWeightedAverageShares",
                  "WeightedAverageShares"}
# EPS moves the other way: a 4-for-1 split divides restated EPS by four.
EPS_CONCEPTS = {"EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted", "DilutedEarningsLossPerShare",
                "BasicAndDilutedEarningsLossPerShare"}


def _clean_ratio(r: float) -> "float | None":
    flipped = r < 1
    x = 1 / r if flipped else r
    for nice in SPLIT_RATIOS:
        if abs(x - nice) / nice < 0.03:
            return 1 / nice if flipped else float(nice)
    return None


def inferred_splits(facts: pd.DataFrame, as_of=None) -> pd.Series:
    """Splits read off the filings themselves.

    When a company splits its stock, the next annual report restates the
    share counts of earlier years. The same period then shows up twice, once
    per filing, at a clean ratio like 4.0 or 0.1. The split is dated at the
    first filing that carries the restated number, which is exactly the
    boundary metrics.split_factors needs.
    """
    shares = facts["concept"].isin(SHARE_CONCEPTS) & (facts["unit"] == "shares")
    eps = facts["concept"].isin(EPS_CONCEPTS) & facts["unit"].str.endswith("/shares", na=False)
    f = facts[shares | eps]
    if as_of is not None:
        f = f[pd.to_datetime(f["filed"]) <= pd.Timestamp(as_of)]
    events: dict = {}
    for (concept, _, _), group in f.groupby(["concept", "period_start", "period_end"]):
        if len(group) < 2:
            continue
        inverse = concept in EPS_CONCEPTS
        group = group.sort_values("filed")
        values, filed = group["value"].tolist(), group["filed"].tolist()
        for prev, cur, when in zip(values, values[1:], filed[1:]):
            if inverse and (abs(prev) < 0.1 or abs(cur) < 0.1 or prev * cur <= 0):
                continue
            if not inverse and (prev <= 0 or cur <= 0):
                continue
            ratio = _clean_ratio(prev / cur if inverse else cur / prev)
            if ratio is not None and (ratio >= 1.4 or ratio <= 0.7):
                events.setdefault(pd.Timestamp(when), []).append(ratio)
    if not events:
        return pd.Series(dtype=float)
    return pd.Series({when: float(pd.Series(r).median()) for when, r in events.items()}).sort_index()


def annual_statements(facts: pd.DataFrame, as_of=None) -> pd.DataFrame:
    """One row per fiscal year, indexed by period end. attrs: currency, taxonomy."""
    if facts.empty:
        return pd.DataFrame()
    f = facts
    if as_of is not None:
        f = f[pd.to_datetime(f["filed"]) <= pd.Timestamp(as_of)]
        if f.empty:
            return pd.DataFrame()

    taxonomies = _taxonomy_order(f)
    currency = _currency(f, taxonomies[0])
    if currency is None:
        return pd.DataFrame()
    f = f[f["unit"].isin({currency, f"{currency}/shares", "shares"})].copy()
    f["period_end"] = pd.to_datetime(f["period_end"])
    f["period_start"] = pd.to_datetime(f["period_start"])
    f["filed"] = pd.to_datetime(f["filed"])

    durations = f[f["period_start"].notna()].copy()
    durations["days"] = (durations["period_end"] - durations["period_start"]).dt.days
    durations = durations[durations["days"].between(YEAR_MIN_DAYS, YEAR_MAX_DAYS)]
    durations = durations.sort_values("filed").drop_duplicates(
        ["taxonomy", "concept", "unit", "period_start", "period_end"], keep="last")

    instants = f[f["period_start"].isna()]
    instants = instants.sort_values("filed").drop_duplicates(
        ["taxonomy", "concept", "unit", "period_end"], keep="last")

    duration_index = _index(durations, duration=True)
    instant_index = _index(instants, duration=False)

    rows = []
    for end in _fiscal_year_ends(duration_index, taxonomies):
        row = {"period_end": end}
        for field in concepts.FIELDS:
            index = instant_index if concepts.kind(field) == concepts.INSTANT else duration_index
            value, filed = _pick(field, end, taxonomies, index)
            if value is not None and field in concepts.ALWAYS_POSITIVE:
                value = abs(value)
            row[field] = value
            if field in TRACK_FILED:
                row[f"{field}_filed"] = filed
        rows.append(row)

    table = pd.DataFrame(rows).set_index("period_end").sort_index()
    table = table.astype({c: "float64" for c in concepts.FIELDS})

    missing_gp = table["gross_profit"].isna() & table["revenue"].notna() & table["cost_of_revenue"].notna()
    table.loc[missing_gp, "gross_profit"] = table["revenue"] - table["cost_of_revenue"]
    missing_liab = (table["total_liabilities"].isna() & table["liabilities_and_equity"].notna()
                    & table["equity_incl_nci"].notna())
    table.loc[missing_liab, "total_liabilities"] = table["liabilities_and_equity"] - table["equity_incl_nci"]

    table.attrs["currency"] = currency
    table.attrs["taxonomy"] = taxonomies[0]
    return table
