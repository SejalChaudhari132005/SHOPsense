"""
ShopSense AI — Local Catalog Store Adapter
Provides fast, zero-latency access to verified local baseline products across all categories.
"""

import time
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.adapters.base import BaseStoreAdapter, StoreStatus, StoreStatusEnum, StoreSearchResult
from app.models.product import Product, DataSourceType, ProductProvenance, AvailabilityStatus
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    canonicalize_category,
)
from app.services.currency_service import normalize_price_to_usd


class LocalCatalogAdapter(BaseStoreAdapter):
    """
    Adapter for the verified local catalog.
    Always available, zero network latency, verified schema models.
    """

    def __init__(self, catalog_path: Optional[str] = None):
        self._catalog_path = catalog_path
        self._products: Optional[List[Product]] = None

    @property
    def store_id(self) -> str:
        return "local_catalog"

    @property
    def store_name(self) -> str:
        return "Local Catalog"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def is_mocked(self) -> bool:
        return False

    def _get_catalog(self) -> List[Product]:
        if self._products is None:
            self._products = load_and_validate_catalog(self._catalog_path)
        return self._products

    def get_status(self) -> StoreStatus:
        return StoreStatus(
            store_id=self.store_id,
            store_name=self.store_name,
            status=StoreStatusEnum.LIVE_VERIFIED,
            is_configured=True,
            is_mocked=False,
            supported_currencies=["USD"],
            rate_limit_per_second=None,
            notes="Verified local catalog with guaranteed multi-facet schemas and benchmark prices",
            last_checked_at=datetime.utcnow()
        )

    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        budget_max: Optional[float] = None,
        currency: Optional[str] = "USD",
        limit: int = 10,
        **kwargs
    ) -> StoreSearchResult:
        start_time = time.perf_counter()
        products = self._get_catalog()

        # Parse keywords from query
        clean_q = (query or "").strip().lower()
        keywords = [k for k in clean_q.split() if len(k) > 2] if clean_q else []

        canonical_cat = canonicalize_category(category) if category else None

        # Execute multi-facet search
        candidates = search_by_category_and_keywords(
            products,
            category=canonical_cat,
            keywords=keywords if keywords else None,
            match_all_keywords=False
        )

        # If strict search by category yielded 0, fall back to broad keyword match across all categories
        if not candidates and keywords:
            candidates = search_by_category_and_keywords(
                products,
                category=None,
                keywords=keywords,
                match_all_keywords=False
            )

        # Normalize benchmark USD prices
        for p in candidates:
            if p.normalized_price_usd is None or p.normalized_price_usd <= 0:
                p.normalized_price_usd = normalize_price_to_usd(p.price, p.currency)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return StoreSearchResult(
            store_id=self.store_id,
            store_name=self.store_name,
            status=StoreStatusEnum.LIVE_VERIFIED,
            products=candidates[:limit],
            total_found=len(candidates),
            latency_ms=round(elapsed_ms, 2),
            is_mocked=False
        )

    async def get_product_details(self, product_id: str) -> Optional[Product]:
        products = self._get_catalog()
        for p in products:
            if p.product_id == product_id or p.source_product_id == product_id:
                return p
        return None

    def normalize_record(self, raw_record: Dict[str, Any]) -> Optional[Product]:
        try:
            return Product(**raw_record)
        except Exception:
            return None
