"""main.py: command line: screen, rank, look at one company, check the market.

run `python ingest.py` first, then:

  python main.py screen                  # score every ingested company, price the ones that pass
  python main.py screen --tickers KO V   # just these, always priced
  python main.py rank                    # the last ranking, best expected return first
  python main.py show KO                 # checklist, valuation and ten years of ratios
  python main.py macro                   # rates, Market Cap / GDP, suggested cash share
  python main.py audit                   # how each history source agrees with yahoo, line by line
  python main.py study                   # would the ranking have picked the better companies?
  python main.py evals                   # do the research briefs say what their sources say?
"""

import argparse
import sys

from rich.console import Console
from rich.table import Table

from value_investor import audit, config, macro, screener, store, study
from value_investor.logging_config import configure_logging

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
console = Console(legacy_windows=False)

STATUS_STYLE = {"pass": "green", "warn": "yellow", "fail": "red", "na": "dim"}


def pct(v, digits=1):
    return "-" if v is None or v != v else f"{v * 100:.{digits}f}%"


def money(v):
    return "-" if v is None or v != v else f"{v:,.2f}"


def ranking_table(df, top: int) -> Table:
    t = Table(title="Ranking: gate passers by expected yearly return", header_style="bold")
    for col, justify in [("#", "right"), ("Ticker", "left"), ("Company", "left"), ("Mkt", "left"),
                         ("Quality", "right"), ("Price", "right"), ("Buy below", "right"),
                         ("Return", "right"), ("Yield", "right")]:
        t.add_column(col, justify=justify)
    for i, r in df.head(top).iterrows():
        ccy = r.get("currency") if isinstance(r.get("currency"), str) else ""
        mkt = r.get("market") if isinstance(r.get("market"), str) else ""
        t.add_row(str(i + 1), r["ticker"] or "", (r["name"] or "")[:30], mkt,
                  f"{r['quality']:.0f}", f"{money(r['price'])} {ccy}", money(r["buy_price"]),
                  pct(r["expected_return"]), pct(r["dividend_yield"]))
    return t


def cmd_screen(args):
    with store.connect() as con:
        if args.tickers:
            ciks = [store.find_cik(con, t) for t in args.tickers]
            missing = [t for t, c in zip(args.tickers, ciks) if c is None]
            if missing:
                console.print(f"[yellow]Not ingested yet: {', '.join(missing)}. Run ingest.py --tickers ...[/]")
            ciks = [c for c in ciks if c is not None]
        else:
            ciks = None
    with_prices = True if args.tickers else None
    if args.no_prices:
        with_prices = False
    results = screener.run(ciks=ciks, with_prices=with_prices)
    if results.empty:
        console.print("Nothing to screen. Run ingest.py first.")
        return
    passed = int(results["passes_gate"].sum())
    console.print(f"Screened {len(results)} companies, {passed} passed the quality gate "
                  f"(score ≥ {config.MIN_QUALITY:.0f}, data ≥ {config.MIN_COMPLETENESS:.0%}).")
    cmd_rank(args)


def cmd_rank(args):
    with store.connect(read_only=True) as con:
        df = screener.ranking(con, only_gate=not args.all)
    if df.empty:
        console.print("No ranking yet. Run `python main.py screen`.")
        return
    console.print(ranking_table(df, args.top))


