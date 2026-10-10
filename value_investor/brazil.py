"""32 · brazil: annual statements for b3 listings, from the cvm's open data.

the securities regulator (cvm) publishes every listed company's annual
statements (dfp) as one zip a year, with fixed account codes, and a register
(fca) that ties trading codes like PETR4 to the company. each year's file
holds the year as filed and the one before; the year as first filed is kept,
with the date the cvm received it.
"""

import base64
import io
import json
import logging
import re
import threading
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from value_investor import config
from value_investor.edgar import COLUMNS

logger = logging.getLogger(__name__)

BASE = "https://dados.cvm.gov.br/dados/CIA_ABERTA/DOC/{kind}/DADOS/{name}_cia_aberta_{year}.zip"
B3 = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/"
CACHE = config.DATA_DIR / "sources" / "cvm"
TAXONOMY = "cvm"
YEARS = 11
_lock = threading.Lock()
_built: dict = {}

# our line -> cvm account codes, added up; the first group present wins
CODES = {
    "revenue": [["3.01"]],
    "cost_of_revenue": [["3.02"]],
    "gross_profit": [["3.03"]],
    "sga": [["3.04.01", "3.04.02"]],
    "operating_income": [["3.05"]],
    "interest_expense": [["3.06.02"]],
    "total_assets": [["1"]],
    "current_assets": [["1.01"]],
    "cash": [["1.01.01"]],
    "short_term_investments": [["1.01.02"]],
    "receivables": [["1.01.03"]],
    "inventory": [["1.01.04"]],
    "ppe": [["1.02.03"]],
    "intangibles": [["1.02.04"]],
    "current_liabilities": [["2.01"]],
    "short_term_debt": [["2.01.04"]],
    "long_term_debt": [["2.02.01"]],
    "equity_incl_nci": [["2.03"]],
    "retained_earnings": [["2.03.04", "2.03.05"]],
    "operating_cash_flow": [["6.01"]],
}
NEGATIVE = {"cost_of_revenue", "sga", "interest_expense", "income_tax"}
INSTANT = {"total_assets", "current_assets", "cash", "short_term_investments", "receivables", "inventory", "ppe",
           "intangibles", "current_liabilities", "short_term_debt", "long_term_debt", "equity_incl_nci", "equity",
           "retained_earnings", "total_liabilities"}
# lines whose code differs between the industrial and the bank chart, found by name
NAMED = {
    "pretax_income": re.compile(r"^resultado antes dos tributos sobre o lucro", re.I),
    "income_tax": re.compile(r"^imposto de renda e contribui", re.I),
    "net_income": re.compile(r"atribu[íi]do a s[óo]cios da (?:empresa )?controladora", re.I),
    "net_income_total": re.compile(r"^lucro.*do per[íi]odo", re.I),
}
# lines without a fixed code, found by name
BY_NAME = {
    # "aquisição de imobilizado", or just "imobilizado" (weg); never "venda de imobilizado"
    "capex": ("6.02", re.compile(r"^(?:(?:aquisi|compra|adi[cç]|investimentos? (?:em|no)).*)?(?:ativos? )?(?:imobilizado|intang)", re.I)),
    "depreciation": ("6.01", re.compile(r"deprecia|amortiza", re.I)),
    "dividends_paid": ("6.03", re.compile(r"dividend|juros sobre (?:o )?capital", re.I)),
}


def _old(path) -> bool:
    return not path.exists() or datetime.fromtimestamp(path.stat().st_mtime) < datetime.now() - timedelta(days=30)


def _digits(cnpj) -> str:
    digits = re.sub(r"\D", "", str(cnpj or ""))
    return digits.zfill(14) if digits else ""      # b3 drops leading zeros


def _zip(kind: str, name: str, year: int) -> "zipfile.ZipFile | None":
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{name}_{year}.zip"
    if not path.exists() or (year >= date.today().year - 1 and _old(path)):
        resp = requests.get(BASE.format(kind=kind, name=name, year=year), timeout=300)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return zipfile.ZipFile(path)


def _csv(z: zipfile.ZipFile, part: str) -> pd.DataFrame:
    names = [n for n in z.namelist() if n.endswith(f"_{part}.csv") or re.search(rf"_{part}_\d{{4}}\.csv$", n)]
    if not names:
        return pd.DataFrame()
    with z.open(names[0]) as fh:
        return pd.read_csv(io.TextIOWrapper(fh, encoding="latin-1"), sep=";", dtype=str)


