"""
ShopSense AI — Catalog API Endpoints
Provides HTTP access to catalog search, facet filtering, and product detail retrieval.
"""

from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from app.models.product import Product
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    filter_by_price_and_attributes,
    sort_and_paginate,
    CATEGORY_SYNONYMS,
)

router = APIRouter(prefix="/api/catalog", tags=["Catalog"])

# In-memory cached catalog
_cached_catalog: Optional[List[Product]] = None

def get_catalog() -> List[Product]:
    global _cached_catalog
    if _cached_catalog is None:
        _cached_catalog = load_and_validate_catalog()
    return _cached_catalog


@router.get("/categories")
async def list_categories():
    """Returns canonical categories and their consumer aliases."""
    return {
        "categories": list(CATEGORY_SYNONYMS.keys()),
        "synonym_map": CATEGORY_SYNONYMS
    }


@router.get("/products")
async def search_products(
    category: Optional[str] = Query(default=None, description="Category filter or alias (e.g. shoes, laptops)"),
    keyword: Optional[str] = Query(default=None, description="Search keyword"),
    min_price: Optional[float] = Query(default=None, ge=0.0, description="Minimum price boundary"),
    max_price: Optional[float] = Query(default=None, ge=0.0, description="Maximum price boundary"),
    currency: str = Query(default="INR", description="Target currency for price bounds"),
    size: Optional[str] = Query(default=None, description="Requested size"),
    colour: Optional[str] = Query(default=None, description="Requested color"),
    sort_by: str = Query(default="relevance", description="Sort field: price, rating, review_count, name"),
    ascending: bool = Query(default=False, description="Ascending sort order"),
    page: int = Query(default=1, ge=1, description="Page number"),
    page_size: int = Query(default=10, ge=1, le=50, description="Items per page")
):
    """
    Search and filter catalog products with multi-currency awareness and strict price ceilings.
    """
    products = get_catalog()

    # Step 1: Category & keyword search
    keywords = [keyword] if keyword else None
    matched = search_by_category_and_keywords(
        products,
        category=category,
        keywords=keywords
    )

    # Step 2: Price and attribute filtering
    filtered = filter_by_price_and_attributes(
        matched,
        min_price=min_price,
        max_price=max_price,
        target_currency=currency,
        size=size,
        colour=colour
    )

    # Step 3: Sort and paginate
    return sort_and_paginate(
        filtered,
        sort_by=sort_by,
        ascending=ascending,
        page=page,
        page_size=page_size
    )


@router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str):
    """Retrieves a single product by its unique product_id."""
    products = get_catalog()
    for p in products:
        if p.product_id == product_id:
            return p
    raise HTTPException(status_code=404, detail=f"Product with ID '{product_id}' not found")