def cmd_show(args):
    with store.connect() as con:
        cik = store.find_cik(con, args.ticker)
        if cik is None:
            console.print(f"{args.ticker} isn't ingested. Run: python ingest.py --tickers {args.ticker}")
            return
        bond, _ = macro.latest(con, "treasury_10y")
        a = screener.analyze(con, cik, with_prices=True, bond_yield=bond / 100 if bond else None)
        store.save_analysis(con, a.row())

    console.print(f"\n[bold]{a.name}[/] ({a.ticker}) · {a.company.get('sic_description') or ''} · "
                  f"{a.company.get('country') or ''} · reports in {a.currency}")
    console.print(f"Quality [bold]{a.quality:.0f}[/]/100 · data coverage {a.completeness:.0%} · "
                  f"{a.summary.get('history_years', 0)} years · profile: {a.profile}"
                  f" · {'passes' if a.passes_gate else 'does not pass'} the gate")
    for flag in a.flags:
        console.print(f"[yellow]! {flag}[/]")

    checks = Table(header_style="bold", title="Checklist")
    for col in ("Area", "Check", "Value", "Result", "Why it matters"):
        checks.add_column(col)
    for ch in a.checks:
        style = STATUS_STYLE[ch.status]
        checks.add_row(ch.group, ch.label, ch.shown, f"[{style}]{ch.status}[/]", ch.note)
    console.print(checks)

    v = a.valuation
    if v.get("available"):
        er = v["expected_return"]
        console.print(
            f"\nPrice {money(v['price'])} ({v['price_date']}) · P/E {v['pe_now']:.1f} · "
            f"initial return {pct(v['initial_return'])} vs 10y Treasury {pct(v['bond_yield'])}\n"
            f"Growth used {pct(v['growth'])} (history {pct(v['growth_inputs']['historical'])}, "
            f"ROE×retention {pct(v['growth_inputs']['sustainable'])}) · "
            f"P/E {v['pe']['low']:.1f}/{v['pe']['mid']:.1f}/{v['pe']['high']:.1f} ({v['pe_source']})\n"
            f"Expected annual return [bold]{pct(er['mid'])}[/] (range {pct(er['low'])} to {pct(er['high'])}) · "
            f"buy below [bold]{money(v['buy_price'])}[/] for {config.HURDLE_RATE:.0%} a year · "
            f"dividend yield {pct(v['dividend_yield'])}"
        )
        if v.get("sell_signal"):
            console.print("[red]P/E is at or above 40: the sell rule applies.[/]")
    else:
        console.print(f"\nNo valuation: {v.get('reason', 'not run')}")

    years = Table(header_style="bold", title="By year")
    cols = [("fiscal_year", "FY", str), ("gross_margin", "GM", pct), ("sga_to_gp", "SGA/GP", pct),
            ("net_margin", "Net", pct), ("roe", "ROE", pct), ("eps", "EPS", money), ("dps", "DPS", money),
            ("debt_years", "Debt yrs", lambda v: "-" if v != v else f"{v:.1f}"),
            ("capex_to_ni", "Capex/NI", pct)]
    for _, title, _ in cols:
        years.add_column(title, justify="right")
    for _, r in a.yearly.tail(12).iterrows():
        years.add_row(*[fmt(r[c]) if c != "fiscal_year" else str(int(r[c])) for c, _, fmt in cols])
    console.print(years)


def cmd_macro(args):
    with store.connect() as con:
        if args.refresh:
            macro.refresh(con)
        snap = macro.snapshot(con)
    mc = snap["market_cap_to_gdp"]
    sahm = "-" if snap["sahm"] is None else f"{snap['sahm']:.2f}"
    console.print(f"10y Treasury {pct(snap['treasury_10y'], 2)} · 10y-2y {pct(snap['yield_curve'], 2)} · "
                  f"VIX {snap['vix'] or '-'} · Sahm rule {sahm}")
    if mc:
        console.print(f"Market Cap / GDP {mc['value']:.0%} (trend {mc['trend']:.0%}, z {mc['z']:+.2f}) → "
                      f"[bold]{mc['regime']}[/], suggested cash {mc['suggested_cash']:.0%}")
    if snap["recession_warning"]:
        console.print("[red]Sahm rule triggered: unemployment is rising fast.[/]")


def cmd_audit(args):
    with store.connect(read_only=True) as con:
        result = audit.run(con)
    audit.save(result)
    t = Table(title="Years within 2% of Yahoo Finance", header_style="bold")
    t.add_column("Source")
    t.add_column("Companies", justify="right")
    for _, label in audit.SHOWN:
        t.add_column(label, justify="right")
    for s in result["sources"]:
        cells = []
        for line, _ in audit.SHOWN:
            v = s["lines"].get(line)
            cells.append("-" if not v else f"{v['close']:.0%} [dim]({v['pairs']})[/]")
        t.add_row(s["name"], str(s["companies"]), *cells)
    console.print(t)
    console.print(f"[dim]{result['companies_checked']} companies checked, saved to {audit.PATH}[/]")


