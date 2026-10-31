"""
ShopSense AI — Multi-Store Adapter Base Interface & Types
Defines the common contract for all external e-commerce product sources.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field

from app.models.product import Product, DataSourceType, ProductProvenance


class StoreStatusEnum(str, Enum):
    LIVE_VERIFIED = "live_verified"                 # Official API active with validated credentials
    CONFIGURED_UNVERIFIED = "configured_unverified" # Credentials provided but not yet health-checked
    MOCKED_DEMONSTRATION = "mocked_demonstration"   # Demo mock data for testing (credentials not configured)
    NOT_CONFIGURED = "not_configured"               # Credentials missing and mock fallback disabled
    RATE_LIMITED = "rate_limited"                   # API rate limit or quota exceeded
    TIMED_OUT = "timed_out"                         # Network timeout during search
    ERROR = "error"                                 # Unhandled connection or parsing error


class StoreStatus(BaseModel):
    """
    Truthful status of a retail store adapter.
    """
    store_id: str = Field(..., description="Unique machine identifier (e.g. 'amazon_in')")
    store_name: str = Field(..., description="Human-readable store name (e.g. 'Amazon India')")
    status: StoreStatusEnum = Field(..., description="Current operational status")
    is_configured: bool = Field(..., description="True if required API keys / affiliate IDs are set")
    is_mocked: bool = Field(..., description="True if returning synthetic demonstration data")
    supported_currencies: List[str] = Field(default_factory=lambda: ["INR"])
    rate_limit_per_second: Optional[float] = None
    notes: str = Field(default="", description="Truthful explanation of integration state")
    last_checked_at: datetime = Field(default_factory=datetime.utcnow)


class StoreSearchResult(BaseModel):
    """
    Results returned from an individual store adapter query.
    """
    store_id: str
    store_name: str
    status: StoreStatusEnum
    products: List[Product] = Field(default_factory=list)
    total_found: int = 0
    latency_ms: float = 0.0
    is_mocked: bool = False
    error_message: Optional[str] = None
    rate_limit_remaining: Optional[int] = None


class BaseStoreAdapter(ABC):
    """
    Abstract Base Class for product-source adapters.
    Product sources implement this interface to serve normalized catalog records.
    """

    @property
    @abstractmethod
    def store_id(self) -> str:
        """Unique machine-readable source ID (for example, 'local_catalog')."""
        pass

    @property
    @abstractmethod
    def store_name(self) -> str:
        """Human-readable source name."""
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Returns True if the required credentials/tokens are set in the environment."""
        pass

    @property
    @abstractmethod
    def is_mocked(self) -> bool:
        """Returns True if this adapter runs in mocked demonstration mode."""
        pass

    @abstractmethod
    def get_status(self) -> StoreStatus:
        """Returns current operational status and capabilities."""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        category: Optional[str] = None,
        budget_max: Optional[float] = None,
        currency: Optional[str] = "INR",
        limit: int = 10,
        **kwargs
    ) -> StoreSearchResult:
        """
        Searches the store catalog for candidate products.
        Must normalize all records into the shared Product schema.
        Must respect timeout and error boundaries without throwing unhandled exceptions.
        """
        pass

    @abstractmethod
    async def get_product_details(self, product_id: str) -> Optional[Product]:
        """
        Retrieves detailed information for a single product by ID when supported.
        """
        pass

    @abstractmethod
    def normalize_record(self, raw_record: Dict[str, Any]) -> Optional[Product]:
        """
        Transforms a raw store API payload or JSON dictionary into the shared Product schema.
        Handles missing fields gracefully without fabricating fake data.
        """
        pass
