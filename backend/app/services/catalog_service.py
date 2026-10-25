"""
ShopSense AI — Catalog Service
Provides loading, schema validation, multi-facet filtering, synonym mapping,
duplicate detection, attribute normalization, and missing-attribute tracking.
"""

import json
import os
import re
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from app.models.product import (
    Product,
    AttributeMatchStatus,
    ProductProvenance,
    AvailabilityStatus
)
from app.services.currency_service import normalize_price_to_usd

# Canonical category synonym mapping
CATEGORY_SYNONYMS: Dict[str, List[str]] = {
    "footwear": ["shoes", "shoe", "sneakers", "boots", "runners", "trainers", "sandals", "slippers", "kicks"],
    "clothing": ["apparel", "clothes", "shirt", "pants", "jacket", "hoodie", "outerwear", "t-shirt", "jeans"],
    "electronics": ["tech", "gadgets", "laptop", "audio", "headphones", "earbuds", "charger", "monitor", "speaker"],
    "travel_accessories": ["travel", "luggage", "travel pillow", "adapter", "passport holder", "packing cubes"],
    "fitness_outdoor": ["fitness", "outdoor", "gym", "workout", "hiking", "camping", "yoga", "exercise", "trail"],
    "home_kitchen": ["kitchen", "home", "cookware", "blender", "coffee maker", "appliances", "utensils"],
    "bags_accessories": ["bag", "backpack", "tote", "duffel", "wallet", "purse", "messenger bag", "daypack"],
}

# Attribute and feature synonyms
FEATURE_SYNONYMS: Dict[str, List[str]] = {
    "lightweight": ["ultralight", "featherweight", "portable", "compact", "easy to carry"],
    "waterproof": ["water-resistant", "weatherproof", "gore-tex", "ipx7", "ipx8", "rainproof", "hydrophobic"],
    "noise_cancelling": ["anc", "active noise cancellation", "sound isolating", "ambient noise reduction"],
    "long_battery": ["extended battery", "all-day battery", "high capacity battery", "long lasting battery"],
    "durable": ["rugged", "heavy duty", "military-grade", "reinforced", "scratch-resistant"],
    "wireless": ["bluetooth", "cordless", "tws", "cable-free"],
    "budget": ["affordable", "cheap", "economy", "low-cost", "value", "entry-level"],
    "breathable": ["ventilated", "cooling", "airmesh", "mesh"],
    "cushioned": ["high cushion", "shock absorbing", "memory foam", "padded"],
    "programming": ["coding", "software development", "developer", "code", "compilation"],
    "running": ["jogging", "marathon", "trail running", "road running", "runner"],
}

# Color normalization table
COLOR_MAP: Dict[str, str] = {
    "black": "black",
    "matte black": "black",
    "midnight black": "black",
    "triple black": "black",
    "black rock": "black",
    "onyx": "black",
    "white": "white",
    "pure white": "white",
    "off-white": "white",
    "chalk white": "white",
    "grey": "grey",
    "gray": "grey",
    "space grey": "grey",
    "silver": "grey",
    "silver mist": "grey",
    "charcoal": "grey",
    "charcoal heather": "grey",
    "blue": "blue",
    "navy": "blue",
    "navy blue": "blue",
    "cobalt blue": "blue",
    "green": "green",
    "forest olive": "green",
    "sage green": "green",
    "neon lime": "green",
    "orange": "orange",
    "flame orange": "orange",
    "red": "red",
    "crimson": "red",
    "coyote tan": "brown",
    "khaki": "brown",
}


def load_and_validate_catalog(file_path: Optional[str] = None) -> List[Product]:
    """
    Loads JSON catalog, applies USD normalized benchmark prices, and validates against Product Pydantic model.
    """
    if file_path is None:
        # Default to root catalog
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        file_path = str(base_dir / "catalog" / "demo_products.json")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Catalog file not found at: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    if not isinstance(raw_data, list):
        raise ValueError("Catalog JSON root must be a list of product objects")

    products: List[Product] = []
    for item in raw_data:
        # Compute normalized price in USD if not present
        if "normalized_price_usd" not in item or item["normalized_price_usd"] is None:
            price = float(item.get("price", 0.0))
            curr = item.get("currency", "USD")
            item["normalized_price_usd"] = normalize_price_to_usd(price, curr)

        product = Product(**item)
        products.append(product)

    return products


