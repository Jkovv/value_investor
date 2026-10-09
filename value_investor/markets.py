"""19 · markets: the 44 markets we screen and Market Cap / GDP for each.

world bank history, rolled forward with the local benchmark and gdp growth.
each market is judged against its own trend only: Switzerland looks huge next
to Germany because of who lists there, not because it is always expensive.
"""

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd
import requests

from value_investor import fx, macro, prices as px, store

logger = logging.getLogger(__name__)

WB_URL = "https://api.worldbank.org/v2/country/all/indicator/{indicator}?format=json&per_page=20000&date=1975:2030"
WB_MCAP = "CM.MKT.LCAP.GD.ZS"
WB_GDP_LCU = "NY.GDP.MKTP.CN"


@dataclass(frozen=True)
class Market:
    iso3: str
    name: str
    region: str             # Yahoo screener region code
    currency: str
    proxy: "str | None"     # benchmark index or ETF used to roll the last annual reading forward
    proxy_currency: "str | None"


MARKETS = [
    Market("USA", "United States", "us", "USD", "^GSPC", "USD"),
    Market("CAN", "Canada", "ca", "CAD", "^GSPTSE", "CAD"),
    Market("MEX", "Mexico", "mx", "MXN", "^MXX", "MXN"),
    Market("BRA", "Brazil", "br", "BRL", "^BVSP", "BRL"),
    Market("ARG", "Argentina", "ar", "ARS", "^MERV", "ARS"),
    Market("CHL", "Chile", "cl", "CLP", "ECH", "USD"),
    Market("GBR", "United Kingdom", "gb", "GBP", "^FTSE", "GBP"),
    Market("IRL", "Ireland", "ie", "EUR", "^ISEQ", "EUR"),
    Market("DEU", "Germany", "de", "EUR", "^GDAXI", "EUR"),
    Market("FRA", "France", "fr", "EUR", "^FCHI", "EUR"),
    Market("NLD", "Netherlands", "nl", "EUR", "^AEX", "EUR"),
    Market("BEL", "Belgium", "be", "EUR", "^BFX", "EUR"),
    Market("ESP", "Spain", "es", "EUR", "^IBEX", "EUR"),
    Market("PRT", "Portugal", "pt", "EUR", "PSI20.LS", "EUR"),
    Market("ITA", "Italy", "it", "EUR", "FTSEMIB.MI", "EUR"),
    Market("AUT", "Austria", "at", "EUR", "^ATX", "EUR"),
    Market("CHE", "Switzerland", "ch", "CHF", "^SSMI", "CHF"),
    Market("SWE", "Sweden", "se", "SEK", "^OMX", "SEK"),
    Market("NOR", "Norway", "no", "NOK", "OSEBX.OL", "NOK"),
    Market("DNK", "Denmark", "dk", "DKK", "^OMXC25", "DKK"),
    Market("FIN", "Finland", "fi", "EUR", "^OMXH25", "EUR"),
    Market("POL", "Poland", "pl", "PLN", "ETFBW20TR.WA", "PLN"),
    Market("CZE", "Czechia", "cz", "CZK", None, None),
    Market("HUN", "Hungary", "hu", "HUF", None, None),
    Market("GRC", "Greece", "gr", "EUR", "GD.AT", "EUR"),
    Market("TUR", "Turkey", "tr", "TRY", "XU100.IS", "TRY"),
    Market("ISR", "Israel", "il", "ILS", "TA35.TA", "ILS"),
    Market("SAU", "Saudi Arabia", "sa", "SAR", "KSA", "USD"),
    Market("EGY", "Egypt", "eg", "EGP", None, None),
    Market("ZAF", "South Africa", "za", "ZAR", "^J203.JO", "ZAR"),
    Market("IND", "India", "in", "INR", "^NSEI", "INR"),
    Market("CHN", "China", "cn", "CNY", "000001.SS", "CNY"),
    Market("HKG", "Hong Kong", "hk", "HKD", "^HSI", "HKD"),
    Market("TWN", "Taiwan", "tw", "TWD", "^TWII", "TWD"),
    Market("KOR", "South Korea", "kr", "KRW", "^KS11", "KRW"),
    Market("JPN", "Japan", "jp", "JPY", "^N225", "JPY"),
    Market("SGP", "Singapore", "sg", "SGD", "^STI", "SGD"),
    Market("MYS", "Malaysia", "my", "MYR", "^KLSE", "MYR"),
    Market("IDN", "Indonesia", "id", "IDR", "^JKSE", "IDR"),
    Market("THA", "Thailand", "th", "THB", "THD", "USD"),
    Market("PHL", "Philippines", "ph", "PHP", "EPHE", "USD"),
    Market("VNM", "Vietnam", "vn", "VND", "VNM", "USD"),
    Market("AUS", "Australia", "au", "AUD", "^AXJO", "AUD"),
    Market("NZL", "New Zealand", "nz", "NZD", "^NZ50", "NZD"),
]

