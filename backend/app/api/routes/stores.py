"""
ShopSense AI — Store Status & Multi-Store Discovery Endpoint
Exposes GET /api/stores/status and POST /api/stores/search for multi-store visibility.
"""

from typing import List, Optional
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.adapters.registry import adapter_registry
from app.adapters.base import StoreStatus
from app.models.product import Product

router = APIRouter(prefix="/api/stores", tags=["Stores"])


class StoreStatusResponse(BaseModel):
    stores: List[StoreStatus]
    total_stores: int
    live_verified_count: int
    configured_unverified_count: int
    mocked_demo_count: int
    not_configured_count: int


class MultiStoreSearchRequest(BaseModel):
    query: str
    category: Optional[str] = None
    budget_max: Optional[float] = None
    currency: Optional[str] = "USD"
    limit_per_store: int = Field(default=8, ge=1, le=50)
    enabled_stores: Optional[List[str]] = None


class MultiStoreSearchResponse(BaseModel):
    products: List[Product]
    total_found: int
    sources_consulted: List[str]
    store_statuses: List[StoreStatus]
    elapsed_total_ms: float
    partial_results: bool
    timed_out_stores: List[str]
    error_stores: List[str]


@router.get("/status", response_model=StoreStatusResponse)
async def get_store_statuses():
    """
    Returns a truthful integration status table distinguishing:
    - Live and verified
    - Configured but not verified
    - Mocked demonstration
    - Not yet accessible
    """
    statuses = adapter_registry.get_all_statuses()
    live_count = sum(1 for s in statuses if s.status.value == "live_verified")
    conf_unverified = sum(1 for s in statuses if s.status.value == "configured_unverified")
    mock_count = sum(1 for s in statuses if s.status.value == "mocked_demonstration")
    not_conf = sum(1 for s in statuses if s.status.value == "not_configured")

    return StoreStatusResponse(
        stores=statuses,
        total_stores=len(statuses),
        live_verified_count=live_count,
        configured_unverified_count=conf_unverified,
        mocked_demo_count=mock_count,
        not_configured_count=not_conf
    )


@router.post("/search", response_model=MultiStoreSearchResponse)
async def search_multi_store(request: MultiStoreSearchRequest):
    """
    Dispatches a parallel multi-store search across all configured retail adapters.
    """
    result = await adapter_registry.search_all(
        query=request.query,
        category=request.category,
        budget_max=request.budget_max,
        currency=request.currency,
        limit_per_store=request.limit_per_store,
        enabled_stores=request.enabled_stores
    )

    return MultiStoreSearchResponse(
        products=result.products,
        total_found=result.total_found,
        sources_consulted=result.sources_consulted,
        store_statuses=result.store_statuses,
        elapsed_total_ms=result.elapsed_total_ms,
        partial_results=result.partial_results,
        timed_out_stores=result.timed_out_stores,
        error_stores=result.error_stores
    )
