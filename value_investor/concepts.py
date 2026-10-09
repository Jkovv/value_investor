"""06 · concepts: which XBRL tags feed which line of the statements.

Companies tag the same line differently, and the same company changes tags
over time (revenue moved to RevenueFromContractWithCustomer... in 2018).
Each field lists its tags in order of preference; the first one present for
a given year wins, so a mid-history tag change doesn't drop years.

An alternative can also be ("sum", [...]): added up from whatever parts
were filed, for lines like SG&A that some companies only report in pieces.

ifrs-full covers foreign filers (20-F) today and ESEF filings later.
"""

DURATION = "duration"
INSTANT = "instant"

G = "us-gaap"
I = "ifrs-full"


def _sum(*names):
    return ("sum", list(names))


FIELDS = {
    # income statement
    "revenue": (DURATION, {
        G: ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
            "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RevenuesNetOfInterestExpense"],
        I: ["Revenue", "RevenueFromContractsWithCustomers"],
    }),
    "cost_of_revenue": (DURATION, {
        G: ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
            "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization", "CostOfServices"],
        I: ["CostOfSales"],
    }),
    "gross_profit": (DURATION, {G: ["GrossProfit"], I: ["GrossProfit"]}),
    "sga": (DURATION, {
        G: ["SellingGeneralAndAdministrativeExpense",
            _sum("SellingAndMarketingExpense", "GeneralAndAdministrativeExpense")],
        I: ["SellingGeneralAndAdministrativeExpense", _sum("DistributionCosts", "AdministrativeExpense")],
    }),
    "rnd": (DURATION, {
        G: ["ResearchAndDevelopmentExpense", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"],
        I: ["ResearchAndDevelopmentExpense"],
    }),
    "depreciation": (DURATION, {
        G: ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization", "Depreciation"],
        I: ["DepreciationAndAmortisationExpense",
            "DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss"],
    }),
    "operating_income": (DURATION, {G: ["OperatingIncomeLoss"], I: ["ProfitLossFromOperatingActivities"]}),
    "interest_expense": (DURATION, {
        G: ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"],
        I: ["InterestExpense", "FinanceCosts"],
    }),
    "pretax_income": (DURATION, {
        G: ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
        I: ["ProfitLossBeforeTax"],
    }),
    "income_tax": (DURATION, {G: ["IncomeTaxExpenseBenefit"], I: ["IncomeTaxExpenseContinuingOperations"]}),
    "net_income": (DURATION, {
        G: ["NetIncomeLoss", "NetIncomeLossAvailableToCommonStockholdersBasic", "ProfitLoss"],
        I: ["ProfitLossAttributableToOwnersOfParent", "ProfitLoss"],
    }),
    "eps_diluted": (DURATION, {
        G: ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
        I: ["DilutedEarningsLossPerShare", "BasicAndDilutedEarningsLossPerShare"],
    }),
    "shares_diluted": (DURATION, {
        G: ["WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
            "WeightedAverageNumberOfSharesOutstandingBasic"],
        I: ["AdjustedWeightedAverageShares", "WeightedAverageShares"],
    }),
    "dps_declared": (DURATION, {
        G: ["CommonStockDividendsPerShareDeclared", "CommonStockDividendsPerShareCashPaid"],
        I: [],
    }),

    # balance sheet
    "cash": (INSTANT, {
        G: ["CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash", "CashAndDueFromBanks"],
        I: ["CashAndCashEquivalents"],
    }),
    "short_term_investments": (INSTANT, {
        G: ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
        I: ["CurrentInvestments"],
    }),
    "receivables": (INSTANT, {
        G: ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"],
        I: ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"],
    }),
    "inventory": (INSTANT, {G: ["InventoryNet"], I: ["Inventories"]}),
    "current_assets": (INSTANT, {G: ["AssetsCurrent"], I: ["CurrentAssets"]}),
    "ppe": (INSTANT, {
        G: ["PropertyPlantAndEquipmentNet",
            "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
        I: ["PropertyPlantAndEquipment"],
    }),
    "goodwill": (INSTANT, {G: ["Goodwill"], I: ["Goodwill"]}),
    "intangibles": (INSTANT, {
        G: ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"],
        I: ["IntangibleAssetsOtherThanGoodwill"],
    }),
    "total_assets": (INSTANT, {G: ["Assets"], I: ["Assets"]}),
    "current_liabilities": (INSTANT, {G: ["LiabilitiesCurrent"], I: ["CurrentLiabilities"]}),
    "short_term_debt": (INSTANT, {
        G: ["DebtCurrent", _sum("ShortTermBorrowings", "CommercialPaper", "LongTermDebtCurrent")],
        I: ["CurrentBorrowings", _sum("ShorttermBorrowings", "CurrentPortionOfLongtermBorrowings")],
    }),
    "long_term_debt": (INSTANT, {
        G: ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebt"],
        I: ["NoncurrentPortionOfNoncurrentBorrowings", "LongtermBorrowings"],
    }),
    "total_liabilities": (INSTANT, {G: ["Liabilities"], I: ["Liabilities"]}),
    "liabilities_and_equity": (INSTANT, {G: ["LiabilitiesAndStockholdersEquity"], I: ["EquityAndLiabilities"]}),
    "equity": (INSTANT, {
        G: ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        I: ["EquityAttributableToOwnersOfParent", "Equity"],
    }),
    "equity_incl_nci": (INSTANT, {
        G: ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"],
        I: ["Equity"],
    }),
    "retained_earnings": (INSTANT, {G: ["RetainedEarningsAccumulatedDeficit"], I: ["RetainedEarnings"]}),
    "treasury_stock": (INSTANT, {G: ["TreasuryStockValue", "TreasuryStockCommonValue"], I: ["TreasuryShares"]}),
    "preferred_stock": (INSTANT, {G: ["PreferredStockValue", "PreferredStockValueOutstanding"], I: []}),

    # cash flow statement
    "operating_cash_flow": (DURATION, {
        G: ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
        I: ["CashFlowsFromUsedInOperatingActivities"],
    }),
    "capex": (DURATION, {
        G: ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
            "PaymentsForCapitalImprovements"],
        I: ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"],
    }),
    "buybacks": (DURATION, {
        G: ["PaymentsForRepurchaseOfCommonStock", "PaymentsForRepurchaseOfEquity"],
        I: ["PaymentsToAcquireOrRedeemEntitysShares"],
    }),
    "dividends_paid": (DURATION, {
        G: ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock", "PaymentsOfOrdinaryDividends"],
        I: ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],
    }),
    "stock_issued": (DURATION, {G: ["ProceedsFromIssuanceOfCommonStock"], I: ["ProceedsFromIssuingShares"]}),
    "taxes_paid": (DURATION, {
        G: ["IncomeTaxesPaidNet", "IncomeTaxesPaid"],
        I: ["IncomeTaxesPaidRefundClassifiedAsOperatingActivities"],
    }),
}

