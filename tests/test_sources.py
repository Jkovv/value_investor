from datetime import date

import pytest

from value_investor import china


def test_bonus_shares_are_found_from_the_jump_in_shares():
    # 1.4 bonus in mid 2021; the 2020 count is already restated, so only 2019 and before move
    counts = {date(2018, 12, 31): 868e6, date(2019, 12, 31): 868e6, date(2020, 12, 31): 1217e6,
              date(2021, 12, 31): 1217e6}
    f = china.bonus_factors(counts, [(date(2021, 7, 5), 1.4), (date(2012, 6, 12), 2.0)])
    assert f[date(2021, 12, 31)] == 1.0 and f[date(2020, 12, 31)] == 1.0
    assert f[date(2019, 12, 31)] == pytest.approx(1.4) and f[date(2018, 12, 31)] == pytest.approx(1.4)


def test_a_new_share_issue_is_not_mistaken_for_a_bonus():
    counts = {date(2019, 12, 31): 100e6, date(2020, 12, 31): 123e6}
    assert china.bonus_factors(counts, [(date(2020, 6, 1), 1.5)])[date(2019, 12, 31)] == 1.0


def test_eastmoney_records_become_facts_in_todays_units():
    records = {
        "2019-12-31": {"NOTICE_DATE": "2020-04-20", "TOTAL_OPERATE_INCOME": 100.0, "OPERATE_COST": 40.0,
                       "PARENT_NETPROFIT": 20.0, "DILUTED_EPS": 2.0, "SALE_EXPENSE": 5.0, "MANAGE_EXPENSE": 5.0,
                       "UNASSIGN_RPOFIT": 50.0, "SURPLUS_RESERVE": 10.0, "ASSIGN_DIVIDEND_PORFIT": 9.0,
                       "FE_INTEREST_EXPENSE": 1.0},
        "2020-12-31": {"NOTICE_DATE": "2021-04-20", "TOTAL_OPERATE_INCOME": 120.0, "PARENT_NETPROFIT": 24.0,
                       "DILUTED_EPS": 1.2},
    }
    facts = china.facts_from(records, [(date(2020, 6, 1), 2.0)])
    get = lambda concept, end: facts[(facts["concept"] == concept) & (facts["period_end"] == date(*end))]["value"].iloc[0]
    assert get("eps_diluted", (2019, 12, 31)) == pytest.approx(1.0)        # halved for the 2-for-1
    assert get("shares_diluted", (2019, 12, 31)) == pytest.approx(20.0)
    assert get("sga", (2019, 12, 31)) == 10.0
    assert get("retained_earnings", (2019, 12, 31)) == 60.0
    assert get("dividends_paid", (2019, 12, 31)) == 8.0                     # less interest paid
    assert set(facts["taxonomy"]) == {"eastmoney"}
    assert facts[facts["concept"] == "net_income"]["filed"].min() == date(2020, 4, 20)


def test_symbols_map_between_yahoo_and_eastmoney():
    assert china.em_code("600519.SS") == "SH600519"
    assert china.em_code("000858.SZ") == "SZ000858"
    assert china.yahoo_symbol("600519") == "600519.SS"
    assert china.yahoo_symbol("300750") == "300750.SZ"
    assert china.em_code("7203.T") is None


def table(revenue, net_income, currency, year=2024):
    import pandas as pd
    t = pd.DataFrame({"revenue": [revenue], "net_income": [net_income]},
                     index=pd.DatetimeIndex([f"{year}-12-31"]))
    t.attrs["currency"] = currency
    return t


def test_sec_names_match_loosely():
    from value_investor import foreign
    assert foreign.name_key("TAIWAN SEMICONDUCTOR MANUFACTURING CO LTD") == \
        foreign.name_key("Taiwan Semiconductor Manufacturing Company Limited")
    assert foreign.name_key("Banco Santander (Brasil) S.A.") == foreign.name_key("BANCO SANTANDER (BRASIL) S.A.")


