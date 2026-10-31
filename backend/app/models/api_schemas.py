"""
ShopSense AI — FastAPI Request & Response Schemas
Type-safe Pydantic models for Search, Compare, Why-Not, Refine, and Consented Preferences.
"""

from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

from app.models.product import Product
from app.models.state import ProductFitScore, ProductRecommendation, OrchestratorResponse


# ==========================================
# 1. Search Request & Response
# ==========================================

class SearchRequest(BaseModel):
    query: Optional[str] = Field(default=None, description="Keywords to match against title/tags/use cases")
    category: Optional[str] = Field(default=None, description="Category filter or synonym (e.g. shoes, laptop)")
    min_price: Optional[float] = Field(default=None, ge=0.0, description="Minimum price boundary")
    max_price: Optional[float] = Field(default=None, ge=0.0, description="Maximum price boundary")
    currency: str = Field(default="INR", description="Currency code for price bounds")
    size: Optional[str] = Field(default=None, description="Size filter")
    colour: Optional[str] = Field(default=None, description="Color filter")
    sort_by: str = Field(default="relevance", description="Sorting field: price, rating, review_count, name")
    ascending: bool = Field(default=False, description="Sort direction")
    page: int = Field(default=1, ge=1, description="Page number")
    page_size: int = Field(default=10, ge=1, le=50, description="Number of results per page")


class SearchResponse(BaseModel):
    items: List[Product]
    total_count: int
    page: int
    page_size: int
    total_pages: int


# ==========================================
# 2. Product Comparison Models
# ==========================================

class CompareRequest(BaseModel):
    product_ids: List[str] = Field(
        ..., 
        min_length=2, 
        max_length=4, 
        description="2 to 4 unique product IDs to compare side-by-side"
    )
    session_id: Optional[str] = Field(default=None, description="Optional session ID to incorporate user criteria")


class ProductComparisonItem(BaseModel):
    product_id: str
    product_name: str
    brand: str
    category: str
    price: float
    currency: str
    normalized_price_usd: float = Field(
        ..., exclude=True, description="Internal-only comparison benchmark"
    )
    rating: Optional[float] = None
    review_count: Optional[int] = None
    highlights: List[str] = Field(default_factory=list)
    key_specs: Dict[str, Any] = Field(default_factory=dict)
    fit_score: Optional[float] = None
    hard_constraint_satisfaction: Dict[str, bool] = Field(default_factory=dict)
    soft_preference_matches: List[str] = Field(default_factory=list)
    fit_score_breakdown: Optional[Dict[str, float]] = None
    unknown_attributes: List[str] = Field(default_factory=list)
    data_source: str = Field(default="Catalog")
    freshness: str = Field(default="Demo sample data")
    trade_offs: List[str] = Field(default_factory=list)


class CompareResponse(BaseModel):
    products: List[ProductComparisonItem]
    attribute_matrix: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, 
        description="Key specs mapped per product (e.g. weight, waterproof, battery)"
    )
    price_comparison: Dict[str, Any] = Field(default_factory=dict)
    recommendation_summary: str = Field(..., description="Associate summary highlighting standout differences")


# ==========================================
# 3. 'Why Not' Mode Models
# ==========================================

class WhyNotRequest(BaseModel):
    session_id: str = Field(..., description="Current user session with established constraints")
    product_id: str = Field(..., description="Product ID to analyze for non-recommendation")
    compare_with_id: Optional[str] = Field(default=None, description="Optional recommended product ID to compare against")


class WhyNotResponse(BaseModel):
    target_product_id: str
    target_product_name: str
    session_id: str
    is_eligible: bool
    was_retrieved: bool = Field(default=True, description="True if retrieved as candidate, False if excluded at retrieval stage")
    rejection_status: str = Field(
        default="excluded",
        description="'excluded' | 'ranked_lower' | 'possible_alternative' | 'not_retrieved'"
    )
    explanation: str = Field(..., description="Conversational explanation of why this product was not recommended")
    violated_hard_constraints: List[str] = Field(default_factory=list)
    unmatched_soft_preferences: List[str] = Field(default_factory=list)
    unknown_attributes: List[str] = Field(default_factory=list, description="Attributes requested or required that are unknown on this item")
    what_needs_to_change: List[str] = Field(default_factory=list, description="Actionable changes to make this product eligible or competitive")
    price_analysis: Optional[Dict[str, Any]] = None
    fit_score: Optional[ProductFitScore] = None
    better_alternatives: List[Dict[str, Any]] = Field(default_factory=list)
    compared_product: Optional[Dict[str, Any]] = Field(default=None, description="Direct comparison against recommended product if requested")


# ==========================================
# 4. Constraint Refinement Models
# ==========================================

class RefineRequest(BaseModel):
    session_id: str = Field(..., description="Active session ID to mutate")
    message: Optional[str] = Field(default=None, description="Optional natural language refinement prompt")
    new_budget_max: Optional[float] = Field(default=None, ge=0.0)
    new_budget_currency: Optional[str] = "INR"
    new_colour: Optional[str] = None
    new_size: Optional[str] = None
    new_brand: Optional[str] = None
    added_preferences: List[str] = Field(default_factory=list)
    removed_preferences: List[str] = Field(default_factory=list)


# ==========================================
# 5. Consented Preferences Persistence Models
# ==========================================

class PreferenceSaveRequest(BaseModel):
    user_id: str = Field(default="default_user", description="User or extension profile identifier")
    consent_given: bool = Field(..., description="Explicit affirmative user consent required to save")
    is_memory_enabled: bool = Field(default=True, description="Toggle to enable or disable cross-session preference memory")
    preferred_categories: List[str] = Field(default_factory=list)
    preferred_brands: List[str] = Field(default_factory=list)
    shoe_size: Optional[str] = None
    apparel_size: Optional[str] = None
    budget_tier: Optional[str] = Field(default=None, description="e.g. 'budget', 'mid_range', 'premium'")
    durable_preferences: Optional[Dict[str, Any]] = Field(
        default=None, 
        description="Explicit durable attributes such as sizing, favorite brands, and materials (e.g. vegan)"
    )
    custom_notes: Optional[str] = None


class PreferenceResponse(BaseModel):
    user_id: str
    consent_given: bool
    is_memory_enabled: bool = Field(default=True)
    memory_status: str = Field(default="active", description="'active', 'disabled', or 'no_consent'")
    preferences: Optional[Dict[str, Any]] = None
    durable_preferences: Optional[Dict[str, Any]] = None
    last_updated_at: Optional[str] = None


# ==========================================
# 6. Structured Error Response Model
# ==========================================

class ErrorResponse(BaseModel):
    error: bool = True
    message: str
    status_code: int
    details: Optional[Any] = None