def _t(v):
    return "-" if v is None else f"{v:.1f}"


def cmd_study(args):
    panel = study.load_panel() if args.reuse else None
    if panel is None:
        panel = study.build_panel(workers=args.workers)
    res = study.results(panel)
    study.save(panel, res)
    console.print(f"{res['company_years']:,} company-years, {res['companies']:,} companies, "
                  f"{len(res['markets'])} markets, {res['first']} to {res['last']}")
    t = Table(title="Each signal against the next year's return, within market and year", header_style="bold")
    for col in ("Signal", "Horizon", "Years", "Rank corr.", "t", "Top fifth less bottom", "t"):
        t.add_column(col, justify="left" if col in ("Signal", "Horizon") else "right")
    for signal, label in study.SIGNALS.items():
        for h in study.HORIZONS:
            p = (res["signals"][signal].get(f"{h}y") or {}).get("pooled")
            if p:
                t.add_row(label, f"{h} year{'s' if h > 1 else ''}", str(p["years"]), f"{p['ic']:.3f}", _t(p["ic_t"]),
                          pct(p["spread"]), _t(p["spread_t"]))
    console.print(t)
    for h in study.HORIZONS:
        g = res["gate"].get(f"{h}y") or {}
        if g:
            console.print(f"Passing the checklist, {h}y: {pct(g['gap'])} against the rest of the market "
                          f"(t {_t(g['t'])}, {g['passing_share']:.0%} pass)")
    c = Table(title="Promised against delivered, companies that passed, three years", header_style="bold")
    for col in ("Promised a year", "Companies", "Delivered a year", "Against their market"):
        c.add_column(col, justify="right")
    for b in res["calibration"]:
        c.add_row(b["bucket"], str(b["n"]), pct(b["realised"]), pct(b["excess"]))
    console.print(c)
    charts = study.figures(res, config.ROOT / "docs" / "img")
    console.print(f"[dim]saved to {study.DIR}, charts in docs/img ({len(charts)})[/]")


def cmd_evals(args):
    from value_investor import evals
    tickers = [t.upper() for t in args.tickers] if args.tickers else evals.briefs()
    if not tickers:
        console.print("No briefs with saved evidence yet. Run research.py on a few companies first.")
        return
    rows = evals.grade(tickers)
    res = evals.summarise(rows, tickers)
    res["human"] = evals.human_agreement(rows)
    evals.save(res, rows)
    t = Table(title=f"Cited sentences, judged by {res['judge']}", header_style="bold")
    for col in ("Brief", "Sentences", "Cited", "Supported", "Partly", "Not in source", "Contradicted"):
        t.add_column(col, justify="left" if col == "Brief" else "right")
    for name, s in [*res["by_brief"].items(), ("All", res["overall"])]:
        t.add_row(name, f"{s['judged']}/{s['sentences']}", pct(s.get("cited_share"), 0),
                  *(pct(s[v], 0) for v in evals.VERDICTS))
    console.print(t)
    if args.sample:
        console.print(f"Mark these by hand, then run again: {evals.write_sample(rows, args.sample)}")
    if res["human"]:
        h = res["human"]
        console.print(f"Judge against your marks: {h['agreement']:.0%} agree on {h['marked']} sentences, "
                      f"kappa {h['kappa']:.2f}" if h["kappa"] is not None else "")


def main():
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("screen")
    p.add_argument("--tickers", nargs="+")
    p.add_argument("--no-prices", action="store_true")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--all", action="store_true", help="include companies that fail the gate")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("rank")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_rank)

    p = sub.add_parser("show")
    p.add_argument("ticker")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("macro")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=cmd_macro)

    p = sub.add_parser("audit")
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("study")
    p.add_argument("--workers", type=int, help="processes scoring companies at once")
    p.add_argument("--reuse", action="store_true", help="reuse the last scored panel, only redo the statistics")
    p.set_defaults(func=cmd_study)

    p = sub.add_parser("evals")
    p.add_argument("--tickers", nargs="+", help="only these briefs")
    p.add_argument("--sample", type=int, help="write this many sentences to mark by hand")
    p.set_defaults(func=cmd_evals)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
