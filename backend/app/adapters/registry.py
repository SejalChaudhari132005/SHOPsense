"""
ShopSense AI — Store Adapter Registry & Unified Search Orchestrator
Coordinates multi-store discovery, parallel async querying, timeouts, and health status reporting.
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field

from app.adapters.base import BaseStoreAdapter, StoreStatus, StoreStatusEnum, StoreSearchResult
from app.adapters.local_catalog_adapter import LocalCatalogAdapter
from app.models.product import Product
from app.core.config import settings


class UnifiedRetrievalResult(BaseModel):
    """
    Consolidated candidate pool retrieved from multiple store adapters.
    """
    products: List[Product] = Field(default_factory=list)
    total_found: int = 0
    sources_consulted: List[str] = Field(default_factory=list)
    store_results: Dict[str, StoreSearchResult] = Field(default_factory=dict)
    store_statuses: List[StoreStatus] = Field(default_factory=list)
    elapsed_total_ms: float = 0.0
    partial_results: bool = False
    timed_out_stores: List[str] = Field(default_factory=list)
    error_stores: List[str] = Field(default_factory=list)


class StoreAdapterRegistry:
    """
    Central registry and coordinator for all retail store adapters.
    """

    def __init__(self):
        self._adapters: Dict[str, BaseStoreAdapter] = {}
        self._register_default_adapters()

    def _register_default_adapters(self):
        """Registers the local mock database as the sole default product source."""
        self.register(LocalCatalogAdapter())

    def register(self, adapter: BaseStoreAdapter):
        """Registers a store adapter."""
        self._adapters[adapter.store_id] = adapter

    def get(self, store_id: str) -> Optional[BaseStoreAdapter]:
        return self._adapters.get(store_id)

    def list_adapters(self) -> List[BaseStoreAdapter]:
        return list(self._adapters.values())

    def get_all_statuses(self) -> List[StoreStatus]:
        """Returns the operational status of all registered adapters."""
        return [adapter.get_status() for adapter in self._adapters.values()]

    async def search_all(
        self,
        query: str,
        category: Optional[str] = None,
        budget_max: Optional[float] = None,
        currency: Optional[str] = "INR",
        limit_per_store: int = 8,
        enabled_stores: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
        **kwargs
    ) -> UnifiedRetrievalResult:
        """
        Executes parallel search across all enabled store adapters with strict timeout protection.
        If one store fails or times out, the other stores continue and return partial results.
        """
        start_overall = time.perf_counter()
        timeout = timeout_seconds if timeout_seconds is not None else settings.STORE_ADAPTER_TIMEOUT_SECONDS
        target_stores = enabled_stores if enabled_stores is not None else settings.ENABLED_STORE_ADAPTERS

        # Filter active adapters
        active_adapters: List[BaseStoreAdapter] = [
            adapter for store_id, adapter in self._adapters.items()
            if store_id in target_stores
        ]

        if not active_adapters:
            # Fall back to local catalog if no stores enabled
            local_ad = self._adapters.get("local_catalog")
            if local_ad:
                active_adapters = [local_ad]

        # Dispatch async searches with timeout
        tasks = [
            self._execute_single_store_search(
                adapter=adapter,
                query=query,
                category=category,
                budget_max=budget_max,
                currency=currency,
                limit=limit_per_store,
                timeout=timeout,
                **kwargs
            )
            for adapter in active_adapters
        ]

        results: List[StoreSearchResult] = await asyncio.gather(*tasks)

        # Consolidate results
        combined_products: List[Product] = []
        sources_consulted: List[str] = []
        store_results_map: Dict[str, StoreSearchResult] = {}
        timed_out_stores: List[str] = []
        error_stores: List[str] = []

        for res in results:
            store_results_map[res.store_id] = res
            sources_consulted.append(res.store_name)

            if res.status == StoreStatusEnum.TIMED_OUT:
                timed_out_stores.append(res.store_name)
            elif res.status in (StoreStatusEnum.ERROR, StoreStatusEnum.RATE_LIMITED):
                error_stores.append(res.store_name)

            combined_products.extend(res.products)

        elapsed_total = (time.perf_counter() - start_overall) * 1000.0
        has_partial = bool(timed_out_stores or error_stores)

        return UnifiedRetrievalResult(
            products=combined_products,
            total_found=len(combined_products),
            sources_consulted=sources_consulted,
            store_results=store_results_map,
            store_statuses=self.get_all_statuses(),
            elapsed_total_ms=round(elapsed_total, 2),
            partial_results=has_partial,
            timed_out_stores=timed_out_stores,
            error_stores=error_stores
        )

    async def _execute_single_store_search(
        self,
        adapter: BaseStoreAdapter,
        query: str,
        category: Optional[str],
        budget_max: Optional[float],
        currency: Optional[str],
        limit: int,
        timeout: float,
        **kwargs
    ) -> StoreSearchResult:
        """Executes a single adapter search safely within a timeout boundary."""
        try:
            return await asyncio.wait_for(
                adapter.search(
                    query=query,
                    category=category,
                    budget_max=budget_max,
                    currency=currency,
                    limit=limit,
                    **kwargs
                ),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            return StoreSearchResult(
                store_id=adapter.store_id,
                store_name=adapter.store_name,
                status=StoreStatusEnum.TIMED_OUT,
                products=[],
                total_found=0,
                latency_ms=round(timeout * 1000.0, 2),
                is_mocked=adapter.is_mocked,
                error_message=f"Store search timed out after {timeout:.1f}s"
            )
        except Exception as e:
            return StoreSearchResult(
                store_id=adapter.store_id,
                store_name=adapter.store_name,
                status=StoreStatusEnum.ERROR,
                products=[],
                total_found=0,
                latency_ms=0.0,
                is_mocked=adapter.is_mocked,
                error_message=f"Store search failed: {str(e)}"
            )

    def search_all_sync(
        self,
        query: str,
        category: Optional[str] = None,
        budget_max: Optional[float] = None,
        currency: Optional[str] = "INR",
        limit_per_store: int = 8,
        enabled_stores: Optional[List[str]] = None,
        timeout_seconds: Optional[float] = None,
        **kwargs
    ) -> UnifiedRetrievalResult:
        """
        Synchronous execution of search_all, safe to call from any context
        (even if another asyncio event loop is already active).
        """
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.search_all(
                        query=query,
                        category=category,
                        budget_max=budget_max,
                        currency=currency,
                        limit_per_store=limit_per_store,
                        enabled_stores=enabled_stores,
                        timeout_seconds=timeout_seconds,
                        **kwargs
                    )
                )
                return future.result()
        else:
            return asyncio.run(
                self.search_all(
                    query=query,
                    category=category,
                    budget_max=budget_max,
                    currency=currency,
                    limit_per_store=limit_per_store,
                    enabled_stores=enabled_stores,
                    timeout_seconds=timeout_seconds,
                    **kwargs
                )
            )


# Global singleton registry
adapter_registry = StoreAdapterRegistry()
