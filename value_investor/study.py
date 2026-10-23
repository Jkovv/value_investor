"""37 · study: would the ranking have picked the better companies?

every june from 2010 each company is scored again with only what was known then:
statements filed by that day, prices up to it, that month's bond yield. the score is
set against what the shares returned over the next one and three years, dividends
reinvested, in the currency they trade in. a company is only compared with the others
in its market that year, so how the whole market did drops out.

free price data only has companies that are still listed. one that went bust or was
taken over since is missing, which flatters every group and the weak ones most, as
they disappear more often; the gaps measured here are between survivors.
"""

import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime

import duckdb
import numpy as np
import pandas as pd

from value_investor import config, screener, store

logger = logging.getLogger(__name__)

DIR = config.DATA_DIR / "study"
FIRST_YEAR = 2010
HORIZONS = (1, 3)
MIN_GROUP = 20          # companies a market needs in a year to be ranked against each other
TOLERANCE_DAYS = 7      # how far a price may be from the day it stands for
SIGNALS = {"quality": "Quality score", "expected_return": "Expected return", "f_score": "Piotroski F-score"}
BUCKETS = [-np.inf, 0.0, 0.05, 0.10, 0.15, 0.20, np.inf]
BUCKET_NAMES = ["below 0%", "0 to 5%", "5 to 10%", "10 to 15%", "15 to 20%", "above 20%"]


def formation_dates(today=None) -> list:
    today = pd.Timestamp(today or date.today())
    return [pd.Timestamp(y, 6, 30) for y in range(FIRST_YEAR, today.year + 1) if pd.Timestamp(y, 6, 30) <= today]


def total_return_index(prices: pd.DataFrame) -> pd.Series:
    """a share's value with its dividends put back in, from yahoo's split-adjusted closes."""
    p = prices.dropna(subset=["close"])
    p = p[p["close"] > 0]
    if p.empty:
        return pd.Series(dtype=float)
    close = p["close"].to_numpy(dtype=float)
    dividend = p["dividend"].fillna(0).to_numpy(dtype=float)
    step = np.ones(len(close))
    step[1:] = (close[1:] + dividend[1:]) / close[:-1]
    return pd.Series(np.cumprod(step), index=pd.DatetimeIndex(p["date"]))


def _on(tri: pd.Series, when: pd.Timestamp) -> "float | None":
    before = tri[tri.index <= when]
    if before.empty or (when - before.index[-1]).days > TOLERANCE_DAYS:
        return None
    return float(before.iloc[-1])


def forward_return(tri: pd.Series, start, years: int) -> "float | None":
    start = pd.Timestamp(start)
    end = start + pd.DateOffset(years=years)
    if tri.empty or end > tri.index[-1] + pd.Timedelta(days=TOLERANCE_DAYS):
        return None
    a, b = _on(tri, start), _on(tri, end)
    return None if a is None or b is None else b / a - 1


def years_filed(facts: pd.DataFrame, when) -> int:
    """fiscal years with a full-year figure filed by `when`, a cheap check before scoring."""
    f = facts[pd.to_datetime(facts["filed"]) <= pd.Timestamp(when)]
    f = f[f["period_start"].notna()]
    if f.empty:
        return 0
    days = (pd.to_datetime(f["period_end"]) - pd.to_datetime(f["period_start"])).dt.days
    return int(pd.to_datetime(f.loc[days.between(330, 400), "period_end"]).dt.year.nunique())


def score_company(con, cik: int, dates: list) -> list:
    """one row per date the company could be scored on, with what its shares did next."""
    comp = store.company(con, cik) or {}
    ticker = comp.get("ticker")
    if not ticker:
        return []
    prices = store.load_prices(con, ticker)
    if prices.empty:
        return []
    prices["date"] = pd.to_datetime(prices["date"])
    tri = total_return_index(prices)
    facts = store.load_facts(con, cik)
    rows = []
    for d in dates:
        if prices["date"].iloc[0] > d - pd.Timedelta(days=365) or years_filed(facts, d) < config.MIN_HISTORY_YEARS:
            continue
        returns = {f"r{h}": forward_return(tri, d, h) for h in HORIZONS}
        if returns["r1"] is None:
            continue
        a = screener.analyze(con, cik, as_of=d, with_prices=True, facts=facts, prices=prices, light=True)
        if not a.summary:
            continue
        rows.append({
            "cik": cik, "ticker": ticker, "market": comp.get("market"), "date": d.date(), "profile": a.profile,
            "quality": a.quality, "completeness": a.completeness, "history_years": a.summary.get("history_years", 0),
            "gate": a.passes_gate, "rankable": a.rankable, "expected_return": a.expected_return,
            "f_score": (a.lenses.get("piotroski") or {}).get("score"), **returns,
        })
    return rows