BY_ISO = {m.iso3: m for m in MARKETS}
BY_REGION = {m.region: m for m in MARKETS}

ISO2 = {
    "USA": "US", "CAN": "CA", "MEX": "MX", "BRA": "BR", "ARG": "AR", "CHL": "CL", "GBR": "GB", "IRL": "IE",
    "DEU": "DE", "FRA": "FR", "NLD": "NL", "BEL": "BE", "ESP": "ES", "PRT": "PT", "ITA": "IT", "AUT": "AT",
    "CHE": "CH", "SWE": "SE", "NOR": "NO", "DNK": "DK", "FIN": "FI", "POL": "PL", "CZE": "CZ", "HUN": "HU",
    "GRC": "GR", "TUR": "TR", "ISR": "IL", "SAU": "SA", "EGY": "EG", "ZAF": "ZA", "IND": "IN", "CHN": "CN",
    "HKG": "HK", "TWN": "TW", "KOR": "KR", "JPN": "JP", "SGP": "SG", "MYS": "MY", "IDN": "ID", "THA": "TH",
    "PHL": "PH", "VNM": "VN", "AUS": "AU", "NZL": "NZ",
}

WB_CPI = "FP.CPI.TOTL.ZG"
FRED_BOND = "IRLTLT01{iso2}M156N"   # OECD long-term government bond yields, monthly
EURO_AREA = "EMU"


def reference_country(currency: "str | None") -> "str | None":
    """whose inflation describes a currency. the euro gets the euro area as a whole."""
    if currency == "EUR":
        return EURO_AREA
    for m in MARKETS:
        if m.currency == currency:
            return m.iso3
    return None


def _world_bank(indicator: str) -> pd.DataFrame:
    resp = requests.get(WB_URL.format(indicator=indicator), timeout=60)
    resp.raise_for_status()
    wanted = set(BY_ISO) | {EURO_AREA}
    rows = [
        (r["countryiso3code"], f"{r['date']}-12-31", r["value"])
        for r in resp.json()[1] or []
        if r["value"] is not None and r["countryiso3code"] in wanted
    ]
    return pd.DataFrame(rows, columns=["iso3", "date", "value"])


def refresh(con) -> None:
    series = ((WB_MCAP, "mcap_gdp", 0.01), (WB_GDP_LCU, "gdp_lcu", 1.0), (WB_CPI, "cpi", 0.01))
    for indicator, prefix, scale in series:
        try:
            frame = _world_bank(indicator)
        except Exception as exc:
            logger.warning("World Bank %s failed: %s", indicator, exc)
            continue
        for iso3, group in frame.groupby("iso3"):
            data = group.assign(date=pd.to_datetime(group["date"]).dt.date, value=group["value"] * scale)
            store.replace_macro(con, f"{prefix}:{iso3}", data[["date", "value"]])
    for m in MARKETS:
        if m.iso3 != "USA":
            try:
                bonds = macro.fetch_series(FRED_BOND.format(iso2=ISO2[m.iso3]))
                store.replace_macro(con, f"bond10y:{m.iso3}", bonds)
            except Exception:
                pass
        if m.proxy:
            px.ensure(con, m.proxy)
            if m.proxy_currency != m.currency:
                fx.series(con, m.proxy_currency, m.currency)


def bond_yield(con, iso3: "str | None", as_of=None) -> "float | None":
    """local 10-year government yield as a fraction, if a reasonably fresh one exists."""
    if iso3 == "USA":
        value, _ = macro.latest(con, "treasury_10y", as_of)
        return None if value is None else value / 100.0
    value, when = macro.latest(con, f"bond10y:{iso3}", as_of)
    if value is None or (pd.Timestamp(as_of or pd.Timestamp.today()) - when).days > 400:
        return None
    return value / 100.0


def inflation(con, currency: "str | None", years: int = 5) -> "float | None":
    country = reference_country(currency)
    if country is None:
        return None
    s = store.load_macro(con, f"cpi:{country}").tail(years)
    return None if s.empty else float(s.median())