def test_a_shared_name_is_not_enough(monkeypatch):
    from value_investor import foreign
    assert foreign.agrees(None, table(100.0, 10.0, "EUR"), table(103.0, 10.2, "EUR"))
    assert not foreign.agrees(None, table(100.0, 10.0, "EUR"), table(400.0, 55.0, "EUR"))


def test_net_income_is_enough_for_banks_and_currencies_convert(monkeypatch):
    from value_investor import foreign, fx
    monkeypatch.setattr(fx, "rate", lambda con, base, quote, when=None, fetch=True: 5.0)
    # revenue defined differently, net income the same once dollars become reais
    assert foreign.agrees(None, table(100.0, 50.0, "BRL"), table(40.0, 10.0, "USD"))
    # yahoo's figures labelled reais but really dollars: the raw numbers match
    assert foreign.agrees(None, table(100.0, 10.0, "BRL"), table(100.0, 10.0, "USD"))


def cvm_rows(end, rows):
    import pandas as pd
    return pd.DataFrame([{"DT_FIM_EXERC": end, "FILED": "2025-02-20", "CD_CONTA": c, "DS_CONTA": d, "VL_CONTA": v}
                         for c, d, v in rows])


def test_cvm_industrial_chart_maps_by_code():
    from value_investor import brazil
    facts = brazil._company_facts(cvm_rows("2024-12-31", [
        ("3.01", "Receita de Venda de Bens e/ou Serviços", 100.0),
        ("3.02", "Custo dos Bens e/ou Serviços Vendidos", -60.0),
        ("3.04.01", "Despesas com Vendas", -5.0), ("3.04.02", "Despesas Gerais e Administrativas", -5.0),
        ("3.05", "Resultado Antes do Resultado Financeiro e dos Tributos", 30.0),
        ("3.07", "Resultado Antes dos Tributos sobre o Lucro", 28.0),
        ("3.08", "Imposto de Renda e Contribuição Social sobre o Lucro", -8.0),
        ("3.11", "Lucro/Prejuízo Consolidado do Período", 20.0),
        ("3.11.01", "Atribuído a Sócios da Empresa Controladora", 18.0),
        ("3.99.02.01", "ON", 1.8),
    ]))
    got = dict(zip(facts["concept"], facts["value"]))
    assert got["revenue"] == 100.0 and got["cost_of_revenue"] == 60.0 and got["sga"] == 10.0
    assert got["operating_income"] == 30.0 and got["pretax_income"] == 28.0 and got["income_tax"] == 8.0
    assert got["net_income"] == 18.0 and got["shares_diluted"] == pytest.approx(10.0)
    assert facts["filed"].iloc[0] == date(2025, 2, 20)


def test_cvm_bank_chart_is_read_by_name():
    from value_investor import brazil
    facts = brazil._company_facts(cvm_rows("2024-12-31", [
        ("3.01", "Receitas da Intermediação Financeira", 500.0),
        ("3.05", "Resultado Antes dos Tributos sobre o Lucro", 50.0),
        ("3.06", "Imposto de Renda e Contribuição Social sobre o Lucro", -10.0),
        ("3.07", "Resultado Líquido das Operações Continuadas", 40.0),
        ("3.09", "Lucro ou Prejuízo Líquido Consolidado do Período", 40.0),
        ("3.09.01", "Atribuído a Sócios da Empresa Controladora", 38.0),
    ]))
    got = dict(zip(facts["concept"], facts["value"]))
    assert got["pretax_income"] == 50.0 and got["income_tax"] == 10.0 and got["net_income"] == 38.0
    assert "operating_income" not in got          # a bank's 3.05 is pre-tax, not ebit