def tickers() -> dict:
    """trading code (PETR4) -> cnpj, from the last three registers; a company that hasn't
    filed this year's yet is still in last year's."""
    out: dict = {}
    for year in range(date.today().year - 2, date.today().year + 1):
        z = _zip("FCA", "fca", year)
        if z is None:
            continue
        df = _csv(z, "valor_mobiliario")
        if df.empty or "Codigo_Negociacao" not in df:
            continue
        df = df.dropna(subset=["Codigo_Negociacao"])
        out.update(zip(df["Codigo_Negociacao"].str.strip().str.upper(), df["CNPJ_Companhia"].map(_digits)))
    return out


def roots() -> dict:
    """four-letter issuer code (CSNA) -> cnpj, from b3's list of listed companies. the
    register's trading codes are sometimes junk ("4030"), b3's issuer codes aren't."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / "b3_companies.json"
    if _old(path):
        rows, page = [], 1
        while True:
            query = base64.b64encode(json.dumps({"language": "en-us", "pageNumber": page, "pageSize": 120}).encode())
            data = requests.get(B3 + query.decode(), timeout=60, headers={"User-Agent": "Mozilla/5.0"}).json()
            rows += data.get("results") or []
            if page >= (data.get("page") or {}).get("totalPages", 0):
                break
            page += 1
        path.write_text(json.dumps(rows), encoding="utf-8")
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {r["issuingCompany"]: _digits(r["cnpj"]) for r in rows if r.get("issuingCompany") and r.get("cnpj")}


def cnpj_for(code: str, codes: dict, issuers: dict) -> "str | None":
    """the company behind a trading code; units (BPAC11) and odd classes (MRSA3B) share the
    four-letter root with the company's other codes."""
    if code in codes:
        return codes[code]
    if code[:4] in issuers:
        return issuers[code[:4]]
    found = {cnpj for c, cnpj in codes.items() if c[:4] == code[:4]}
    return found.pop() if len(found) == 1 else None


def _year_frame(year: int) -> pd.DataFrame:
    """every company's accounts as first filed for one fiscal year, consolidated where there is one."""
    z = _zip("DFP", "dfp", year)
    if z is None:
        return pd.DataFrame()
    index = _csv(z, str(year))
    received = {} if index.empty else dict(zip(index["CNPJ_CIA"] + "|" + index["VERSAO"], index["DT_RECEB"]))
    parts = []
    for statement in ("DRE", "BPA", "BPP", "DFC_MI", "DFC_MD"):
        for scope in ("con", "ind"):
            df = _csv(z, f"{statement}_{scope}")
            if df.empty:
                continue
            df = df[df["ORDEM_EXERC"].str.startswith("ÚLTIMO") | df["ORDEM_EXERC"].str.startswith("ULTIMO")]
            parts.append(df.assign(SCOPE=scope))
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    df["VL_CONTA"] = pd.to_numeric(df["VL_CONTA"], errors="coerce")
    df.loc[df["ESCALA_MOEDA"].str.upper().eq("MIL") & ~df["CD_CONTA"].str.startswith("3.99"), "VL_CONTA"] *= 1000
    # the last version of each filing, consolidated when the company publishes one
    df["VERSAO"] = pd.to_numeric(df["VERSAO"], errors="coerce")
    df = df[df["VERSAO"] == df.groupby("CNPJ_CIA")["VERSAO"].transform("max")]
    has_con = set(df.loc[df["SCOPE"] == "con", "CNPJ_CIA"])
    df = df[(df["SCOPE"] == "con") | ~df["CNPJ_CIA"].isin(has_con)]
    df["FILED"] = [received.get(f"{c}|{int(v)}") for c, v in zip(df["CNPJ_CIA"], df["VERSAO"])]
    return df


