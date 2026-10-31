"""Services for catalog operations, currency conversion, and search"""

from app.services.currency_service import (
    get_exchange_rate,
    convert_currency,
    normalize_price_to_inr,
    normalize_price_to_usd,
    format_price,
    compare_prices,
    EXCHANGE_RATES_TO_INR,
)
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    filter_by_price_and_attributes,
    match_synonyms,
    normalize_attribute_values,
    identify_duplicate_products,
    handle_missing_attributes,
    get_source_metadata,
    sort_and_paginate,
    canonicalize_category,
)

__all__ = [
    "get_exchange_rate",
    "convert_currency",
    "normalize_price_to_inr",
    "normalize_price_to_usd",
    "format_price",
    "compare_prices",
    "EXCHANGE_RATES_TO_INR",
    "load_and_validate_catalog",
    "search_by_category_and_keywords",
    "filter_by_price_and_attributes",
    "match_synonyms",
    "normalize_attribute_values",
    "identify_duplicate_products",
    "handle_missing_attributes",
    "get_source_metadata",
    "sort_and_paginate",
    "canonicalize_category",
]