def canonicalize_category(query_category: str) -> str:
    """
    Maps user or query category input to canonical catalog category name.
    """
    token = query_category.strip().lower()
    for canonical, syns in CATEGORY_SYNONYMS.items():
        if token == canonical or token in syns:
            return canonical
    return token


def match_synonyms(term: str, context: Optional[str] = None) -> List[str]:
    """
    Returns expanded synonyms for a term or attribute.
    """
    clean_term = term.strip().lower()
    matched: List[str] = [clean_term]

    # Check category synonyms
    for canon, syns in CATEGORY_SYNONYMS.items():
        if clean_term == canon or clean_term in syns:
            matched.extend([canon] + syns)

    # Check feature synonyms
    for canon, syns in FEATURE_SYNONYMS.items():
        if clean_term == canon or clean_term in syns:
            matched.extend([canon] + syns)

    # Return unique terms
    return list(dict.fromkeys(matched))


def normalize_attribute_values(key: str, value: Any) -> Any:
    """
    Normalizes sizes, colors, and numeric units (weights, dimensions).
    """
    if value is None:
        return None

    str_val = str(value).strip()

    # Color normalization
    if key.lower() in ("colour", "color", "colors", "colours"):
        return COLOR_MAP.get(str_val.lower(), str_val.lower())

    # Size normalization (e.g., "US 10.5", "10.5 US", "Size 10" -> "10.5" or standard apparel)
    if key.lower() in ("size", "sizes"):
        # Check if it is purely an apparel size (XS, S, M, L, XL, XXL) with word boundaries
        apparel_map = {
            "extra small": "XS",
            "small": "S",
            "medium": "M",
            "large": "L",
            "extra large": "XL",
            "x-large": "XL",
            "2xl": "XXL",
            "double xl": "XXL"
        }
        lower_str = str_val.lower()
        if lower_str in apparel_map:
            return apparel_map[lower_str]
        if re.search(r"\b(xs|s|m|l|xl|xxl)\b", lower_str) and not re.search(r"\d", str_val):
            return str_val.upper()

        # Shoe / numeric sizes (extract numeric part e.g. "US 10.5" -> "10.5")
        shoe_match = re.search(r"(\d+(\.\d+)?)", str_val)
        if shoe_match:
            return shoe_match.group(1)

        return str_val.upper()

    # Weight normalization (converts grams/pounds to kilograms float)
    if key.lower() in ("weight", "weight_kg"):
        if isinstance(value, (int, float)):
            return float(value)
        # g / grams
        g_match = re.search(r"(\d+(\.\d+)?)\s*(g|grams)", str_val, re.IGNORECASE)
        if g_match:
            return round(float(g_match.group(1)) / 1000.0, 3)
        # lbs / pound
        lb_match = re.search(r"(\d+(\.\d+)?)\s*(lbs?|pounds?)", str_val, re.IGNORECASE)
        if lb_match:
            return round(float(lb_match.group(1)) * 0.453592, 3)
        # kg
        kg_match = re.search(r"(\d+(\.\d+)?)\s*kg", str_val, re.IGNORECASE)
        if kg_match:
            return round(float(kg_match.group(1)), 3)

    return value


