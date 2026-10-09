"""01 · config: every setting, read from .env. everything imports this.

thresholds come from knowledge/principles.md. if you change one here,
change the principle there too, so the docs and the score never disagree.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent

## STORAGE

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.getenv("DB_PATH", DATA_DIR / "value_investor.duckdb"))

## SEC EDGAR

# the SEC rejects anonymous traffic. use "Your Name your@email.com".
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "")
# their fair-access limit is 10 requests/second; stay a bit under it.
SEC_REQUESTS_PER_SECOND = float(os.getenv("SEC_REQUESTS_PER_SECOND", "8"))
SEC_WORKERS = int(os.getenv("SEC_WORKERS", "6"))

DEFAULT_EXCHANGES = ("NYSE", "Nasdaq")

## WORLD (Yahoo Finance, every market outside the US)

WORLD_MIN_CAP_USD = float(os.getenv("WORLD_MIN_CAP_USD", "1e9"))

## MACRO (FRED, no key needed for the CSV endpoint)

FRED_SERIES = {
    "treasury_10y": "DGS10",
    "treasury_2y": "DGS2",
    "gdp": "GDP",
    "corporate_equities": "NCBEILQ027S",
    "unemployment": "UNRATE",
    "vix": "VIXCLS",
}

## LLM
# local first. Groq and Hugging Face only kick in if their keys are set.

LLM_PRIMARY = os.getenv("LLM_PRIMARY", "ollama")  # ollama | groq | huggingface
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "16384"))
# qwen3 "thinks" before answering. on a laptop CPU that costs minutes per call
# at ~7 tokens/s, so it's off unless asked for.
OLLAMA_THINK = os.getenv("OLLAMA_THINK", "false").strip().lower() == "true"

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

HF_TOKEN = os.getenv("HF_TOKEN")
HF_MODEL = os.getenv("HF_MODEL", "openai/gpt-oss-120b")
HF_BASE_URL = os.getenv("HF_BASE_URL", "https://router.huggingface.co/v1")

LLM_TEMPERATURE = 0

## WEB SEARCH (research agents)

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
# counted here and kept under tavily's free 1,000 a month; 0 means never use tavily
TAVILY_MONTHLY_CREDITS = int(os.getenv("TAVILY_MONTHLY_CREDITS", "900"))

## DASHBOARD

# true when other people can open the dashboard: no research runs and no questions,
# since those spend your api credits.
PUBLIC_DASHBOARD = os.getenv("PUBLIC_DASHBOARD", "false").strip().lower() == "true"

## LANGSMITH (optional tracing)

LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "value-investor")

## SCREENING: history

HISTORY_YEARS = 10           # the window every consistency check looks at
MIN_HISTORY_YEARS = 4        # below this, consistency checks report "n/a"; Yahoo gives four or five years

## SCREENING: income statement

GROSS_MARGIN_GOOD = 0.40
GROSS_MARGIN_POOR = 0.20
GROSS_MARGIN_MAX_SWING = 0.05      # std dev of yearly gross margin
OPERATING_MARGIN_GOOD = 0.25       # stand-in when a company files no cost of sales
OPERATING_MARGIN_POOR = 0.12
SGA_TO_GROSS_PROFIT_GOOD = 0.30
SGA_TO_GROSS_PROFIT_POOR = 0.80
RND_TO_GROSS_PROFIT_GOOD = 0.10
RND_TO_GROSS_PROFIT_POOR = 0.30
DEPRECIATION_TO_GROSS_PROFIT_GOOD = 0.10
DEPRECIATION_TO_GROSS_PROFIT_POOR = 0.20
INTEREST_TO_OPERATING_INCOME_GOOD = 0.15
INTEREST_TO_OPERATING_INCOME_POOR = 0.30
NET_MARGIN_GOOD = 0.20
NET_MARGIN_POOR = 0.10
EPS_UP_YEARS_GOOD = 0.70           # share of years where EPS beat the year before
EPS_UP_YEARS_POOR = 0.50
TAX_RATE_LOW = 0.10                # effective rates outside this band get a second look
TAX_RATE_HIGH = 0.35

## SCREENING: balance sheet

ROE_GOOD = 0.15
ROE_POOR = 0.10
ROE_CONSISTENT_YEARS = 0.80
DEBT_PAYOFF_YEARS_GOOD = 3.0       # long-term debt / net earnings
DEBT_PAYOFF_YEARS_POOR = 5.0
ADJ_DEBT_TO_EQUITY_GOOD = 0.80
ADJ_DEBT_TO_EQUITY_POOR = 2.0
SHARE_COUNT_DILUTION_POOR = 0.10   # +10% shares over the window

## SCREENING: cash flow

CAPEX_TO_EARNINGS_GOOD = 0.25
CAPEX_TO_EARNINGS_POOR = 0.50
FCF_CONVERSION_GOOD = 0.80
FCF_CONVERSION_POOR = 0.50
RETAINED_EARNINGS_RETURN_GOOD = 0.15
RETAINED_EARNINGS_RETURN_POOR = 0.08

## VALUATION

PROJECTION_YEARS = 10
HURDLE_RATE = float(os.getenv("HURDLE_RATE", "0.15"))
GROWTH_CAP = 0.15
PE_FLOOR = 5.0
PE_CAP = 35.0
SELL_PE = 40.0

## RANKING

MIN_QUALITY = float(os.getenv("MIN_QUALITY", "70"))
MIN_COMPLETENESS = 0.60

# SIC 6000-6799: banks, insurers, brokers, REITs. leverage and margin rules
# mean something else there, so they get their own (smaller) checklist.
FINANCIAL_SIC_RANGE = (6000, 6799)

## QUARTERS, PEERS, INSIDERS

QUARTERS_SHOWN = 12
PEERS_SHOWN = 8
INSIDER_DAYS = 365


def check_sec_user_agent() -> None:
    if not SEC_USER_AGENT or "@" not in SEC_USER_AGENT:
        raise ValueError(
            "Set SEC_USER_AGENT in .env, e.g. 'Jane Doe jane@example.com'. "
            "The SEC blocks requests without a contact address."
        )
