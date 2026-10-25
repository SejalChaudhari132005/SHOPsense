"""
ShopSense AI — Search Endpoint
POST /api/search
Provides faceted multi-currency catalog search.
"""

from fastapi import APIRouter
from app.models.api_schemas import SearchRequest, SearchResponse
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    filter_by_price_and_attributes,
    sort_and_paginate
)

router = APIRouter(prefix="/api/search", tags=["Search"])


@router.post("/", response_model=SearchResponse)
async def search_catalog(request: SearchRequest):
    """
    Search and filter products across the catalog with multi-currency awareness.
    """
    products = load_and_validate_catalog()

    # Step 1: Category & keyword filtering
    keywords = [request.query] if request.query else None
    matched = search_by_category_and_keywords(
        products,
        category=request.category,
        keywords=keywords
    )

    # Step 2: Price and physical attribute filtering
    filtered = filter_by_price_and_attributes(
        matched,
        min_price=request.min_price,
        max_price=request.max_price,
        target_currency=request.currency,
        size=request.size,
        colour=request.colour
    )

    # Step 3: Sort and paginate
    result = sort_and_paginate(
        filtered,
        sort_by=request.sort_by,
        ascending=request.ascending,
        page=request.page,
        page_size=request.page_size
    )

    return SearchResponse(**result)