def search_by_category_and_keywords(
    products: List[Product],
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    keywords: Optional[List[str]] = None,
    match_all_keywords: bool = False
) -> List[Product]:
    """
    Filters products by category and keyword matches against title, description, tags, and use cases.
    """
    results: List[Product] = []
    canonical_cat = canonicalize_category(category) if category else None

    # Expand keywords with synonyms and singular/plural forms
    expanded_keywords: List[str] = []
    if keywords:
        for kw in keywords:
            clean_kw = kw.strip().lower()
            syns = match_synonyms(clean_kw)
            expanded_keywords.extend(syns)
            if clean_kw.endswith("s") and len(clean_kw) > 3:
                expanded_keywords.extend(match_synonyms(clean_kw[:-1]))
            elif not clean_kw.endswith("s"):
                expanded_keywords.extend(match_synonyms(clean_kw + "s"))
        expanded_keywords = list(dict.fromkeys(expanded_keywords))

    for p in products:
        # Category check
        if canonical_cat:
            prod_cat = canonicalize_category(p.category)
            if prod_cat != canonical_cat:
                continue

        # Subcategory check
        if subcategory:
            if not p.subcategory or subcategory.strip().lower() not in p.subcategory.lower():
                continue

        # Keyword match check
        if expanded_keywords:
            searchable_text = " ".join([
                p.product_name,
                p.description,
                p.brand,
                p.category,
                p.subcategory or "",
                " ".join(p.tags),
                " ".join(p.use_cases),
                " ".join(p.features) if hasattr(p, "features") else "",
                " ".join(f"{k} {v}" for k, v in p.attributes.items()),
                " ".join(f"{k} {v}" for k, v in p.specifications.items())
            ]).lower()

            if match_all_keywords:
                # All primary keywords must have at least one synonym present
                all_matched = True
                for kw in (keywords or []):
                    kw_syns = match_synonyms(kw)
                    if not any(syn in searchable_text for syn in kw_syns):
                        all_matched = False
                        break
                if not all_matched:
                    continue
            else:
                # Any expanded keyword match
                if not any(kw.lower() in searchable_text for kw in expanded_keywords):
                    continue

        results.append(p)

    return results


def filter_by_price_and_attributes(
    products: List[Product],
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    target_currency: str = "USD",
    attribute_filters: Optional[Dict[str, Any]] = None,
    size: Optional[str] = None,
    colour: Optional[str] = None
) -> List[Product]:
    """
    Applies strict price boundaries (using normalized USD comparison) and attribute constraints.
    """
    results: List[Product] = []

    # Convert min/max bounds to USD for consistent comparison
    min_price_usd = normalize_price_to_usd(min_price, target_currency) if min_price is not None else None
    max_price_usd = normalize_price_to_usd(max_price, target_currency) if max_price is not None else None

    # Canonicalize requested size & colour
    norm_size = normalize_attribute_values("size", size) if size else None
    norm_colour = normalize_attribute_values("colour", colour) if colour else None

    for p in products:
        p_price_usd = p.normalized_price_usd or normalize_price_to_usd(p.price, p.currency)

        # Min Price
        if min_price_usd is not None and p_price_usd < min_price_usd:
            continue

        # Strict Max Price Ceiling (Rule #11)
        if max_price_usd is not None and p_price_usd > max_price_usd:
            continue

        # Size matching
        if norm_size:
            if not p.sizes:
                continue
            norm_prod_sizes = [normalize_attribute_values("size", s) for s in p.sizes]
            if norm_size not in norm_prod_sizes:
                continue

        # Colour matching
        if norm_colour:
            if not p.colours:
                continue
            norm_prod_colours = [normalize_attribute_values("colour", c) for c in p.colours]
            if norm_colour not in norm_prod_colours:
                continue

        # Generic attribute filters
        if attribute_filters:
            skip = False
            for attr_key, expected_val in attribute_filters.items():
                actual_val = p.attributes.get(attr_key)
                if actual_val is None:
                    actual_val = p.specifications.get(attr_key)

                if actual_val is None:
                    # Missing attribute is treated as non-match in hard filter
                    skip = True
                    break

                if isinstance(expected_val, bool):
                    if bool(actual_val) != expected_val:
                        skip = True
                        break
                elif isinstance(actual_val, list):
                    if expected_val not in actual_val:
                        skip = True
                        break
                elif str(actual_val).lower() != str(expected_val).lower():
                    skip = True
                    break

            if skip:
                continue

        results.append(p)

    return results