def _company_facts(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for end_text, year in df.groupby("DT_FIM_EXERC"):
        end = pd.Timestamp(end_text).date()
        start = (pd.Timestamp(end) - pd.Timedelta(days=364)).date()
        filed_text = year["FILED"].dropna()
        filed = pd.Timestamp(filed_text.iloc[0]).date() if not filed_text.empty else (pd.Timestamp(end) + pd.Timedelta(days=90)).date()
        acct = year.groupby("CD_CONTA")["VL_CONTA"].sum()
        values = {}
        for field, groups in CODES.items():
            for group in groups:
                hits = [acct[c] for c in group if c in acct.index and not pd.isna(acct[c])]
                if hits:
                    values[field] = abs(sum(hits)) if field in NEGATIVE else sum(hits)
                    break
        top = year[year["CD_CONTA"].str.match(r"^3\.\d\d(\.\d\d)?$")]
        for field, pattern in NAMED.items():
            rows = top[top["DS_CONTA"].fillna("").str.contains(pattern)]
            if not rows.empty and not pd.isna(rows["VL_CONTA"].iloc[0]):
                value = float(rows["VL_CONTA"].iloc[0])
                values[field] = abs(value) if field == "income_tax" else value
        # some filers leave the parent's share at zero and only fill in the total
        if not values.get("net_income") and "net_income_total" in values:
            values["net_income"] = values["net_income_total"]
        values.pop("net_income_total", None)
        if "operating_income" in values and "pretax_income" in values and values["operating_income"] == values["pretax_income"]:
            values.pop("operating_income")      # the bank chart's 3.05 is pre-tax, not ebit
        for field, (prefix, pattern) in BY_NAME.items():
            rows = year[year["CD_CONTA"].str.startswith(prefix + ".") & year["DS_CONTA"].fillna("").str.contains(pattern)]
            if not rows.empty:
                values[field] = abs(float(rows["VL_CONTA"].sum()))
        if "equity_incl_nci" in values:
            nci = acct.get("2.03.09")
            values["equity"] = values["equity_incl_nci"] - (0.0 if nci is None or pd.isna(nci) else nci)
            if "1" in acct.index:
                values["total_liabilities"] = acct["1"] - values["equity_incl_nci"]
        eps_rows = year[year["CD_CONTA"].str.startswith("3.99.02.") | year["CD_CONTA"].str.startswith("3.99.01.")]
        eps_rows = eps_rows.sort_values("CD_CONTA", ascending=False)       # diluted (3.99.02) before basic
        ordinary = eps_rows[eps_rows["DS_CONTA"].fillna("").str.upper().str.contains("ON")]
        pick = ordinary if not ordinary.empty else eps_rows
        if not pick.empty and pick["VL_CONTA"].iloc[0]:
            values["eps_diluted"] = float(pick["VL_CONTA"].iloc[0])
            if values.get("net_income") and values["net_income"] / values["eps_diluted"] > 0:
                values["shares_diluted"] = values["net_income"] / values["eps_diluted"]
        currency = "BRL"
        for field, value in values.items():
            if value is None or pd.isna(value):
                continue
            unit = f"{currency}/shares" if field == "eps_diluted" else "shares" if field == "shares_diluted" else currency
            out.append((TAXONOMY, field, unit, None if field in INSTANT else start, end, float(value), "dfp", filed, None))
    facts = pd.DataFrame(out, columns=COLUMNS)
    # some filers give eps per lot of a thousand shares
    eps = facts["concept"] == "eps_diluted"
    if eps.sum() >= 3:
        typical = facts.loc[eps, "value"].abs().median()
        lots = eps & (facts["value"].abs() > 200 * typical)
        facts.loc[lots, "value"] /= 1000
        shares = (facts["concept"] == "shares_diluted") & facts["period_end"].isin(facts.loc[lots, "period_end"])
        facts.loc[shares, "value"] *= 1000
    return facts


def _build() -> dict:
    """cnpj -> facts for every company, built once per run."""
    with _lock:
        if _built:
            return _built
        last = date.today().year - 1
        frames = []
        for year in range(last - YEARS + 1, last + 1):
            try:
                frames.append(_year_frame(year))
            except Exception as exc:
                logger.warning("cvm %s failed: %s", year, exc)
        df = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else pd.DataFrame()
        _built["by_cnpj"] = {_digits(cnpj): _company_facts(g) for cnpj, g in df.groupby("CNPJ_CIA")} if not df.empty else {}
        _built["tickers"] = tickers()
        try:
            _built["issuers"] = roots()
        except Exception as exc:
            logger.warning("b3 company list failed: %s", exc)
            _built["issuers"] = {}
        return _built


def statements(symbol: str) -> pd.DataFrame:
    code, _, suffix = symbol.upper().partition(".")
    if suffix != "SA":
        return pd.DataFrame(columns=COLUMNS)
    built = _build()
    cnpj = cnpj_for(code, built["tickers"], built["issuers"])
    facts = built["by_cnpj"].get(cnpj) if cnpj else None
    if facts is None or facts.empty:
        return pd.DataFrame(columns=COLUMNS)
    try:
        import yfinance as yf
        from value_investor.china import bonus_factors
        splits = [(pd.Timestamp(d).date(), float(r)) for d, r in yf.Ticker(symbol).splits.items() if r and r > 0]
    except Exception:
        splits = []
    if splits:
        facts = facts.copy()
        shares = facts[facts["concept"] == "shares_diluted"].set_index("period_end")["value"].to_dict()
        factors = bonus_factors(shares, splits)
        for concept, op in (("shares_diluted", lambda v, f: v * f), ("eps_diluted", lambda v, f: v / f)):
            mask = facts["concept"] == concept
            facts.loc[mask, "value"] = [op(v, factors.get(e, 1.0)) for v, e in zip(facts.loc[mask, "value"], facts.loc[mask, "period_end"])]
    return facts
