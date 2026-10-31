"""Currency conversion with INR as the catalog and comparison currency."""

from typing import Dict

# Fixed demo rates expressed directly as INR per currency unit.
EXCHANGE_RATES_TO_INR: Dict[str, float] = {
    "INR": 1.0,
    "USD": 83.3333333333,
    "EUR": 90.0,
    "GBP": 106.6666666667,
    "CAD": 61.6666666667,
    "AUD": 55.0,
    "JPY": 0.5583333333,
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

    if from_curr not in EXCHANGE_RATES_TO_INR:
        raise ValueError(f"Unsupported source currency for conversion: {from_curr}")
    if to_curr not in EXCHANGE_RATES_TO_INR:
        raise ValueError(f"Unsupported target currency for conversion: {to_curr}")

    return EXCHANGE_RATES_TO_INR[from_curr] / EXCHANGE_RATES_TO_INR[to_curr]


def convert_currency(amount: float, from_currency: str, to_currency: str) -> float:
    """
    Converts an amount from one currency to another using the benchmark matrix.
    """
    rate = get_exchange_rate(from_currency, to_currency)
    return round(amount * rate, 2)


def normalize_price_to_inr(amount: float, currency: str) -> float:
    """
    Standardizes a price to INR for ranking and filtering.
    """
    return convert_currency(amount, currency, "INR")


def normalize_price_to_usd(amount: float, currency: str) -> float:
    """Legacy helper retained for callers that explicitly request a USD amount."""
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


def format_price_in_inr(amount: float, currency: str) -> str:
    """Convert a product price to INR for consistent user-facing display."""
    return format_price(convert_currency(amount, currency, "INR"), "INR")


def compare_prices(price_a: float, curr_a: str, price_b: float, curr_b: str) -> int:
    """
    Compares two prices in potentially different currencies.
    Returns:
      -1 if price_a < price_b
       0 if price_a == price_b
       1 if price_a > price_b
    """
    norm_a = normalize_price_to_inr(price_a, curr_a)
    norm_b = normalize_price_to_inr(price_b, curr_b)
    diff = norm_a - norm_b

    if abs(diff) < 0.001:
        return 0
    return -1 if diff < 0 else 1
