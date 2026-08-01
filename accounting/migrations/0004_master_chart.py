from django.db import migrations


# (code, name, type, parent_code, is_group)
# Master chart of accounts for a jewellery business.
# Group accounts are headings only — postings must go to a detail account.
CHART = [
    # ---------------------------------------------------------------- ASSETS
    ("1000", "Current Assets", "asset", None, True),

    ("1010", "Cash and Cash Equivalents", "asset", "1000", True),
    ("1011", "Cash on Hand", "asset", "1010", False),
    ("1012", "Petty Cash", "asset", "1010", False),
    ("1013", "Cash in Transit", "asset", "1010", False),
    ("1014", "Undeposited Cash Receipts", "asset", "1010", False),

    ("1020", "Bank Accounts", "asset", "1000", True),
    ("1021", "Current Bank Account", "asset", "1020", False),
    ("1022", "Payroll Bank Account", "asset", "1020", False),
    ("1023", "Collection Bank Account", "asset", "1020", False),
    ("1024", "Other Bank Accounts", "asset", "1020", False),

    ("1030", "Card and Payment Gateway Receivables", "asset", "1000", True),
    ("1031", "POS Card Receivables", "asset", "1030", False),
    ("1032", "Payment Gateway Receivables", "asset", "1030", False),
    ("1033", "Mobile Wallet Receivables", "asset", "1030", False),
    ("1034", "Card Settlement Differences", "asset", "1030", False),
    ("1035", "Payment Gateway Settlement Differences", "asset", "1030", False),

    ("1040", "Accounts Receivable", "asset", "1000", True),
    ("1041", "Retail Customer Receivables", "asset", "1040", False),
    ("1042", "Instalment Receivables — Current", "asset", "1040", False),
    ("1043", "Instalment Receivables — Non-current", "asset", "1040", False),
    ("1044", "Custom Order Receivables", "asset", "1040", False),
    ("1045", "Repair Service Receivables", "asset", "1040", False),
    ("1046", "Polishing Service Receivables", "asset", "1040", False),
    ("1047", "Employee Receivables", "asset", "1040", False),
    ("1048", "Other Receivables", "asset", "1040", False),
    ("1049", "Allowance for Doubtful Receivables", "asset", "1040", False),

    ("1050", "Advances and Prepayments", "asset", "1000", True),
    ("1051", "Advances to Suppliers", "asset", "1050", False),
    ("1052", "Prepaid Rent", "asset", "1050", False),
    ("1053", "Prepaid Insurance", "asset", "1050", False),
    ("1054", "Prepaid Software and Subscriptions", "asset", "1050", False),
    ("1055", "Other Prepaid Expenses", "asset", "1050", False),

    ("1060", "Interbranch Current Accounts", "asset", "1000", True),
    ("1061", "Due from Branches", "asset", "1060", False),
    ("1062", "Interbranch Cash Transfer Clearing", "asset", "1060", False),
    ("1063", "Interbranch Expense Allocation Clearing", "asset", "1060", False),

    # ------------------------------------------------------------- INVENTORY
    ("1200", "Inventory", "asset", None, True),

    ("1210", "Raw Gold Inventory", "asset", "1200", True),
    ("1211", "Raw Gold Inventory — 18K", "asset", "1210", False),
    ("1212", "Raw Gold Inventory — 21K", "asset", "1210", False),
    ("1213", "Raw Gold Inventory — 24K", "asset", "1210", False),

    ("1220", "Finished Gold Jewellery", "asset", "1200", True),
    ("1221", "Finished Gold Jewellery — 18K", "asset", "1220", False),
    ("1222", "Finished Gold Jewellery — 21K", "asset", "1220", False),
    ("1223", "Finished Gold Jewellery — 24K", "asset", "1220", False),

    ("1230", "Silver Inventory", "asset", "1200", True),
    ("1231", "Raw Silver Inventory", "asset", "1230", False),
    ("1232", "Finished Silver Jewellery", "asset", "1230", False),

    ("1240", "Diamond Inventory", "asset", "1200", True),
    ("1241", "Loose Diamonds", "asset", "1240", False),
    ("1242", "Diamond Jewellery", "asset", "1240", False),

    ("1250", "Gemstone Inventory", "asset", "1200", True),
    ("1251", "Loose Gemstones", "asset", "1250", False),
    ("1252", "Gemstone Jewellery", "asset", "1250", False),

    ("1260", "Custom Order Work in Progress", "asset", "1200", True),
    ("1261", "Gold Materials in Custom Order WIP", "asset", "1260", False),
    ("1262", "Silver Materials in Custom Order WIP", "asset", "1260", False),
    ("1263", "Diamonds in Custom Order WIP", "asset", "1260", False),
    ("1264", "Gemstones in Custom Order WIP", "asset", "1260", False),
    ("1265", "Direct Labour in Custom Order WIP", "asset", "1260", False),
    ("1266", "External Workshop Cost in WIP", "asset", "1260", False),

    ("1270", "Repair and Polishing Materials", "asset", "1200", True),
    ("1271", "Repair Spare Parts and Materials", "asset", "1270", False),
    ("1272", "Polishing Materials", "asset", "1270", False),
    ("1273", "Repair Work in Progress", "asset", "1270", False),

    ("1280", "Recoverable Metal and Scrap", "asset", "1200", True),
    ("1281", "Recoverable Gold Scrap — 18K", "asset", "1280", False),
    ("1282", "Recoverable Gold Scrap — 21K", "asset", "1280", False),
    ("1283", "Recoverable Gold Scrap — 24K", "asset", "1280", False),
    ("1284", "Recoverable Silver Scrap", "asset", "1280", False),
    ("1285", "Non-recoverable Waste", "asset", "1280", False),

    ("1290", "Inventory in Transit", "asset", "1200", True),
    ("1291", "Purchased Inventory in Transit", "asset", "1290", False),
    ("1292", "Interbranch Inventory in Transit", "asset", "1290", False),
    ("1293", "Inventory Count Difference Clearing", "asset", "1290", False),
    ("1294", "Packaging Inventory", "asset", "1290", False),

    # --------------------------------------------------- NON-CURRENT ASSETS
    ("1500", "Property and Equipment", "asset", None, True),
    ("1510", "Store Furniture and Fixtures", "asset", "1500", False),
    ("1520", "Display Units and Jewellery Cabinets", "asset", "1500", False),
    ("1530", "Security and Surveillance Equipment", "asset", "1500", False),
    ("1540", "Workshop Tools and Equipment", "asset", "1500", False),
    ("1550", "Polishing Machines", "asset", "1500", False),
    ("1560", "Weighing and Testing Equipment", "asset", "1500", False),
    ("1570", "Computers and POS Equipment", "asset", "1500", False),
    ("1580", "Leasehold Improvements", "asset", "1500", False),
    ("1590", "Vehicles", "asset", "1500", False),

    ("1600", "Accumulated Depreciation", "asset", None, True),
    ("1610", "Accumulated Depreciation — Furniture", "asset", "1600", False),
    ("1620", "Accumulated Depreciation — Display Units", "asset", "1600", False),
    ("1630", "Accumulated Depreciation — Security Equipment", "asset", "1600", False),
    ("1640", "Accumulated Depreciation — Workshop Equipment", "asset", "1600", False),
    ("1650", "Accumulated Depreciation — Computers and POS", "asset", "1600", False),
    ("1660", "Accumulated Depreciation — Leasehold Improvements", "asset", "1600", False),
    ("1670", "Accumulated Depreciation — Vehicles", "asset", "1600", False),

    # ----------------------------------------------------------- LIABILITIES
    ("2000", "Current Liabilities", "liability", None, True),

    ("2010", "Accounts Payable", "liability", "2000", True),
    ("2011", "Gold Suppliers Payable", "liability", "2010", False),
    ("2012", "Silver Suppliers Payable", "liability", "2010", False),
    ("2013", "Diamond Suppliers Payable", "liability", "2010", False),
    ("2014", "Gemstone Suppliers Payable", "liability", "2010", False),
    ("2015", "Jewellery Suppliers Payable", "liability", "2010", False),
    ("2016", "Workshop and Service Suppliers Payable", "liability", "2010", False),
    ("2017", "General Suppliers Payable", "liability", "2010", False),

    ("2020", "Customer Advances and Deposits", "liability", "2000", True),
    ("2021", "Customer Advances — Custom Orders", "liability", "2020", False),
    ("2022", "Customer Advances — Repairs", "liability", "2020", False),
    ("2023", "Customer Advances — Polishing", "liability", "2020", False),
    ("2024", "Customer Instalment Advances", "liability", "2020", False),
    ("2025", "Unallocated Customer Receipts", "liability", "2020", False),
    ("2026", "Customer Credit Balances", "liability", "2020", False),

    ("2030", "Accrued Expenses", "liability", "2000", True),
    ("2031", "Accrued Salaries and Wages", "liability", "2030", False),
    ("2032", "Accrued Rent", "liability", "2030", False),
    ("2033", "Accrued Utilities", "liability", "2030", False),
    ("2034", "Accrued Professional Fees", "liability", "2030", False),
    ("2035", "Accrued Workshop Charges", "liability", "2030", False),
    ("2036", "Other Accrued Expenses", "liability", "2030", False),

    ("2040", "Card and Gateway Liabilities", "liability", "2000", True),
    ("2041", "Card Refunds Payable", "liability", "2040", False),
    ("2042", "Card Chargebacks Payable", "liability", "2040", False),
    ("2043", "Payment Gateway Refunds Payable", "liability", "2040", False),

    ("2050", "Employee and Payroll Liabilities", "liability", "2000", True),
    ("2051", "Salaries Payable", "liability", "2050", False),
    ("2052", "Employee Deductions Payable", "liability", "2050", False),
    ("2053", "Staff Expense Reimbursements Payable", "liability", "2050", False),

    ("2060", "Interbranch Payables", "liability", "2000", True),
    ("2061", "Due to Branches", "liability", "2060", False),
    ("2062", "Interbranch Transfer Clearing", "liability", "2060", False),

    ("2070", "Short-Term Borrowings", "liability", "2000", True),
    ("2071", "Bank Overdraft", "liability", "2070", False),
    ("2072", "Short-Term Loans", "liability", "2070", False),
    ("2073", "Current Portion of Long-Term Loans", "liability", "2070", False),

    ("2080", "Other Current Liabilities", "liability", "2000", True),
    ("2081", "Security Deposits Received", "liability", "2080", False),
    ("2082", "Unclaimed Customer Balances", "liability", "2080", False),
    ("2083", "Suspense Receipts", "liability", "2080", False),

    ("2200", "Non-current Liabilities", "liability", None, True),
    ("2210", "Long-Term Bank Loans", "liability", "2200", False),
    ("2220", "Owner or Shareholder Loans", "liability", "2200", False),
    ("2230", "Lease Liabilities", "liability", "2200", False),
    ("2240", "Other Long-Term Liabilities", "liability", "2200", False),

    # ---------------------------------------------------------------- EQUITY
    ("3000", "Equity", "equity", None, True),
    ("3010", "Owner's Capital", "equity", "3000", False),
    ("3020", "Additional Owner Contributions", "equity", "3000", False),
    ("3030", "Owner's Drawings", "equity", "3000", False),
    ("3040", "Retained Earnings", "equity", "3000", False),
    ("3050", "Current-Year Profit or Loss", "equity", "3000", False),
    ("3060", "Prior-Year Adjustments", "equity", "3000", False),
    ("3100", "Opening Balance Equity", "equity", "3000", False),

    # --------------------------------------------------------------- REVENUE
    ("4000", "Revenue", "revenue", None, True),

    ("4010", "Gold Jewellery Sales", "revenue", "4000", True),
    ("4011", "Gold Jewellery Sales — 18K", "revenue", "4010", False),
    ("4012", "Gold Jewellery Sales — 21K", "revenue", "4010", False),
    ("4013", "Gold Jewellery Sales — 24K", "revenue", "4010", False),

    ("4020", "Silver Jewellery Sales", "revenue", "4000", False),
    ("4030", "Diamond Jewellery Sales", "revenue", "4000", False),
    ("4040", "Gemstone Jewellery Sales", "revenue", "4000", False),
    ("4050", "Loose Diamond Sales", "revenue", "4000", False),
    ("4060", "Loose Gemstone Sales", "revenue", "4000", False),

    ("4070", "Custom Order Revenue", "revenue", "4000", True),
    ("4071", "Custom Order Jewellery Revenue", "revenue", "4070", False),
    ("4072", "Custom Order Making Charges", "revenue", "4070", False),
    ("4073", "Custom Order Design Charges", "revenue", "4070", False),
    ("4074", "Custom Order Stone-Setting Revenue", "revenue", "4070", False),

    ("4080", "Repair Revenue", "revenue", "4000", True),
    ("4081", "Jewellery Repair Revenue", "revenue", "4080", False),
    ("4082", "Resizing Revenue", "revenue", "4080", False),
    ("4083", "Stone Replacement Revenue", "revenue", "4080", False),
    ("4084", "Soldering and Restoration Revenue", "revenue", "4080", False),

    ("4090", "Polishing Revenue", "revenue", "4000", False),
    ("4100", "Delivery and Other Service Revenue", "revenue", "4000", False),

    ("4190", "Sales Returns and Allowances", "revenue", "4000", True),
    ("4191", "Gold Sales Returns", "revenue", "4190", False),
    ("4192", "Silver Sales Returns", "revenue", "4190", False),
    ("4193", "Diamond and Gemstone Returns", "revenue", "4190", False),
    ("4194", "Sales Discounts", "revenue", "4190", False),
    ("4195", "Service Discounts", "revenue", "4190", False),

    # ---------------------------------------------------- COST OF GOODS SOLD
    ("5000", "Cost of Goods Sold", "expense", None, True),

    ("5010", "Gold Jewellery Cost of Sales", "expense", "5000", True),
    ("5011", "Cost of Gold Jewellery Sold — 18K", "expense", "5010", False),
    ("5012", "Cost of Gold Jewellery Sold — 21K", "expense", "5010", False),
    ("5013", "Cost of Gold Jewellery Sold — 24K", "expense", "5010", False),

    ("5020", "Cost of Silver Jewellery Sold", "expense", "5000", False),
    ("5030", "Cost of Diamond Jewellery Sold", "expense", "5000", False),
    ("5040", "Cost of Gemstone Jewellery Sold", "expense", "5000", False),
    ("5050", "Cost of Loose Diamonds Sold", "expense", "5000", False),
    ("5060", "Cost of Loose Gemstones Sold", "expense", "5000", False),

    ("5070", "Custom Order Cost of Sales", "expense", "5000", True),
    ("5071", "Custom Order Gold Cost", "expense", "5070", False),
    ("5072", "Custom Order Silver Cost", "expense", "5070", False),
    ("5073", "Custom Order Diamond Cost", "expense", "5070", False),
    ("5074", "Custom Order Gemstone Cost", "expense", "5070", False),
    ("5075", "Custom Order Direct Labour", "expense", "5070", False),
    ("5076", "Custom Order External Workshop Cost", "expense", "5070", False),

    ("5080", "Repair Service Cost", "expense", "5000", True),
    ("5081", "Repair Materials Consumed", "expense", "5080", False),
    ("5082", "Repair Direct Labour", "expense", "5080", False),
    ("5083", "External Repair Workshop Cost", "expense", "5080", False),

    ("5090", "Polishing Service Cost", "expense", "5000", True),
    ("5091", "Polishing Materials Consumed", "expense", "5090", False),
    ("5092", "Polishing Direct Labour", "expense", "5090", False),

    ("5100", "Packaging Cost of Sales", "expense", "5000", False),
    ("5110", "Freight and Import Cost Allocated to Inventory", "expense", "5000", False),
    ("5120", "Inventory Purchase Price Variance", "expense", "5000", False),

    # ---------------------------------------------- SELLING / STORE EXPENSES
    ("6000", "Selling and Store Expenses", "expense", None, True),
    ("6010", "Store Salaries and Wages", "expense", "6000", False),
    ("6020", "Sales Commissions", "expense", "6000", False),
    ("6030", "Store Rent", "expense", "6000", False),
    ("6040", "Store Utilities", "expense", "6000", False),
    ("6050", "Store Maintenance", "expense", "6000", False),
    ("6060", "Security Expenses", "expense", "6000", False),
    ("6070", "Cleaning Expenses", "expense", "6000", False),
    ("6080", "Packaging and Customer Supplies", "expense", "6000", False),
    ("6090", "Advertising and Marketing", "expense", "6000", False),
    ("6100", "Delivery and Courier Expenses", "expense", "6000", False),
    ("6110", "Customer Hospitality", "expense", "6000", False),
    ("6120", "Card Machine Fees", "expense", "6000", False),
    ("6130", "Payment Gateway Fees", "expense", "6000", False),
    ("6140", "Card Chargeback Losses", "expense", "6000", False),
    ("6150", "Branch Communication Expenses", "expense", "6000", False),
    ("6160", "Store Insurance", "expense", "6000", False),
    ("6170", "Display and Decoration Expenses", "expense", "6000", False),
    ("6180", "Jewellery Certification and Testing Fees", "expense", "6000", False),

    ("6200", "Workshop Expenses", "expense", None, True),
    ("6210", "Workshop Salaries", "expense", "6200", False),
    ("6220", "Workshop Consumables", "expense", "6200", False),
    ("6230", "Tool Maintenance", "expense", "6200", False),
    ("6240", "Machine Maintenance", "expense", "6200", False),
    ("6250", "External Craftsmen Fees", "expense", "6200", False),
    ("6260", "Workshop Electricity", "expense", "6200", False),
    ("6270", "Safety Equipment", "expense", "6200", False),
    ("6280", "Design and Modelling Software", "expense", "6200", False),

    ("6300", "General and Administrative Expenses", "expense", None, True),
    ("6310", "Management Salaries", "expense", "6300", False),
    ("6320", "Office Rent", "expense", "6300", False),
    ("6330", "Office Utilities", "expense", "6300", False),
    ("6340", "Telephone and Internet", "expense", "6300", False),
    ("6350", "Software and System Subscriptions", "expense", "6300", False),
    ("6360", "Professional and Consultancy Fees", "expense", "6300", False),
    ("6370", "Legal Fees", "expense", "6300", False),
    ("6380", "Audit and Accounting Fees", "expense", "6300", False),
    ("6390", "Bank Charges", "expense", "6300", False),
    ("6400", "Stationery and Printing", "expense", "6300", False),
    ("6410", "Travel and Transportation", "expense", "6300", False),
    ("6420", "Recruitment and Training", "expense", "6300", False),
    ("6430", "Repairs and Maintenance", "expense", "6300", False),
    ("6440", "Insurance Expense", "expense", "6300", False),
    ("6450", "Depreciation Expense", "expense", "6300", False),
    ("6460", "Bad Debt Expense", "expense", "6300", False),
    ("6470", "Miscellaneous Administrative Expense", "expense", "6300", False),

    ("6500", "Inventory Adjustments", "expense", None, True),
    ("6510", "Inventory Shortage Expense", "expense", "6500", False),
    ("6520", "Inventory Surplus Gain", "expense", "6500", False),
    ("6530", "Gold Weight Loss and Wastage", "expense", "6500", False),
    ("6540", "Silver Weight Loss and Wastage", "expense", "6500", False),
    ("6550", "Diamond and Stone Loss", "expense", "6500", False),
    ("6560", "Damaged Inventory Expense", "expense", "6500", False),
    ("6570", "Obsolete Inventory Expense", "expense", "6500", False),
    ("6580", "Inventory Cost Adjustment", "expense", "6500", False),
    ("6590", "Unexplained Inventory Difference", "expense", "6500", False),

    # ----------------------------------------------- OTHER INCOME / EXPENSES
    ("7000", "Other Income", "revenue", None, True),
    ("7010", "Interest Income", "revenue", "7000", False),
    ("7020", "Foreign Exchange Gain", "revenue", "7000", False),
    ("7030", "Gain on Disposal of Assets", "revenue", "7000", False),
    ("7040", "Scrap Sales Income", "revenue", "7000", False),
    ("7050", "Miscellaneous Income", "revenue", "7000", False),

    ("7500", "Other Expenses", "expense", None, True),
    ("7510", "Interest Expense", "expense", "7500", False),
    ("7520", "Foreign Exchange Loss", "expense", "7500", False),
    ("7530", "Loss on Disposal of Assets", "expense", "7500", False),
    ("7540", "Penalties and Claims", "expense", "7500", False),
    ("7550", "Miscellaneous Expense", "expense", "7500", False),
]