_con = None


def _start_worker() -> None:
    global _con
    logging.getLogger().setLevel(logging.ERROR)
    _con = duckdb.connect(str(config.DB_PATH), read_only=True)


def _score(cik: int, dates: list) -> list:
    try:
        return score_company(_con, cik, dates)
    except Exception as exc:
        return [{"cik": cik, "error": str(exc)[:200]}]


def universe(con) -> list:
    """companies with more history than yahoo's four years; the rest can't be scored back then."""
    return [r[0] for r in con.execute("""
        SELECT DISTINCT f.cik FROM facts f WHERE f.taxonomy <> 'yahoo' ORDER BY 1
    """).fetchall()]


def build_panel(workers: "int | None" = None, ciks=None) -> pd.DataFrame:
    dates = formation_dates()
    with store.connect(read_only=True) as con:
        ciks = universe(con) if ciks is None else ciks
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    rows, failed = [], 0
    with ProcessPoolExecutor(max_workers=workers, initializer=_start_worker) as pool:
        futures = [pool.submit(_score, int(c), dates) for c in ciks]
        for i, fut in enumerate(as_completed(futures), start=1):
            for row in fut.result():
                if "error" in row:
                    failed += 1
                else:
                    rows.append(row)
            if i % 250 == 0 or i == len(futures):
                logger.info("study: %d / %d companies, %d company-years", i, len(futures), len(rows))
    if failed:
        logger.warning("study: %d companies failed", failed)
    return pd.DataFrame(rows)


# statistics

def _spearman(x: pd.Series, y: pd.Series) -> float:
    return float(np.corrcoef(x.rank(), y.rank())[0, 1])