def test_cvm_eps_per_thousand_shares_is_scaled_back():
    import pandas as pd
    from value_investor import brazil
    frames = [cvm_rows(f"{y}-12-31", [("3.11.01", "Atribuído a Sócios da Empresa Controladora", 100.0),
                                      ("3.99.02.01", "ON", eps)])
              for y, eps in ((2021, 1.8), (2022, 1900.0), (2023, 2.1))]
    facts = brazil._company_facts(pd.concat(frames, ignore_index=True))
    eps = facts[facts["concept"] == "eps_diluted"].sort_values("period_end")["value"].tolist()
    assert eps == pytest.approx([1.8, 1.9, 2.1])


def test_screener_rows_become_facts_in_rupees():
    from value_investor import india
    end = date(2024, 3, 31)
    pl = {"Sales": {end: 1000.0}, "Profit before tax": {end: 200.0}, "Tax %": {end: 25.0},
          "Net Profit": {end: 150.0}, "EPS in Rs": {end: 15.0}, "Interest": {end: 10.0},
          "Dividend Payout %": {end: 40.0}}
    bs = {"Equity Capital": {end: 10.0}, "Reserves": {end: 590.0}, "Total Liabilities": {end: 1500.0}}
    cf = {"Cash from Operating Activity": {end: 180.0}, "Free Cash Flow": {end: 120.0}}
    facts = india.facts_from(pl, bs, cf)
    got = dict(zip(facts["concept"], facts["value"]))
    assert got["revenue"] == 1000.0 * india.CRORE
    assert got["operating_income"] == 210.0 * india.CRORE
    assert got["income_tax"] == 50.0 * india.CRORE
    assert got["equity"] == 600.0 * india.CRORE and got["total_liabilities"] == 900.0 * india.CRORE
    assert got["capex"] == 60.0 * india.CRORE and got["dividends_paid"] == 60.0 * india.CRORE
    assert got["eps_diluted"] == 15.0 and got["shares_diluted"] == pytest.approx(10.0 * india.CRORE)


def test_finmind_quarters_add_up_to_a_year():
    import pandas as pd
    from value_investor import taiwan
    quarters = ["2023-03-31", "2023-06-30", "2023-09-30", "2023-12-31"]
    income = pd.DataFrame([{"date": d, "type": t, "value": v} for d in quarters
                           for t, v in (("Revenue", 25.0), ("EquityAttributableToOwnersOfParent", 5.0), ("EPS", 0.5))])
    balance = pd.DataFrame([{"date": "2023-12-31", "type": "TotalAssets", "value": 300.0}])
    cash = pd.DataFrame([{"date": "2023-12-31", "type": "PropertyAndPlantAndEquipment", "value": -12.0}])
    facts = taiwan.facts_from(income, balance, cash)
    got = dict(zip(facts["concept"], facts["value"]))
    assert got["revenue"] == 100.0 and got["net_income"] == 20.0 and got["eps_diluted"] == 2.0
    assert got["total_assets"] == 300.0 and got["capex"] == 12.0
    assert facts[facts["concept"] == "total_assets"]["period_start"].isna().all()


def test_hong_kong_currency_is_settled_against_yahoo(monkeypatch):
    from value_investor import fx, hongkong, statements, store
    rows = [{"STD_REPORT_DATE": "2024-12-31 00:00:00", "HOLDER_PROFIT": 100.0, "OPERATE_INCOME": 900.0,
             "DILUTED_EPS": 2.0}]
    facts = hongkong.facts_from(rows, "XXX")
    monkeypatch.setattr(store, "load_facts", lambda con, cik: None)
    monkeypatch.setattr(fx, "rate", lambda con, base, quote, when=None, fetch=True: {"CNY": 1.08, "USD": 7.8}.get(base))
    # yahoo shows hong kong dollars; eastmoney's 100 only fits as yuan, and becomes 108 dollars
    monkeypatch.setattr(statements, "annual_statements", lambda facts: table(970.0, 108.0, "HKD"))
    settled = hongkong.settle(None, 1, facts)
    got = dict(zip(settled["concept"], settled["value"]))
    assert set(settled["unit"]) == {"HKD", "HKD/shares", "shares"}
    assert got["net_income"] == pytest.approx(108.0) and got["eps_diluted"] == pytest.approx(2.16)
    assert got["shares_diluted"] == pytest.approx(50.0)
    # nothing fits: nothing is kept
    monkeypatch.setattr(statements, "annual_statements", lambda facts: table(970.0, 400.0, "HKD"))
    assert hongkong.settle(None, 1, facts).empty


