"""
ShopSense AI — Local Catalog Store Adapter
Provides fast, zero-latency access to local demonstration products across all categories.
"""

import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from pathlib import Path

from app.adapters.base import BaseStoreAdapter, StoreStatus, StoreStatusEnum, StoreSearchResult
from app.models.product import Product, DataSourceType, ProductProvenance, AvailabilityStatus
from app.core.config import settings
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    canonicalize_category,
)


class LocalCatalogAdapter(BaseStoreAdapter):
    """
    Adapter for the local demo catalog.
    Always available with zero network latency and validated product schemas.
    """

    def __init__(self, catalog_path: Optional[str] = None):
        self._catalog_path = catalog_path
        self._products: Optional[List[Product]] = None
        self._catalog_signature = None

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
        return True

    def _get_catalog(self) -> List[Product]:
        catalog_path = Path(self._catalog_path or settings.CATALOG_PATH)
        try:
            stat = catalog_path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        if self._products is None or signature != self._catalog_signature:
            self._products = load_and_validate_catalog(self._catalog_path)
            self._catalog_signature = signature
        return self._products

    def get_status(self) -> StoreStatus:
        return StoreStatus(
            store_id=self.store_id,
            store_name=self.store_name,
            status=StoreStatusEnum.MOCKED_DEMONSTRATION,
            is_configured=True,
            is_mocked=True,
            supported_currencies=["INR"],
            rate_limit_per_second=None,
            notes="Static demo catalog; product prices and availability are not live-verified",
            last_checked_at=datetime.utcnow()
        )

    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        budget_max: Optional[float] = None,
        currency: Optional[str] = "INR",
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

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        return StoreSearchResult(
            store_id=self.store_id,
            store_name=self.store_name,
            status=StoreStatusEnum.MOCKED_DEMONSTRATION,
            products=candidates[:limit],
            total_found=len(candidates),
            latency_ms=round(elapsed_ms, 2),
            is_mocked=True
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
