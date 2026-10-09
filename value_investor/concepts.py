"""06 · concepts — which XBRL tags feed which line of the statements.

Companies tag the same line differently, and the same company changes tags
over time (revenue moved to RevenueFromContractWithCustomer... in 2018).
Each field lists its tags in order of preference; the first one present for
a given year wins, so a mid-history tag change doesn't drop years.

An alternative can also be ("sum", [...]) — added up from whatever parts
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
