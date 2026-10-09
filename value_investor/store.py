"""04 · store: the DuckDB file everything reads from and writes to.

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

CREATE TABLE IF NOT EXISTS entity_ids (
    source_key VARCHAR PRIMARY KEY,
    id INTEGER
);
"""

# Added after the first release; ALTER keeps existing databases working.
MIGRATIONS = """
ALTER TABLE companies ADD COLUMN IF NOT EXISTS source VARCHAR;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS market VARCHAR;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS price_currency VARCHAR;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS sector VARCHAR;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS industry VARCHAR;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS summary VARCHAR;
ALTER TABLE companies ADD COLUMN IF NOT EXISTS market_cap DOUBLE;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS market VARCHAR;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS country VARCHAR;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS currency VARCHAR;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS expected_return_base DOUBLE;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS f_score INTEGER;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS earnings_yield DOUBLE;
ALTER TABLE analyses ADD COLUMN IF NOT EXISTS return_on_capital DOUBLE;
UPDATE companies SET source = 'sec', market = 'USA', price_currency = 'USD', sector = sic_description
    WHERE source IS NULL AND cik > 0;
"""

COMPANY_COLUMNS = [
    "cik", "ticker", "name", "exchange", "sic", "sic_description", "country", "fiscal_year_end",
    "category", "currency", "last_annual_filed", "source", "market", "price_currency", "sector",
    "industry", "summary", "market_cap",
]


@contextmanager
def connect(read_only: bool = False):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(config.DB_PATH), read_only=read_only)
    try:
        if not read_only:
            con.execute(SCHEMA)
            con.execute(MIGRATIONS)
        yield con
    finally:
        con.close()


def init() -> None:
    with connect():
        pass


def entity_id(con, source_key: str) -> int:
    """Companies without an SEC CIK get a stable negative id, so CIKs never collide."""
    row = con.execute("SELECT id FROM entity_ids WHERE source_key = ?", [source_key]).fetchone()
    if row:
        return int(row[0])
    lowest = con.execute("SELECT coalesce(min(id), 0) FROM entity_ids").fetchone()[0]
    new_id = min(int(lowest), 0) - 1
    con.execute("INSERT INTO entity_ids VALUES (?, ?)", [source_key, new_id])
    return new_id


def upsert_company(con, profile: dict) -> None:
    con.execute("DELETE FROM companies WHERE cik = ?", [profile["cik"]])
    columns = COMPANY_COLUMNS + ["facts_updated_at"]
    values = [profile.get(c) for c in COMPANY_COLUMNS]
    con.execute(
        f"INSERT INTO companies ({', '.join(columns)}) VALUES ({', '.join('?' * len(COMPANY_COLUMNS))}, now())",
        values,
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


ANALYSIS_COLUMNS = [
    "cik", "ticker", "name", "as_of", "profile", "quality", "completeness", "history_years", "price",
    "expected_return", "buy_price", "dividend_yield", "passes_gate", "market", "country", "currency",
    "expected_return_base", "f_score", "earnings_yield", "return_on_capital",
]


def save_analysis(con, row: dict) -> None:
    con.execute("DELETE FROM analyses WHERE cik = ?", [row["cik"]])
    columns = ANALYSIS_COLUMNS + ["payload", "analysed_at"]
    values = [row.get(c) for c in ANALYSIS_COLUMNS] + [json.dumps(row["payload"], default=str)]
    con.execute(
        f"INSERT INTO analyses ({', '.join(columns)}) VALUES ({', '.join('?' * len(values))}, now())",
        values,
    )


def analyses(con) -> pd.DataFrame:
    return con.execute("SELECT * EXCLUDE (payload) FROM analyses").df()


def analysis_payload(con, cik: int) -> "dict | None":
    row = con.execute("SELECT payload FROM analyses WHERE cik = ?", [cik]).fetchone()
    return None if row is None else json.loads(row[0])
