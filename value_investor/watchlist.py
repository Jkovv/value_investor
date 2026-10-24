"""40 · watchlist: companies to keep an eye on, and what changed since the last look.

a name and the day it was added, nothing more: no positions, no amounts. a digest
compares each name with the previous digest: did the price fall under buy below,
did a sell signal appear, did insiders buy, did the checklist verdict change. a good
business is bought when its price falls, rarely on the day its brief is read, and
this is what sends you back to it.
"""

import json
from datetime import date, datetime

from value_investor import config

PATH = config.DATA_DIR / "watchlist.json"
STATE = config.DATA_DIR / "watchlist_state.json"
DIGESTS = config.DATA_DIR / "digests"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write(path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)


def load() -> dict:
    """ticker -> {"added": iso date}."""
    return _read(PATH, {})


def toggle(ticker: str) -> bool:
    """add a ticker, or take it off if it's there; True when it's now watched."""
    items = load()
    ticker = ticker.upper()
    if ticker in items:
        items.pop(ticker)
        _write(PATH, items)
        return False
    items[ticker] = {"added": date.today().isoformat()}
    _write(PATH, items)
    return True


def reading(row: dict, payload: dict) -> dict:
    """what the digest looks at for one company, from its stored analysis."""
    v = payload.get("valuation") or {}
    ins = payload.get("insiders") or {}
    price, buy = v.get("price"), v.get("buy_price")
    return {
        "price": price, "buy_price": buy, "currency": v.get("currency"),
        "in_zone": bool(price and buy and price <= buy),
        "gap": (price / buy - 1) if price and buy else None,
        "sell_signal": bool(v.get("sell_signal")),
        "passes_gate": bool(row.get("passes_gate")),
        "expected_return": row.get("expected_return"),
        "insider_buyers": int(ins.get("buyers") or 0),
        "cluster": bool(ins.get("cluster")),
        "as_of": str(row.get("analysed_at") or "")[:10],
    }


def snapshot(con, tickers) -> dict:
    out = {}
    for ticker in tickers:
        row = con.execute("SELECT * EXCLUDE (payload) FROM analyses WHERE ticker = ?", [ticker]).df()
        if row.empty:
            continue
        payload = json.loads(con.execute("SELECT payload FROM analyses WHERE ticker = ?", [ticker]).fetchone()[0])
        out[ticker] = reading(row.iloc[0].to_dict(), payload)
    return out


def changes(before: dict, now: dict) -> list:
    """what moved between two snapshots, most pressing first."""
    events = []
    for ticker, n in now.items():
        b = before.get(ticker)
        if b is None:
            continue
        if n["in_zone"] and not b["in_zone"]:
            events.append((0, ticker, "entered the buy zone", f"{n['price']:,.2f} against buy below {n['buy_price']:,.2f}"))
        if n["sell_signal"] and not b["sell_signal"]:
            events.append((1, ticker, "sell signal", f"P/E at or above {config.SELL_PE:.0f}"))
        if n["cluster"] and not b["cluster"]:
            events.append((2, ticker, "insiders buying together", f"{n['insider_buyers']} buyers"))
        elif n["insider_buyers"] > b["insider_buyers"]:
            events.append((3, ticker, "insider buying", f"{n['insider_buyers']} buyers in the last year"))
        if b["passes_gate"] and not n["passes_gate"]:
            events.append((4, ticker, "fell below the gate", "the checklist no longer passes"))
        if b["in_zone"] and not n["in_zone"]:
            events.append((5, ticker, "left the buy zone", f"{n['price']:,.2f} against buy below {n['buy_price']:,.2f}"))
    return [{"ticker": t, "what": w, "detail": d} for _, t, w, d in sorted(events)]


def last_state() -> dict:
    return _read(STATE, {})


def save_state(snap: dict) -> None:
    _write(STATE, {"at": datetime.now().isoformat(timespec="minutes"), "companies": snap})


def write_digest(events: list, snap: dict) -> "str":
    """a dated markdown digest in data/digests."""
    DIGESTS.mkdir(parents=True, exist_ok=True)
    path = DIGESTS / f"{date.today().isoformat()}.md"
    lines = [f"# Watchlist, {date.today().isoformat()}", ""]
    lines += [f"- **{e['ticker']}**: {e['what']} ({e['detail']})" for e in events] or ["Nothing changed."]
    lines += ["", "| Company | Price | Buy below | Gap | Signals |", "|---|---|---|---|---|"]
    for ticker, r in sorted(snap.items(), key=lambda kv: kv[1]["gap"] if kv[1]["gap"] is not None else 9):
        signals = ", ".join(s for s, on in (("in the buy zone", r["in_zone"]), ("sell signal", r["sell_signal"]),
                                            ("insider buying", r["insider_buyers"] > 0)) if on) or "-"
        gap = f"{r['gap'] * 100:+.0f}%" if r["gap"] is not None else "-"
        price = f"{r['price']:,.2f} {r['currency'] or ''}" if r["price"] else "-"
        buy = f"{r['buy_price']:,.2f}" if r["buy_price"] else "-"
        lines.append(f"| {ticker} | {price} | {buy} | {gap} | {signals} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)
