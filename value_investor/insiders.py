"""25 · insiders: open-market buys and sells by officers and directors (form 4).

US only: EDGAR is the one free, complete source. what counts is open-market
buying (code P) with the insider's own money, and sales that weren't set up
in advance under a 10b5-1 plan. grants, option exercises and tax withholding
are left out.
"""

import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd

from value_investor import config
from value_investor.http import get_json, get_text

logger = logging.getLogger(__name__)

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{doc}"
FORMS = {"4", "4/A"}
CLUSTER_DAYS = 90
HEAVY_SHARE = 0.25
HEAVY_SELLERS = 3


def _text(node, path: str) -> "str | None":
    found = node.find(path) if node is not None else None
    return found.text.strip() if found is not None and found.text else None


def _num(node, path: str) -> "float | None":
    try:
        return float(_text(node, path))
    except (TypeError, ValueError):
        return None


def _flag(value: "str | None") -> bool:
    return (value or "").strip().lower() in ("1", "true")


def _role(rel) -> str:
    if rel is None:
        return ""
    title = _text(rel, "officerTitle")
    if _flag(_text(rel, "isOfficer")) and title:
        return title
    if _flag(_text(rel, "isDirector")):
        return "Director"
    if _flag(_text(rel, "isTenPercentOwner")):
        return "10% owner"
    return title or _text(rel, "otherText") or "Other"


def parse(xml_text: str, issuer: "int | None" = None) -> list:
    """trades in one form 4, as dicts. a company's filing list also holds the
    form 4s it files as an owner of other companies; issuer filters those out."""
    root = ET.fromstring(xml_text)
    if issuer is not None and _num(root, "issuer/issuerCik") != issuer:
        return []
    owner = root.find("reportingOwner")
    name = _text(owner, "reportingOwnerId/rptOwnerName") or "Unknown"
    role = _role(owner.find("reportingOwnerRelationship") if owner is not None else None)
    notes = " ".join((n.text or "") for n in root.iter("footnote")).lower()
    planned = _flag(_text(root, "aff10b5One")) or "10b5-1" in notes
    out = []
    for tx in root.iter("nonDerivativeTransaction"):
        code = _text(tx, "transactionCoding/transactionCode")
        if not code:
            continue
        out.append({
            "trade_date": _text(tx, "transactionDate/value"),
            "owner": name.title() if name.isupper() else name,
            "role": role,
            "code": code,
            "shares": _num(tx, "transactionAmounts/transactionShares/value"),
            "price": _num(tx, "transactionAmounts/transactionPricePerShare/value"),
            "acquired": _text(tx, "transactionAmounts/transactionAcquiredDisposedCode/value") == "A",
            "owned_after": _num(tx, "postTransactionAmounts/sharesOwnedFollowingTransaction/value"),
            "planned": planned,
        })
    return out


def recent_filings(cik: int, days: int) -> list:
    """(accession, filed, xml document) for form 4s about this issuer."""
    sub = get_json(SUBMISSIONS_URL.format(cik=cik))
    recent = sub.get("filings", {}).get("recent", {})
    since = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for form, accn, filed, doc in zip(recent.get("form", []), recent.get("accessionNumber", []),
                                      recent.get("filingDate", []), recent.get("primaryDocument", [])):
        if form in FORMS and filed >= since and doc:
            out.append((accn, filed, doc.split("/")[-1]))
    return out


def _fetch(cik: int, accn: str, doc: str) -> list:
    url = DOC_URL.format(cik=cik, accn=accn.replace("-", ""), doc=doc)
    return parse(get_text(url), issuer=cik)


def refresh(con, ciks: list, days: int = config.INSIDER_DAYS, workers: int = 6) -> dict:
    """fetch form 4s not seen before. each filing is read once, ever."""
    counts = {"companies": 0, "filings": 0, "trades": 0, "failed": 0}
    seen = {r[0] for r in con.execute("SELECT accn FROM insider_filings").fetchall()}
    for cik in ciks:
        if cik <= 0:
            continue
        try:
            todo = [f for f in recent_filings(cik, days) if f[0] not in seen]
        except Exception as exc:
            logger.warning("form 4 list failed for CIK %s: %s", cik, exc)
            counts["failed"] += 1
            continue
        counts["companies"] += 1
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch, cik, accn, doc): (accn, filed) for accn, filed, doc in todo}
            for fut in as_completed(futures):
                accn, filed = futures[fut]
                try:
                    trades = fut.result()
                except Exception as exc:
                    logger.debug("form 4 %s failed: %s", accn, exc)
                    counts["failed"] += 1
                    continue
                for t in trades:
                    con.execute("INSERT INTO insider_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                [cik, accn, filed, t["trade_date"], t["owner"], t["role"], t["code"],
                                 t["shares"], t["price"], t["acquired"], t["owned_after"], t["planned"]])
                con.execute("INSERT OR IGNORE INTO insider_filings VALUES (?, ?, ?)", [accn, cik, filed])
                counts["filings"] += 1
                counts["trades"] += len(trades)
    return counts