def newey_west_t(values, lags: int) -> "float | None":
    """t-statistic of a mean whose observations overlap (three-year returns started a year apart)."""
    x = np.asarray(values, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return None
    e = x - x.mean()
    var = e @ e / n
    for lag in range(1, min(lags, n - 1) + 1):
        var += 2 * (1 - lag / (lags + 1)) * (e[lag:] @ e[:-lag]) / n
    return float(x.mean() / np.sqrt(var / n)) if var > 0 else None


def cross_sections(panel: pd.DataFrame, signal: str, horizon: int, subset=None) -> pd.DataFrame:
    """per market and year: rank correlation of the signal with what came next, and the
    average return of each fifth against the market's average that year."""
    ret = f"r{horizon}"
    df = panel if subset is None else panel[subset]
    df = df.dropna(subset=[signal, ret])
    out = []
    for (market, when), g in df.groupby(["market", "date"]):
        if len(g) < MIN_GROUP or g[signal].nunique() < 5:
            continue
        excess = g[ret] - g[ret].mean()
        fifths = pd.qcut(g[signal].rank(method="first"), 5, labels=False) + 1
        means = excess.groupby(fifths).mean()
        out.append({"market": market, "date": when, "n": len(g), "ic": _spearman(g[signal], g[ret]),
                    **{f"q{q}": float(means.get(q, np.nan)) for q in range(1, 6)},
                    "spread": float(means.get(5, np.nan) - means.get(1, np.nan))})
    return pd.DataFrame(out)


def summarise(cs: pd.DataFrame, horizon: int) -> dict:
    """pooled over markets: each year's markets averaged first, then the years, with t-statistics
    that allow for overlapping holding periods."""
    if cs.empty:
        return {}
    by_year = cs.groupby("date")[["ic", "spread", "q1", "q2", "q3", "q4", "q5"]].mean()
    lags = horizon - 1
    pooled = {"years": int(len(by_year)), "markets": int(cs["market"].nunique()), "groups": int(len(cs)),
              "company_years": int(cs["n"].sum()), "ic": float(by_year["ic"].mean()),
              "ic_t": newey_west_t(by_year["ic"], lags), "ic_positive": float((cs["ic"] > 0).mean()),
              "spread": float(by_year["spread"].mean()), "spread_t": newey_west_t(by_year["spread"], lags),
              "fifths": [float(by_year[f"q{q}"].mean()) for q in range(1, 6)],
              "ic_by_year": {str(d): float(v) for d, v in by_year["ic"].items()}}
    markets = {}
    for market, g in cs.groupby("market"):
        markets[market] = {"years": int(len(g)), "company_years": int(g["n"].sum()), "ic": float(g["ic"].mean()),
                           "ic_t": newey_west_t(g.sort_values("date")["ic"], lags),
                           "spread": float(g["spread"].mean())}
    return {"pooled": pooled, "markets": markets}


def gate_gap(panel: pd.DataFrame, horizon: int) -> dict:
    """what passing the checklist was worth: passers against the rest of their market that year."""
    ret = f"r{horizon}"
    gaps = []
    for (market, when), g in panel.dropna(subset=[ret]).groupby(["market", "date"]):
        passed, failed = g.loc[g["gate"], ret], g.loc[~g["gate"], ret]
        if len(g) >= MIN_GROUP and len(passed) >= 5 and len(failed) >= 5:
            gaps.append({"date": when, "market": market, "gap": float(passed.mean() - failed.mean()),
                         "share": float(len(passed) / len(g))})
    if not gaps:
        return {}
    df = pd.DataFrame(gaps)
    by_year = df.groupby("date")["gap"].mean()
    return {"groups": int(len(df)), "gap": float(by_year.mean()), "t": newey_west_t(by_year, horizon - 1),
            "passing_share": float(df["share"].mean())}


def calibration(panel: pd.DataFrame, horizon: int = 3) -> list:
    """companies that passed, by the yearly return their price promised, against what they then
    returned a year, and against their market's average that year."""
    ret = f"r{horizon}"
    df = panel.dropna(subset=[ret]).copy()
    df["realised"] = (1 + df[ret]).clip(lower=0) ** (1 / horizon) - 1
    df["excess"] = df["realised"] - df.groupby(["market", "date"])["realised"].transform("mean")
    df = df[df["gate"] & df["expected_return"].notna()]
    df["bucket"] = pd.cut(df["expected_return"], BUCKETS, labels=BUCKET_NAMES)
    out = []
    for name, g in df.groupby("bucket", observed=True):
        out.append({"bucket": str(name), "n": int(len(g)), "promised": float(g["expected_return"].median()),
                    "realised": float(g["realised"].median()), "excess": float(g["excess"].mean())})
    return out


def results(panel: pd.DataFrame) -> dict:
    panel = panel[panel["rankable"]]
    out = {"run_at": datetime.now().isoformat(timespec="minutes"), "company_years": int(len(panel)),
           "companies": int(panel["cik"].nunique()), "markets": sorted(panel["market"].dropna().unique().tolist()),
           "first": str(panel["date"].min()), "last": str(panel["date"].max()), "signals": {}}
    for signal in SIGNALS:
        out["signals"][signal] = {}
        for h in HORIZONS:
            subset = panel["gate"] if signal == "expected_return" else None
            out["signals"][signal][f"{h}y"] = summarise(cross_sections(panel, signal, h, subset), h)
    out["gate"] = {f"{h}y": gate_gap(panel, h) for h in HORIZONS}
    out["calibration"] = calibration(panel, 3)
    out["coverage"] = (panel.groupby("market").agg(company_years=("cik", "size"), companies=("cik", "nunique"),
                                                   first=("date", "min"))
                       .reset_index().astype({"first": str}).to_dict(orient="records"))
    return out


def save(panel: pd.DataFrame, res: dict) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(DIR / "panel.parquet", index=False)
    (DIR / "results.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


def load_panel() -> "pd.DataFrame | None":
    path = DIR / "panel.parquet"
    return pd.read_parquet(path) if path.exists() else None


# charts for the write-up, in the dashboard's own colours

INK, INK_2, GRID, AXIS = "#111114", "#55555f", "#e6e6e9", "#d4d4d9"
BLUE, ORANGE = "#2a78d6", "#eb6834"


def _style(ax) -> None:
    ax.set_facecolor("white")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK_2, length=0, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _pct_axis(ax, digits: int = 0) -> None:
    from matplotlib.ticker import FuncFormatter
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.{digits}f}%"))


def figures(res: dict, out_dir) -> list:
    """three charts for docs/: the fifths, the yearly rank correlation, promised against delivered."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from matplotlib import font_manager
    installed = {f.name for f in font_manager.fontManager.ttflist}
    family = [f for f in ("Segoe UI", "Inter") if f in installed] + ["DejaVu Sans"]
    plt.rcParams.update({"font.family": family, "text.color": INK,
                         "axes.labelcolor": INK_2, "figure.facecolor": "white"})
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []

    panels = [(s, label) for s, label in SIGNALS.items() if (res["signals"][s].get("1y") or {}).get("pooled")]
    if panels:
        fig, axes = plt.subplots(1, len(panels), figsize=(3.4 * len(panels), 3.4), sharey=True)
        axes = np.atleast_1d(axes)
        for ax, (signal, label) in zip(axes, panels):
            p = res["signals"][signal]["1y"]["pooled"]
            values = p["fifths"]
            ax.bar(range(5), values, width=0.62, color=BLUE)
            for i, v in enumerate(values):
                text = f"{v * 100:+.1f}%" if abs(v) >= 0.0005 else "0.0%"
                ax.annotate(text, (i, v), xytext=(0, 4 if v >= 0 else -12), textcoords="offset points",
                            ha="center", fontsize=8.5, color=INK)
            ax.axhline(0, color=AXIS, linewidth=1)
            ax.set_xticks(range(5), ["Lowest", "2", "3", "4", "Highest"])
            title = label if signal != "expected_return" else f"{label}, passers"
            t = f", t {p['ic_t']:.1f}" if p.get("ic_t") is not None else ""
            ax.set_title(f"{title}\nrank corr. {p['ic']:.3f}{t}", fontsize=10, color=INK, loc="left")
            ax.margins(y=0.16)
            _style(ax)
        _pct_axis(axes[0], 1)
        axes[0].set_ylabel("next year's return less the market's")
        fig.tight_layout()
        path = out_dir / "study_fifths.png"
        fig.savefig(path, dpi=200)
        plt.close(fig)
        made.append(path)

    series = [("quality", BLUE), ("expected_return", ORANGE)]
    lines = [(s, c, res["signals"][s]["1y"]["pooled"]["ic_by_year"]) for s, c in series
             if (res["signals"][s].get("1y") or {}).get("pooled")]
    if lines:
        from matplotlib.ticker import MaxNLocator
        fig, ax = plt.subplots(figsize=(8, 3.6))
        for signal, colour, by_year in lines:
            years = [int(d[:4]) for d in by_year]
            ax.plot(years, list(by_year.values()), color=colour, linewidth=2, marker="o", markersize=4.5,
                    label=SIGNALS[signal] + (", passers" if signal == "expected_return" else ""))
        ax.axhline(0, color=AXIS, linewidth=1)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.set_ylabel("rank correlation with\nnext year's return")
        ax.legend(frameon=False, fontsize=9, loc="upper left", bbox_to_anchor=(0, -0.1), ncol=2)
        _style(ax)
        ax.margins(x=0.04, y=0.15)
        fig.tight_layout()
        path = out_dir / "study_by_year.png"
        fig.savefig(path, dpi=200)
        plt.close(fig)
        made.append(path)

    cal = res.get("calibration") or []
    if cal:
        fig, ax = plt.subplots(figsize=(8, 3.4))
        x = np.arange(len(cal))
        w = 0.36
        ax.bar(x - w / 2 - 0.01, [c["realised"] for c in cal], width=w, color=BLUE, label="delivered a year")
        ax.bar(x + w / 2 + 0.01, [c["excess"] for c in cal], width=w, color=ORANGE, label="against their market")
        ax.axhline(0, color=AXIS, linewidth=1)
        ax.set_xticks(x, [f"{c['bucket']}\n{c['n']:,} cases" for c in cal])
        ax.set_xlabel("yearly return the price promised, companies that passed the checklist", color=INK_2)
        _pct_axis(ax)
        ax.legend(frameon=False, fontsize=9, loc="upper left")
        _style(ax)
        fig.tight_layout()
        path = out_dir / "study_calibration.png"
        fig.savefig(path, dpi=200)
        plt.close(fig)
        made.append(path)
    return made