# Old code -> new code. Journal lines are moved before the old account is retired.
REMAP = {
    "1000": "1011",   # Cash               -> Cash on Hand
    "1010": "1021",   # Bank               -> Current Bank Account
    "1100": "1041",   # Accounts Receivable-> Retail Customer Receivables
    "2000": "2017",   # Accounts Payable   -> General Suppliers Payable
    "3000": "3010",   # Owner's Capital    -> Owner's Capital (detail)
    "3200": "3040",   # Retained Earnings  -> Retained Earnings
    "4000": "4012",   # Sales Revenue      -> Gold Jewellery Sales 21K
    "5000": "5012",   # COGS               -> Cost of Gold Jewellery Sold 21K
    "1200": "1222",   # Inventory          -> Finished Gold Jewellery 21K (then split by karat)
    # 3100 Opening Balance Equity keeps its code.
}


def load_chart(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    JournalLine = apps.get_model("accounting", "JournalLine")

    # 1) Move existing postings off codes that are about to become headings.
    #    A temporary code avoids clashing with an account that still exists.
    for old_code, new_code in REMAP.items():
        old = Account.objects.filter(code=old_code).first()
        if old is None:
            continue
        holder, _ = Account.objects.get_or_create(
            code=f"TMP-{new_code}",
            defaults={"name": f"migrating to {new_code}", "type": old.type},
        )
        JournalLine.objects.filter(account=old).update(account=holder)
        old.delete()

    # 2) Create / update every account, parents first so FKs resolve.
    for code, name, type_, parent_code, is_group in CHART:
        parent = Account.objects.filter(code=parent_code).first() if parent_code else None
        Account.objects.update_or_create(
            code=code,
            defaults={"name": name, "type": type_, "parent": parent, "is_group": is_group},
        )

    # 3) Land the parked postings on their new detail accounts.
    for old_code, new_code in REMAP.items():
        holder = Account.objects.filter(code=f"TMP-{new_code}").first()
        if holder is None:
            continue
        target = Account.objects.get(code=new_code)
        JournalLine.objects.filter(account=holder).update(account=target)
        holder.delete()


def unload_chart(apps, schema_editor):
    """Best-effort reverse: drop only accounts that carry no postings."""
    Account = apps.get_model("accounting", "Account")
    for code, _n, _t, _p, _g in reversed(CHART):
        acct = Account.objects.filter(code=code).first()
        if acct and not acct.lines.exists() and not acct.children.exists():
            acct.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0003_account_hierarchy"),
    ]

    operations = [
        migrations.RunPython(load_chart, unload_chart),
    ]
