"""04 · store — the DuckDB file everything reads from and writes to.

Raw facts are kept with their filing date and accession number, so any
statement can be rebuilt as it looked on a past date (see statements.py).
DuckDB allows one writer per file: fetch in threads, write from one.
"""

import json
from contextlib import contextmanager

import duckdb
import pandas as pd

from value_investor import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    cik INTEGER PRIMARY KEY,
    ticker VARCHAR,
    name VARCHAR,
    exchange VARCHAR,
    sic INTEGER,
    sic_description VARCHAR,
    country VARCHAR,
    fiscal_year_end VARCHAR,
    category VARCHAR,
    currency VARCHAR,
    last_annual_filed DATE,
    facts_updated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS facts (
    cik INTEGER,
    taxonomy VARCHAR,
    concept VARCHAR,
    unit VARCHAR,
    period_start DATE,
    period_end DATE,
    value DOUBLE,
    form VARCHAR,
    filed DATE,
    accn VARCHAR
);

CREATE TABLE IF NOT EXISTS prices (
    ticker VARCHAR,
    date DATE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    dividend DOUBLE,
    split DOUBLE
);

CREATE TABLE IF NOT EXISTS price_fetches (
    ticker VARCHAR PRIMARY KEY,
    fetched_at TIMESTAMP,
    ok BOOLEAN
);

CREATE TABLE IF NOT EXISTS macro (
    series VARCHAR,
    date DATE,
    value DOUBLE
);

CREATE TABLE IF NOT EXISTS analyses (
    cik INTEGER PRIMARY KEY,
    ticker VARCHAR,
    name VARCHAR,
    as_of DATE,
    profile VARCHAR,
    quality DOUBLE,
    completeness DOUBLE,
    history_years INTEGER,
    price DOUBLE,
    expected_return DOUBLE,
    buy_price DOUBLE,
    dividend_yield DOUBLE,
    passes_gate BOOLEAN,
    payload JSON,
    analysed_at TIMESTAMP
);
"""


@contextmanager
def connect(read_only: bool = False):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.DB_PATH), read_only=read_only)
    try:
        if not read_only:
            con.execute(SCHEMA)
        yield con
    finally:
        con.close()


def init() -> None:
    with connect():
        pass


def upsert_company(con, profile: dict) -> None:
    con.execute("DELETE FROM companies WHERE cik = ?", [profile["cik"]])
    con.execute(
        """INSERT INTO companies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())""",
        [
            profile["cik"], profile.get("ticker"), profile.get("name"), profile.get("exchange"),
            profile.get("sic"), profile.get("sic_description"), profile.get("country"),
            profile.get("fiscal_year_end"), profile.get("category"), profile.get("currency"),
            profile.get("last_annual_filed"),
        ],
    )


def replace_facts(con, cik: int, facts: pd.DataFrame) -> None:
    con.execute("DELETE FROM facts WHERE cik = ?", [cik])
    if facts.empty:
        return
    frame = facts.assign(cik=cik)[
        ["cik", "taxonomy", "concept", "unit", "period_start", "period_end", "value", "form", "filed", "accn"]
    ]
    con.register("incoming_facts", frame)
    con.execute("INSERT INTO facts SELECT * FROM incoming_facts")
    con.unregister("incoming_facts")


def load_facts(con, cik: int) -> pd.DataFrame:
    return con.execute("SELECT * FROM facts WHERE cik = ?", [cik]).df()


def company(con, cik: int) -> "dict | None":
    row = con.execute("SELECT * FROM companies WHERE cik = ?", [cik]).df()
    return None if row.empty else row.iloc[0].to_dict()


def find_cik(con, ticker: str) -> "int | None":
    row = con.execute("SELECT cik FROM companies WHERE upper(ticker) = upper(?)", [ticker]).fetchone()
    return None if row is None else int(row[0])


def companies(con) -> pd.DataFrame:
    return con.execute("SELECT * FROM companies ORDER BY name").df()


def replace_prices(con, ticker: str, prices: pd.DataFrame, ok: bool) -> None:
    con.execute("DELETE FROM prices WHERE ticker = ?", [ticker])
    if not prices.empty:
        frame = prices.assign(ticker=ticker)[["ticker", "date", "high", "low", "close", "dividend", "split"]]
        con.register("incoming_prices", frame)
        con.execute("INSERT INTO prices SELECT * FROM incoming_prices")
        con.unregister("incoming_prices")
    con.execute("DELETE FROM price_fetches WHERE ticker = ?", [ticker])
    con.execute("INSERT INTO price_fetches VALUES (?, now(), ?)", [ticker, ok])


def load_prices(con, ticker: str) -> pd.DataFrame:
    return con.execute(
        "SELECT date, high, low, close, dividend, split FROM prices WHERE ticker = ? ORDER BY date", [ticker]
    ).df()


def price_fetched_at(con, ticker: str):
    row = con.execute("SELECT fetched_at FROM price_fetches WHERE ticker = ?", [ticker]).fetchone()
    return None if row is None else row[0]


def replace_macro(con, series: str, frame: pd.DataFrame) -> None:
    con.execute("DELETE FROM macro WHERE series = ?", [series])
    if frame.empty:
        return
    con.register("incoming_macro", frame.assign(series=series)[["series", "date", "value"]])
    con.execute("INSERT INTO macro SELECT * FROM incoming_macro")
    con.unregister("incoming_macro")


def load_macro(con, series: str) -> pd.Series:
    df = con.execute("SELECT date, value FROM macro WHERE series = ? ORDER BY date", [series]).df()
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index(pd.to_datetime(df["date"]))["value"]


def save_analysis(con, row: dict) -> None:
    con.execute("DELETE FROM analyses WHERE cik = ?", [row["cik"]])
    con.execute(
        """INSERT INTO analyses VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())""",
        [
            row["cik"], row["ticker"], row["name"], row["as_of"], row["profile"], row["quality"],
            row["completeness"], row["history_years"], row["price"], row["expected_return"],
            row["buy_price"], row["dividend_yield"], row["passes_gate"],
            json.dumps(row["payload"], default=str),
        ],
    )


def analyses(con) -> pd.DataFrame:
    return con.execute("SELECT * EXCLUDE (payload) FROM analyses").df()


def analysis_payload(con, cik: int) -> "dict | None":
    row = con.execute("SELECT payload FROM analyses WHERE cik = ?", [cik]).fetchone()
    return None if row is None else json.loads(row[0])
