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
from app.adapters.amazon_adapter import AmazonIndiaAdapter
from app.adapters.flipkart_adapter import FlipkartAdapter
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
    "AmazonIndiaAdapter",
    "FlipkartAdapter",
    "StoreAdapterRegistry",
    "UnifiedRetrievalResult",
    "adapter_registry",
]
