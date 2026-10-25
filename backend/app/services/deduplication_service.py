"""
ShopSense AI — Multi-Store Deduplication & Cross-Store Price Comparison Service
Identifies identical or equivalent products across multiple retail merchants,
groups cross-store offers, computes price deltas, and preserves store-specific links.
"""

import re
from typing import Dict, List, Optional, Any, Tuple
from pydantic import BaseModel, Field

from app.models.product import Product
from app.services.currency_service import normalize_price_to_usd, format_price


class CrossStoreOffer(BaseModel):
    """
    An individual merchant offer for a product available across multiple stores.
    """
    store_name: str
    product_id: str
    price: float
    currency: str
    normalized_price_usd: float
    product_url: Optional[str] = None
    availability: str = "in_stock"
    is_mocked: bool = False
    is_lowest_price: bool = False


class DeduplicatedProductGroup(BaseModel):
    """
    Unified product candidate with cross-store merchant offers and price comparisons.
    """
    primary_product: Product
    cross_store_offers: List[CrossStoreOffer] = Field(default_factory=list)
    has_multiple_stores: bool = False
    lowest_price_usd: float
    highest_price_usd: float
    max_savings_usd: float = 0.0
    best_store_name: str
    comparison_summary: Optional[str] = None


def extract_product_canonical_key(product: Product) -> str:
    """
    Extracts a canonical key for cross-store duplicate detection.
    Combines normalized brand and core model identifier (e.g. 'sony_wh1000xm5', 'apple_airpods_max').
    """
    brand = (product.brand or "").strip().lower()

    # Check specifications or attributes for model name
    model = ""
    for k in ("Model Name", "model_name", "model", "Model"):
        if k in product.specifications:
            model = str(product.specifications[k]).strip().lower()
            break
        elif k in product.attributes:
            model = str(product.attributes[k]).strip().lower()
            break

    # If no explicit model, extract from title
    title_clean = re.sub(r"[^\w\s-]", " ", product.product_name.lower())
    title_clean = re.sub(r"\s+", " ", title_clean).strip()

    # Remove brand from title
    if brand:
        title_clean = title_clean.replace(brand, "").strip()

    # Look for known model patterns (alphanumeric codes like wh-1000xm5, qc45, m2, etc.)
    model_match = re.search(r"\b([a-z0-9]+-[a-z0-9]+|[a-z]{1,4}\d{2,5}[a-z]{0,3})\b", title_clean)
    if model_match:
        model = model_match.group(1).replace("-", "")

    if not model:
        # Fall back to top 3 significant words
        words = [w for w in title_clean.split() if len(w) > 3 and w not in (
            "wireless", "bluetooth", "headset", "headphones", "cancelling", "laptop", "shoes", "running"
        )]
        model = "_".join(words[:2]) if words else title_clean[:20]

    return f"{brand}_{model}".strip("_")


def deduplicate_cross_store_candidates(products: List[Product]) -> List[Product]:
    """
    Deduplicates products across stores while enriching the primary candidate
    with a cross-store price comparison and store-specific links.
    """
    if not products:
        return []

    groups: Dict[str, List[Product]] = {}

    for prod in products:
        # Ensure benchmark USD price is computed
        if prod.normalized_price_usd is None or prod.normalized_price_usd <= 0:
            prod.normalized_price_usd = normalize_price_to_usd(prod.price, prod.currency)

        key = extract_product_canonical_key(prod)
        if key not in groups:
            groups[key] = []
        groups[key].append(prod)

    deduped_products: List[Product] = []

    for key, group in groups.items():
        if len(group) == 1:
            # Single store listing
            deduped_products.append(group[0])
            continue

        # Sort group by normalized USD price ascending (lowest price first)
        sorted_group = sorted(group, key=lambda p: p.normalized_price_usd or float("inf"))
        primary = sorted_group[0]  # Lowest price is the primary offer

        offers: List[CrossStoreOffer] = []
        lowest_usd = primary.normalized_price_usd or 0.0
        highest_usd = sorted_group[-1].normalized_price_usd or 0.0
        savings_usd = round(highest_usd - lowest_usd, 2)

        for idx, item in enumerate(sorted_group):
            is_mock = item.provenance.is_sample_data if item.provenance else False
            offers.append(CrossStoreOffer(
                store_name=item.source_store,
                product_id=item.product_id,
                price=item.price,
                currency=item.currency,
                normalized_price_usd=item.normalized_price_usd or 0.0,
                product_url=item.product_url,
                availability=item.availability.value if hasattr(item.availability, "value") else str(item.availability),
                is_mocked=is_mock,
                is_lowest_price=(idx == 0)
            ))

        # Store cross-store offers in primary product attributes
        primary.attributes["cross_store_offers"] = [offer.model_dump() for offer in offers]
        primary.attributes["has_cross_store_comparison"] = True
        primary.attributes["best_store_name"] = primary.source_store

        if savings_usd > 1.0:
            summary = (
                f"Available on {len(offers)} stores. Lowest price at {primary.source_store} "
                f"({format_price(primary.price, primary.currency)}), saving "
                f"~${savings_usd:.2f} USD compared to {sorted_group[-1].source_store}."
            )
            primary.attributes["cross_store_savings_summary"] = summary

        deduped_products.append(primary)

    return deduped_products
