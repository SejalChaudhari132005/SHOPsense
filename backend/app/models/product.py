"""
ShopSense AI — Normalized Product Schema
Defines Pydantic models for product data, attributes, provenance, and multi-currency support.
"""

from enum import Enum
from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator


class AvailabilityStatus(str, Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    PREORDER = "preorder"
    UNKNOWN = "unknown"


class DataSourceType(str, Enum):
    LOCAL_DEMO = "local_demo"
    VERIFIED_PARTNER = "verified_partner"
    EXTENSION_SCRAPED = "extension_scraped"
    MANUAL_SEED = "manual_seed"
    UNKNOWN = "unknown"


class AttributeMatchStatus(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class ShippingInfo(BaseModel):
    free_shipping: bool = False
    estimated_days: Optional[int] = Field(default=None, ge=0)
    shipping_cost: Optional[float] = Field(default=None, ge=0.0)
    currency: Optional[str] = "USD"
    carrier: Optional[str] = None


class ProductProvenance(BaseModel):
    is_sample_data: bool = True
    data_source_type: DataSourceType = DataSourceType.LOCAL_DEMO
    verified: bool = False
    confidence_score: float = Field(default=1.0, ge=0.0, le=1.0)
    missing_fields: List[str] = Field(default_factory=list)
    notes: Optional[str] = "Demonstration product for local testing"


class Product(BaseModel):
    """
    Normalized Product representation used by all agents, filters, and shopping sources.
    """
    product_id: str = Field(..., description="Unique product identifier (e.g. prod_foot_001)")
    product_name: str = Field(..., description="Full human-readable product title")
    brand: str = Field(..., description="Brand or manufacturer")
    category: str = Field(..., description="Top-level product category")
    subcategory: Optional[str] = Field(default=None, description="Granular product subcategory")
    description: str = Field(..., description="Product summary and highlights")

    # Financial & Currency Handling
    price: float = Field(..., gt=0.0, description="Product listing price in native currency")
    currency: str = Field(default="USD", description="ISO 4217 currency code (USD, INR, EUR, GBP)")
    normalized_price_usd: Optional[float] = Field(
        default=None, 
        gt=0.0, 
        description="Calculated benchmark price in USD for standardized comparison"
    )

    # Online Links & Store Attribution
    product_url: Optional[str] = Field(default=None, description="Product page URL")
    image_url: Optional[str] = Field(default=None, description="Product image URL")
    source_store: str = Field(default="DemoStore", description="Primary retail merchant or source name")
    source_product_id: Optional[str] = Field(default=None, description="Merchant-specific SKU or ASIN")

    # Structured Facets
    attributes: Dict[str, Any] = Field(default_factory=dict, description="Generic key-value attribute facets")
    use_cases: List[str] = Field(default_factory=list, description="Target use cases, activities, or personas")
    tags: List[str] = Field(default_factory=list, description="Search and synonym tags")
    sizes: Optional[List[str]] = Field(default=None, description="Available sizes if applicable")
    colours: Optional[List[str]] = Field(default=None, description="Available color options if applicable")
    specifications: Dict[str, Any] = Field(default_factory=dict, description="Technical specifications")

    # Availability & Social Proof
    availability: AvailabilityStatus = Field(
        default=AvailabilityStatus.IN_STOCK, 
        description="Current stock availability"
    )
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0, description="Customer rating from 0.0 to 5.0")
    review_count: Optional[int] = Field(default=None, ge=0, description="Total verified customer review count")
    shipping_information: Optional[ShippingInfo] = Field(default=None, description="Shipping estimates and costs")

    # Provenance & Audit
    last_verified_at: Optional[datetime] = Field(default=None, description="Timestamp when price and stock were last validated")
    data_source_type: DataSourceType = Field(
        default=DataSourceType.LOCAL_DEMO, 
        description="Origin source type"
    )
    provenance: ProductProvenance = Field(
        default_factory=ProductProvenance, 
        description="Data provenance and uncertainty metadata"
    )

    @field_validator("product_name", "brand", "category")
    @classmethod
    def check_non_empty_strings(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return v.strip()

    @field_validator("currency")
    @classmethod
    def uppercase_currency(cls, v: str) -> str:
        return v.strip().upper()

    @model_validator(mode="after")
    def set_provenance_and_missing(self) -> "Product":
        # Keep data_source_type in sync with provenance
        if self.data_source_type != self.provenance.data_source_type:
            self.provenance.data_source_type = self.data_source_type

        # Track missing optional fields for honest uncertainty handling (Rule #10)
        missing = []
        if self.sizes is None:
            missing.append("sizes")
        if self.colours is None:
            missing.append("colours")
        if self.rating is None:
            missing.append("rating")
        if self.review_count is None:
            missing.append("review_count")
        if self.shipping_information is None:
            missing.append("shipping_information")
        if not self.specifications:
            missing.append("specifications")

        self.provenance.missing_fields = missing
        return self
