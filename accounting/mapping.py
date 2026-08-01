"""Which ledger account each kind of transaction posts to.

Keeping the codes here means the rest of the app never hard-codes an account
number — when the chart of accounts changes, this is the only file to edit.
"""

# --- money ---------------------------------------------------------------
CASH = "1011"                    # Cash on Hand
BANK = "1021"                    # Current Bank Account
CARD_RECEIVABLE = "1031"         # POS Card Receivables (awaiting settlement)

# --- customers and suppliers --------------------------------------------
RETAIL_RECEIVABLE = "1041"       # Retail Customer Receivables
SUPPLIER_PAYABLE = "2011"        # Gold Suppliers Payable

# --- equity --------------------------------------------------------------
OWNERS_CAPITAL = "3010"
OPENING_BALANCE_EQUITY = "3100"

# --- revenue deductions --------------------------------------------------
SALES_DISCOUNTS = "4194"

# --- gold, keyed by karat ------------------------------------------------
# Silver, diamond and gemstone accounts exist in the chart but stay unused
# until the item record carries a material field.
_GOLD_INVENTORY = {18: "1221", 21: "1222", 24: "1223"}
_GOLD_REVENUE = {18: "4011", 21: "4012", 24: "4013"}
_GOLD_COGS = {18: "5011", 21: "5012", 24: "5013"}

_DEFAULT_KARAT = 21


def gold_inventory(karat):
    """Finished Gold Jewellery account for this karat."""
    return _GOLD_INVENTORY.get(int(karat), _GOLD_INVENTORY[_DEFAULT_KARAT])


def gold_revenue(karat):
    """Gold Jewellery Sales account for this karat."""
    return _GOLD_REVENUE.get(int(karat), _GOLD_REVENUE[_DEFAULT_KARAT])


def gold_cogs(karat):
    """Cost of Gold Jewellery Sold account for this karat."""
    return _GOLD_COGS.get(int(karat), _GOLD_COGS[_DEFAULT_KARAT])