def test_a_foreign_listing_beside_an_american_one_needs_real_turnover(monkeypatch):
    import pandas as pd
    from value_investor import fx, yahoo
    monkeypatch.setattr(fx, "rate", lambda con, base, quote, when=None, fetch=True: {"HKD": 0.13, "EUR": 1.1}.get(base))
    df = pd.DataFrame([
        {"market": "USA", "board": "HSBC", "currency": "USD", "financial_currency": "USD", "turnover": 50e6},
        {"market": "HKG", "board": "HSBC", "currency": "HKD", "financial_currency": "USD", "turnover": 1e9},
        {"market": "USA", "board": "AAPL", "currency": "USD", "financial_currency": "USD", "turnover": 10e9},
        {"market": "DEU", "board": "AAPL", "currency": "EUR", "financial_currency": "USD", "turnover": 5e6},
        {"market": "DEU", "board": "SAP", "currency": "EUR", "financial_currency": "EUR", "turnover": 1e8},
    ])
    kept = yahoo._drop_american(None, df)
    assert sorted(zip(kept["market"], kept["board"])) == [("DEU", "SAP"), ("HKG", "HSBC")]


def test_a_hong_kong_year_reported_twice_counts_once():
    from value_investor import hongkong
    rows = [{"STD_REPORT_DATE": "2024-12-31 00:00:00", "HOLDER_PROFIT": 110.0},
            {"STD_REPORT_DATE": "2024-12-31 00:00:00", "HOLDER_PROFIT": 100.0}]
    facts = hongkong.facts_from(rows, "HKD")
    assert facts[facts["concept"] == "net_income"]["value"].tolist() == [110.0]


def test_cvm_total_profit_stands_in_when_the_parent_share_is_left_at_zero():
    from value_investor import brazil
    facts = brazil._company_facts(cvm_rows("2024-12-31", [
        ("3.11", "Lucro/Prejuízo Consolidado do Período", 45.0),
        ("3.11.01", "Atribuído a Sócios da Empresa Controladora", 0.0),
    ]))
    assert dict(zip(facts["concept"], facts["value"]))["net_income"] == 45.0


def test_b3_codes_find_their_company():
    from value_investor import brazil
    codes = {"PETR4": "33000167000101", "MRSA3": "01417222000177", "MRSA5": "01417222000177"}
    issuers = {"BPAC": "30306294000145"}
    assert brazil.cnpj_for("PETR4", codes, issuers) == "33000167000101"
    assert brazil.cnpj_for("BPAC11", codes, issuers) == "30306294000145"     # a unit, through b3's issuer code
    assert brazil.cnpj_for("MRSA3B", codes, issuers) == "01417222000177"     # same root in the register
    assert brazil.cnpj_for("XXXX3", codes, issuers) is None
    assert brazil._digits("1417222000177") == "01417222000177"


def test_a_june_year_end_in_hong_kong_keeps_its_own_dates():
    from value_investor import hongkong
    rows = [{"STD_REPORT_DATE": "2023-12-31 00:00:00", "REPORT_DATE": "2024-06-30 00:00:00",
             "START_DATE": "2023-07-01 00:00:00", "HOLDER_PROFIT": 17.0}]
    facts = hongkong.facts_from(rows, "HKD")
    assert facts["period_end"].iloc[0] == date(2024, 6, 30) and facts["period_start"].iloc[0] == date(2023, 7, 1)