# Values the statements always show as positive amounts, whatever sign the filer used.
# Yahoo Finance rows, used for every company outside the US. Same fields,
# same preference order rules, so the rest of the pipeline can't tell the
# difference apart from the shorter history.
Y = "yahoo"
YAHOO = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "cost_of_revenue": ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit": ["Gross Profit"],
    "sga": ["Selling General And Administration", _sum("Selling And Marketing Expense", "General And Administrative Expense")],
    "rnd": ["Research And Development"],
    "depreciation": ["Reconciled Depreciation", "Depreciation And Amortization", "Depreciation Amortization Depletion"],
    "operating_income": ["Operating Income", "Total Operating Income As Reported"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "pretax_income": ["Pretax Income"],
    "income_tax": ["Tax Provision"],
    "net_income": ["Net Income Common Stockholders", "Net Income", "Net Income From Continuing Operation Net Minority Interest"],
    "eps_diluted": ["Diluted EPS", "Basic EPS"],
    "shares_diluted": ["Diluted Average Shares", "Basic Average Shares"],
    "cash": ["Cash And Cash Equivalents", "Cash Financial"],
    "short_term_investments": ["Other Short Term Investments"],
    "receivables": ["Accounts Receivable", "Receivables"],
    "inventory": ["Inventory"],
    "current_assets": ["Current Assets"],
    "ppe": ["Net PPE"],
    "goodwill": ["Goodwill"],
    "intangibles": ["Other Intangible Assets"],
    "total_assets": ["Total Assets"],
    "current_liabilities": ["Current Liabilities"],
    "short_term_debt": ["Current Debt", "Current Debt And Capital Lease Obligation"],
    "long_term_debt": ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "total_liabilities": ["Total Liabilities Net Minority Interest"],
    "equity": ["Stockholders Equity", "Common Stock Equity"],
    "equity_incl_nci": ["Total Equity Gross Minority Interest"],
    "retained_earnings": ["Retained Earnings"],
    "treasury_stock": ["Treasury Stock"],
    "preferred_stock": ["Preferred Stock"],
    "operating_cash_flow": ["Operating Cash Flow"],
    "capex": ["Capital Expenditure", "Purchase Of PPE"],
    "buybacks": ["Repurchase Of Capital Stock", "Common Stock Payments"],
    "dividends_paid": ["Cash Dividends Paid", "Common Stock Dividend Paid"],
    "stock_issued": ["Issuance Of Capital Stock", "Common Stock Issuance"],
    "taxes_paid": ["Income Tax Paid Supplemental Data", "Taxes Refund Paid"],
}
for _field, _names in YAHOO.items():
    FIELDS[_field][1][Y] = _names

YAHOO_PER_SHARE_ROWS = {"Diluted EPS", "Basic EPS"}
YAHOO_SHARE_ROWS = {"Diluted Average Shares", "Basic Average Shares"}

ALWAYS_POSITIVE = {"capex", "buybacks", "dividends_paid", "treasury_stock", "interest_expense", "taxes_paid"}

PER_SHARE = {"eps_diluted", "dps_declared"}
SHARE_COUNTS = {"shares_diluted"}


def alternatives(field: str, taxonomy: str) -> list:
    return FIELDS[field][1].get(taxonomy, [])


def kind(field: str) -> str:
    return FIELDS[field][0]


def wanted_concepts() -> set:
    wanted = set()
    for _, by_taxonomy in FIELDS.values():
        for taxonomy, alts in by_taxonomy.items():
            for alt in alts:
                names = alt[1] if isinstance(alt, tuple) else [alt]
                wanted.update((taxonomy, n) for n in names)
    return wanted
