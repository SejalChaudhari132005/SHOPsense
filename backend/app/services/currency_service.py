"""
ShopSense AI — Multi-Currency Service
Handles exchange rates, normalization to USD benchmark, and cross-currency comparisons.
Guarantees that different currencies (e.g. USD vs INR) are never compared 1:1.
"""

from typing import Dict

# Exchange rates relative to 1.0 USD benchmark
EXCHANGE_RATES_TO_USD: Dict[str, float] = {
    "USD": 1.0,
    "INR": 0.012,    # ~83.33 INR per USD
    "EUR": 1.08,     # ~0.925 EUR per USD
    "GBP": 1.28,     # ~0.781 GBP per USD
    "CAD": 0.74,     # ~1.35 CAD per USD
    "AUD": 0.66,     # ~1.51 AUD per USD
    "JPY": 0.0067,   # ~149 JPY per USD
}

CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$",
    "INR": "₹",
    "EUR": "€",
    "GBP": "£",
    "CAD": "CA$",
    "AUD": "A$",
    "JPY": "¥",
}


def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """
    Returns the conversion multiplier from from_currency to to_currency.
    """
    from_curr = from_currency.strip().upper()
    to_curr = to_currency.strip().upper()

    if from_curr == to_curr:
        return 1.0

    if from_curr not in EXCHANGE_RATES_TO_USD:
        raise ValueError(f"Unsupported source currency for conversion: {from_curr}")
    if to_curr not in EXCHANGE_RATES_TO_USD:
        raise ValueError(f"Unsupported target currency for conversion: {to_curr}")

    # Convert from -> USD -> to
    usd_val = EXCHANGE_RATES_TO_USD[from_curr]
    to_rate = EXCHANGE_RATES_TO_USD[to_curr]
    return usd_val / to_rate


def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    """
    Converts an amount from one currency to another using the benchmark matrix.
    """
    rate = get_exchange_rate(from_currency, to_currency)
    return round(amount * rate, 2)


def normalize_price_to_usd(amount: float, currency: str) -> float:
    """
    Standardizes a price to USD for normalized ranking and filtering.
    """
    return convert_currency(amount, currency, "USD")


def format_price(amount: float, currency: str) -> str:
    """
    Formats a numeric price with its localized currency symbol.
    """
    curr = currency.strip().upper()
    symbol = CURRENCY_SYMBOLS.get(curr, f"{curr} ")
    if curr == "INR":
        # Indian numbering format grouping
        return f"{symbol}{amount:,.2f}"
    return f"{symbol}{amount:,.2f}"


def compare_prices(price_a: float, curr_a: str, price_b: float, curr_b: str) -> int:
    """
    Compares two prices in potentially different currencies.
    Returns:
      -1 if price_a < price_b
       0 if price_a == price_b
       1 if price_a > price_b
    """
    norm_a = normalize_price_to_usd(price_a, curr_a)
    norm_b = normalize_price_to_usd(price_b, curr_b)
    diff = norm_a - norm_b

    if abs(diff) < 0.001:
        return 0
    return -1 if diff < 0 else 1