def _heavy_sellers(sells: pd.DataFrame) -> int:
    """insiders who sold a quarter or more of what they held. executives at big companies
    sell stock they're paid in all the time; emptying the drawer is what's worth noticing."""
    heavy = 0
    for _, g in sells.groupby("owner"):
        sold = g["shares"].fillna(0).sum()
        left = g.sort_values("trade_date")["owned_after"].iloc[-1]
        if sold > 0 and (pd.isna(left) or sold / (sold + left) >= HEAVY_SHARE):
            heavy += 1
    return heavy


def trades(con, cik: int, days: int = config.INSIDER_DAYS) -> pd.DataFrame:
    since = date.today() - timedelta(days=days)
    df = con.execute("""SELECT * FROM insider_trades WHERE cik = ? AND trade_date >= ? AND code IN ('P', 'S')
                        ORDER BY trade_date DESC""", [cik, since]).df()
    if not df.empty:
        df["value"] = df["shares"].fillna(0) * df["price"].fillna(0)
    return df


def summary(con, cik: int, days: int = config.INSIDER_DAYS) -> "dict | None":
    if cik is None or cik <= 0:
        return None
    covered = con.execute("SELECT count(*) FROM insider_filings WHERE cik = ?", [cik]).fetchone()[0]
    if not covered:
        return None
    df = trades(con, cik, days)
    out = {"days": days, "filings": int(covered), "buys": 0, "buyers": 0, "buy_value": 0.0, "sells": 0,
           "sellers": 0, "sell_value": 0.0, "unplanned_sell_value": 0.0, "cluster": False, "recent": []}
    if df.empty:
        out["signal"] = "quiet"
        return out
    buys, sells = df[df["code"] == "P"], df[df["code"] == "S"]
    out.update(
        buys=len(buys), buyers=int(buys["owner"].nunique()), buy_value=float(buys["value"].sum()),
        sells=len(sells), sellers=int(sells["owner"].nunique()), sell_value=float(sells["value"].sum()),
        unplanned_sell_value=float(sells.loc[~sells["planned"].fillna(False).astype(bool), "value"].sum()),
    )
    if not buys.empty:
        cutoff = pd.Timestamp(buys["trade_date"].max()) - pd.Timedelta(days=CLUSTER_DAYS)
        out["cluster"] = int(buys[pd.to_datetime(buys["trade_date"]) >= cutoff]["owner"].nunique()) >= 2
    since = date.today() - timedelta(days=days)
    exercised = {(o, str(d)[:10]) for o, d in con.execute(
        "SELECT owner, trade_date FROM insider_trades WHERE cik = ? AND code = 'M' AND trade_date >= ?",
        [cik, since]).fetchall()}
    # options exercised and sold the same day are pay being cashed in, not a view on the stock
    mine = pd.Series([(o, str(d)[:10]) not in exercised for o, d in zip(sells["owner"], sells["trade_date"])],
                     index=sells.index, dtype=bool)
    own_shares = sells[mine]
    out["heavy_sellers"] = _heavy_sellers(own_shares[~own_shares["planned"].fillna(False).astype(bool)])
    if out["buyers"] >= 2 or (out["buy_value"] > 0 and out["buy_value"] >= out["unplanned_sell_value"]):
        out["signal"] = "buying"
    elif out["heavy_sellers"] >= HEAVY_SELLERS:
        out["signal"] = "selling"
    else:
        out["signal"] = "routine"
    out["recent"] = [
        {"date": str(r.trade_date)[:10], "owner": r.owner, "role": r.role, "code": r.code,
         "shares": None if pd.isna(r.shares) else float(r.shares),
         "price": None if pd.isna(r.price) else float(r.price),
         "value": float(r.value), "planned": bool(r.planned)}
        for r in df.head(12).itertuples()
    ]
    return out