def to_base(con, expected: "float | None", currency: "str | None", base: str) -> "float | None":
    """a local-currency yearly return re-expressed in the base currency.

    over ten years exchange rates track inflation differences more than
    anything else (relative purchasing power parity), so a 20% return in a
    currency losing 15% a year to inflation is worth far less in zloty than
    a 12% return in francs.
    """
    if expected is None or currency is None:
        return None
    if currency == base:
        return expected
    local, home = inflation(con, currency), inflation(con, base)
    if local is None or home is None:
        return None
    return (1 + expected) * (1 + home) / (1 + local) - 1


def _proxy_in_local(con, m: Market) -> pd.Series:
    empty = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    if not m.proxy:
        return empty
    frame = store.load_prices(con, m.proxy)
    if frame.empty:
        return empty
    frame["date"] = pd.to_datetime(frame["date"])
    if m.proxy_currency != m.currency:
        frame = fx.convert_prices(con, frame, m.proxy_currency, m.currency)
        if frame is None or frame.empty:
            return pd.Series(dtype=float)
    return frame.set_index("date")["close"].dropna()


def _regime(z: float) -> "tuple[str, float]":
    for upper, label, cash in macro.REGIMES:
        if z < upper:
            return label, cash
    return macro.REGIMES[-1][1], macro.REGIMES[-1][2]


def reading(con, iso3: str, as_of=None) -> "dict | None":
    m = BY_ISO.get(iso3)
    if m is None:
        return None
    if iso3 == "USA":
        us = macro.market_cap_to_gdp(con, as_of)
        if us:
            us.update(iso3="USA", name=m.name, source="Fed Z.1 / BEA, quarterly", base_date=us["date"],
                      rolled=True, stale=False, confidence="high")
        return us

    ratio = store.load_macro(con, f"mcap_gdp:{iso3}")
    if as_of is not None:
        ratio = ratio[ratio.index <= pd.Timestamp(as_of)]
    ratio = ratio[ratio > 0]
    if len(ratio) < 8:
        return None

    base_date, base = ratio.index[-1], float(ratio.iloc[-1])
    value, value_date, rolled = base, base_date, False
    proxy = _proxy_in_local(con, m)
    if as_of is not None:
        proxy = proxy[proxy.index <= pd.Timestamp(as_of)]
    then = proxy[proxy.index <= base_date]
    if not proxy.empty and not then.empty and proxy.index[-1] > base_date:
        value *= float(proxy.iloc[-1]) / float(then.iloc[-1])
        value_date, rolled = proxy.index[-1], True
        gdp = store.load_macro(con, f"gdp_lcu:{iso3}")
        gdp = gdp[gdp.index <= base_date].tail(4)
        if len(gdp) >= 2 and gdp.iloc[0] > 0:
            growth = (gdp.iloc[-1] / gdp.iloc[0]) ** (1 / (len(gdp) - 1)) - 1
            years = (value_date - base_date).days / 365.25
            value /= (1 + growth) ** years

    years = (ratio.index - ratio.index[0]).days / 365.25
    logs = np.log(ratio.values)
    slope, intercept = np.polyfit(years, logs, 1)
    spread = float(np.std(logs - (slope * years + intercept)))
    now = (pd.Timestamp(value_date) - ratio.index[0]).days / 365.25
    trend = float(np.exp(slope * now + intercept))
    z = float((np.log(value) - np.log(trend)) / spread) if spread > 0 else 0.0
    label, cash = _regime(z)

    history = pd.DataFrame({"ratio": ratio, "trend": np.exp(slope * years + intercept)}, index=ratio.index)
    if pd.Timestamp(value_date) > history.index[-1]:
        history.loc[pd.Timestamp(value_date)] = [value, trend]
    stale = (pd.Timestamp.today() - pd.Timestamp(value_date)).days > 400
    base_age = (pd.Timestamp.today() - base_date).days / 365.25
    if stale:
        confidence = "stale"
    elif base_age <= 2:
        confidence = "high"
    elif base_age <= 5:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "iso3": iso3, "name": m.name, "value": value, "date": pd.Timestamp(value_date).date(),
        "base_date": base_date.date(), "rolled": rolled, "stale": stale, "trend": trend, "z": z,
        "regime": label, "suggested_cash": cash, "history": history, "confidence": confidence,
        "source": f"World Bank, rolled forward with {m.proxy}" if rolled else "World Bank, annual",
    }


def all_readings(con, as_of=None) -> list:
    out = []
    for m in MARKETS:
        try:
            r = reading(con, m.iso3, as_of)
        except Exception as exc:
            logger.warning("market reading failed for %s: %s", m.iso3, exc)
            r = None
        out.append(r or {"iso3": m.iso3, "name": m.name, "value": None})
    return out