def identify_duplicate_products(
    products: List[Product], 
    similarity_threshold: float = 0.85
) -> List[Tuple[Product, Product, float]]:
    """
    Identifies duplicate or identical products across merchants/sources
    using Jaccard word similarity on product names and brand alignment.
    """
    duplicates: List[Tuple[Product, Product, float]] = []

    for i in range(len(products)):
        for j in range(i + 1, len(products)):
            p1 = products[i]
            p2 = products[j]

            # Direct match by source_product_id if available
            if p1.source_product_id and p2.source_product_id and p1.source_product_id == p2.source_product_id:
                duplicates.append((p1, p2, 1.0))
                continue

            # Brand must match or both belong to same category
            if p1.brand.lower() != p2.brand.lower():
                continue

            # Jaccard word similarity on title
            words1 = set(re.findall(r"\w+", p1.product_name.lower()))
            words2 = set(re.findall(r"\w+", p2.product_name.lower()))
            if not words1 or not words2:
                continue

            intersection = len(words1.intersection(words2))
            union = len(words1.union(words2))
            sim = intersection / union

            if sim >= similarity_threshold:
                duplicates.append((p1, p2, round(sim, 2)))

    return duplicates


def handle_missing_attributes(
    product: Product, 
    requested_attributes: List[str]
) -> Dict[str, AttributeMatchStatus]:
    """
    Evaluates requested attributes against a product.
    Accurately classifies into MATCH, MISMATCH, or UNKNOWN (Rule #10).
    """
    statuses: Dict[str, AttributeMatchStatus] = {}

    for attr in requested_attributes:
        clean_attr = attr.strip().lower()

        # Check top-level optional fields first
        if clean_attr in ("size", "sizes"):
            if product.sizes is None:
                statuses[attr] = AttributeMatchStatus.UNKNOWN
            else:
                statuses[attr] = AttributeMatchStatus.MATCH if product.sizes else AttributeMatchStatus.UNKNOWN
            continue

        if clean_attr in ("color", "colour", "colours", "colors"):
            if product.colours is None:
                statuses[attr] = AttributeMatchStatus.UNKNOWN
            else:
                statuses[attr] = AttributeMatchStatus.MATCH if product.colours else AttributeMatchStatus.UNKNOWN
            continue

        if clean_attr in ("rating", "reviews"):
            if product.rating is None:
                statuses[attr] = AttributeMatchStatus.UNKNOWN
            else:
                statuses[attr] = AttributeMatchStatus.MATCH
            continue

        # Check specifications & attributes
        found = False
        for collection in (product.specifications, product.attributes):
            for k, v in collection.items():
                if k.lower() == clean_attr or clean_attr in match_synonyms(k):
                    found = True
                    if v is None:
                        statuses[attr] = AttributeMatchStatus.UNKNOWN
                    else:
                        statuses[attr] = AttributeMatchStatus.MATCH
                    break
            if found:
                break

        if not found:
            # Attribute is completely unmentioned/unknown
            statuses[attr] = AttributeMatchStatus.UNKNOWN

    return statuses


def get_source_metadata(product: Product) -> ProductProvenance:
    """
    Returns the provenance and audit metadata for a given product.
    """
    return product.provenance


def sort_and_paginate(
    products: List[Product],
    sort_by: str = "relevance",
    ascending: bool = False,
    page: int = 1,
    page_size: int = 10
) -> Dict[str, Any]:
    """
    Sorts product list and returns paginated result metadata.
    """
    sorted_items = list(products)

    if sort_by == "price":
        sorted_items.sort(
            key=lambda p: p.normalized_price_usd or normalize_price_to_usd(p.price, p.currency),
            reverse=not ascending
        )
    elif sort_by == "rating":
        sorted_items.sort(
            key=lambda p: p.rating if p.rating is not None else -1.0,
            reverse=not ascending
        )
    elif sort_by == "review_count":
        sorted_items.sort(
            key=lambda p: p.review_count if p.review_count is not None else -1,
            reverse=not ascending
        )
    elif sort_by == "name":
        sorted_items.sort(key=lambda p: p.product_name.lower(), reverse=not ascending)

    total_count = len(sorted_items)
    total_pages = max(1, (total_count + page_size - 1) // page_size)
    current_page = max(1, min(page, total_pages))

    start_idx = (current_page - 1) * page_size
    end_idx = start_idx + page_size
    page_items = sorted_items[start_idx:end_idx]

    return {
        "items": page_items,
        "total_count": total_count,
        "page": current_page,
        "page_size": page_size,
        "total_pages": total_pages
    }
