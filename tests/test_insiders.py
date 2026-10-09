from datetime import date, timedelta

import duckdb

from value_investor import insiders, store

FORM4 = """<?xml version="1.0"?>
<ownershipDocument>
  <issuer><issuerCik>0000021344</issuerCik><issuerName>COCA COLA CO</issuerName></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>SMITH JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>{relationship}</reportingOwnerRelationship>
  </reportingOwner>
  <aff10b5One>{plan}</aff10b5One>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-08-20</value></transactionDate>
      <transactionCoding><transactionCode>{code}</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>60.5</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>{side}</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>5000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <footnotes>{notes}</footnotes>
</ownershipDocument>"""


def form4(code="P", side="A", plan="0", notes="", relationship="<isOfficer>1</isOfficer><officerTitle>CFO</officerTitle>"):
    return FORM4.format(code=code, side=side, plan=plan, notes=notes, relationship=relationship)


def test_parse_a_purchase():
    [t] = insiders.parse(form4())
    assert t["owner"] == "Smith Jane" and t["role"] == "CFO" and t["code"] == "P"
    assert t["shares"] == 1000 and t["price"] == 60.5 and t["acquired"] and not t["planned"]


def test_planned_sales_are_marked_from_the_flag_or_a_footnote():
    assert insiders.parse(form4(code="S", side="D", plan="1"))[0]["planned"]
    note = "<footnote id='F1'>Sold under a Rule 10b5-1 trading plan adopted in May.</footnote>"
    assert insiders.parse(form4(code="S", side="D", notes=note))[0]["planned"]


def test_role_falls_back_to_the_other_text():
    rel = "<isOther>1</isOther><otherText>President, Latin America</otherText>"
    assert insiders.parse(form4(relationship=rel))[0]["role"] == "President, Latin America"


def test_filings_about_another_issuer_are_dropped():
    assert insiders.parse(form4(), issuer=21344)
    assert insiders.parse(form4(), issuer=999) == []


def con_with(trades, left=0.0):
    con = duckdb.connect()
    con.execute(store.SCHEMA)
    day = date.today() - timedelta(days=20)
    for i, (owner, code, value, planned) in enumerate(trades):
        con.execute("INSERT INTO insider_filings VALUES (?, 1, ?)", [f"a{i}", day])
        con.execute("INSERT INTO insider_trades VALUES (1, ?, ?, ?, ?, 'Director', ?, ?, 10.0, ?, ?, ?)",
                    [f"a{i}", day, day - timedelta(days=i), owner, code, value / 10, code == "P", left, planned])
    return con


def test_two_buyers_read_as_buying_and_a_cluster():
    s = insiders.summary(con_with([("A", "P", 50_000, False), ("B", "P", 20_000, False), ("C", "S", 900_000, True)]), 1)
    assert s["signal"] == "buying" and s["cluster"] and s["buyers"] == 2
    assert s["unplanned_sell_value"] == 0


def test_several_insiders_emptying_their_holdings_reads_as_selling():
    sells = [("A", "S", 500_000, False), ("B", "S", 300_000, False), ("C", "S", 200_000, False)]
    assert insiders.summary(con_with(sells), 1)["signal"] == "selling"


def test_selling_a_sliver_of_a_big_holding_is_routine():
    sells = [("A", "S", 500_000, False), ("B", "S", 300_000, False), ("C", "S", 200_000, False)]
    s = insiders.summary(con_with(sells, left=1_000_000), 1)
    assert s["signal"] == "routine" and s["heavy_sellers"] == 0


def test_no_filings_means_no_summary():
    con = duckdb.connect()
    con.execute(store.SCHEMA)
    assert insiders.summary(con, 1) is None
