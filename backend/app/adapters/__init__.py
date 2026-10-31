"""
ShopSense AI — Multi-Store Adapter Architecture Package
"""

from app.adapters.base import (
    BaseStoreAdapter,
    StoreStatus,
    StoreStatusEnum,
    StoreSearchResult,
)
from app.adapters.local_catalog_adapter import LocalCatalogAdapter
from app.adapters.registry import (
    StoreAdapterRegistry,
    UnifiedRetrievalResult,
    adapter_registry,
)

__all__ = [
    "BaseStoreAdapter",
    "StoreStatus",
    "StoreStatusEnum",
    "StoreSearchResult",
    "LocalCatalogAdapter",
    "StoreAdapterRegistry",
    "UnifiedRetrievalResult",
    "adapter_registry",
]
