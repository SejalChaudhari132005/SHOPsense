"""
ShopSense AI — State and Inter-Agent Contracts
Defines typed models for inputs, extracted intents, clarification decisions,
mapping results, ranking scores, recommendations, session memory, and orchestrator state.
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field

from app.models.product import Product


# ==========================================
# 1. Ingestion & Input Models
# ==========================================

class IngestedQuery(BaseModel):
    session_id: str = Field(..., description="Unique user session identifier")
    turn_id: int = Field(default=1, ge=1, description="Current turn index in dialogue")
    raw_message: str = Field(..., description="Original user message before sanitization")
    sanitized_message: str = Field(..., description="Cleaned, normalized text preserving entities & qualifiers")
    input_source: str = Field(default="text", description="'text' or 'voice'")
    client_context: Dict[str, Any] = Field(default_factory=dict, description="Active browser tab context if provided")
    is_empty: bool = False
    rejection_reason: Optional[str] = None


# ==========================================
# 2. Intent & Constraint Extraction Models
# ==========================================

class ExtractedIntent(BaseModel):
    shopping_intent: str = Field(
        default="product_search", 
        description="Intent type: product_search, gift_buying, comparison, refinement, clarification_answer, general_query"
    )
    category: Optional[str] = Field(default=None, description="Primary product category")
    subcategory: Optional[str] = Field(default=None, description="Granular product subcategory")

    # Financial Constraints
    budget_min: Optional[float] = Field(default=None, ge=0.0, description="Minimum budget constraint")
    budget_max: Optional[float] = Field(default=None, ge=0.0, description="Maximum budget constraint")
    budget_currency: str = Field(default="USD", description="Currency code (USD, INR, EUR, GBP)")
    is_budget_strict: bool = Field(
        default=True, 
        description="True for hard ceiling ('under ₹8000'), False for flexible preference ('around ₹8000')"
    )

    # Core Constraints & Preferences
    hard_constraints: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Non-negotiable criteria (e.g. waterproof=True, brand='AlpineTrack')"
    )
    soft_preferences: List[str] = Field(
        default_factory=list, 
        description="Desirable criteria (e.g. lightweight, cushioned, high rating)"
    )

    # Persona & Occasion
    intended_use: Optional[str] = Field(default=None, description="Target activity (e.g. hiking, travel, running)")
    recipient: Optional[str] = Field(default=None, description="Target recipient (e.g. dad, friend, self)")
    occasion: Optional[str] = Field(default=None, description="Special occasion (e.g. birthday, wedding, holiday)")

    # Physical Attributes
    size: Optional[str] = Field(default=None, description="Size requirement")
    colour: Optional[str] = Field(default=None, description="Preferred color")
    brand: Optional[str] = Field(default=None, description="Preferred brand")
    feature_preferences: List[str] = Field(default_factory=list, description="Specific desired features")
    exclusions: List[str] = Field(default_factory=list, description="Explicitly negated items (e.g. 'not leather')")

    # Uncertainty & State Tracking
    missing_or_uncertain: List[str] = Field(default_factory=list, description="Ambiguous or missing elements")
    is_refinement: bool = Field(default=False, description="True if query mutates previous turn constraints")

    @classmethod
    def _normalize_dict_input(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # 1. Normalize shopping_intent if boolean or invalid
            if not isinstance(data.get("shopping_intent"), str):
                data["shopping_intent"] = "product_search"
            # 2. Normalize budget_currency
            if not data.get("budget_currency"):
                data["budget_currency"] = "USD"
            # 3. Normalize is_budget_strict
            if data.get("is_budget_strict") is None:
                data["is_budget_strict"] = True
            # 4. Normalize hard_constraints if returned as list or non-dict
            hc = data.get("hard_constraints")
            if isinstance(hc, list):
                norm_hc = {}
                for item in hc:
                    if isinstance(item, str):
                        parts = item.split(":") if ":" in item else item.split("=")
                        if len(parts) == 2:
                            norm_hc[parts[0].strip()] = parts[1].strip()
                        else:
                            norm_hc[item.strip()] = True
                data["hard_constraints"] = norm_hc
            elif not isinstance(hc, dict):
                data["hard_constraints"] = {}
            # 5. Normalize soft_preferences and exclusions
            for list_key in ("soft_preferences", "feature_preferences", "exclusions", "missing_or_uncertain"):
                val = data.get(list_key)
                if val is None:
                    data[list_key] = []
                elif isinstance(val, dict):
                    data[list_key] = [f"{k}: {v}" for k, v in val.items()]
                elif isinstance(val, str):
                    data[list_key] = [val]
        return data

    from pydantic import model_validator
    @model_validator(mode="before")
    @classmethod
    def validate_llm_fields(cls, data: Any) -> Any:
        return cls._normalize_dict_input(data)


# ==========================================
# 3. Ambiguity & Clarification Models
# ==========================================

class ClarificationDecision(BaseModel):
    needs_clarification: bool = Field(..., description="Whether to interrupt flow and ask user a question")
    completeness_score: float = Field(..., ge=0.0, le=1.0, description="Confidence in search readiness")
    confidence_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Composite autonomy confidence score")
    clarification_question: Optional[str] = Field(default=None, description="Targeted single question to ask")
    suggested_options: List[str] = Field(default_factory=list, description="Quick-pick suggestions for the user")
    missing_critical_fields: List[str] = Field(default_factory=list, description="Fields causing the ambiguity")
    decision_reason: Optional[str] = Field(default=None, description="Transparent justification for proceeding or asking clarification")
    risk_assessment: str = Field(default="low", description="'low', 'medium', or 'high' risk of violating important constraints")
    ambiguity_factors: List[str] = Field(default_factory=list, description="Detected ambiguous words or conflicting constraint pairs")
    catalog_coverage_feasible: bool = Field(default=True, description="True if catalog contains potential matches for the category")
    reason: Optional[str] = None


# ==========================================
# 4. Catalog Attribute Mapping Models
# ==========================================

class AttributeMappingResult(BaseModel):
    normalized_category: Optional[str] = None
    mapped_attributes: Dict[str, Any] = Field(default_factory=dict, description="Canonical catalog filter keys")
    mapped_use_cases: List[str] = Field(default_factory=list, description="Mapped catalog use case tags")
    applied_synonyms: Dict[str, str] = Field(default_factory=dict, description="Synonym conversions made")
    explanations: List[str] = Field(default_factory=list, description="Transparent audit of mappings")


# ==========================================
# 5. Candidate Retrieval Models
# ==========================================

class CandidateRetrievalResult(BaseModel):
    candidates: List[Product] = Field(default_factory=list, description="Eligible products passing initial filters")
    total_found: int = 0
    sources_consulted: List[str] = Field(default_factory=list)
    unverified_candidates: List[Product] = Field(
        default_factory=list, 
        description="Candidates lacking verification on an optional attribute"
    )
    eliminated_count: int = 0
    elimination_reasons: Dict[str, str] = Field(default_factory=dict)
    store_statuses: List[Dict[str, Any]] = Field(default_factory=list, description="Health and result status per store")
    partial_results: bool = Field(default=False, description="True if one or more stores failed or timed out")
    timed_out_stores: List[str] = Field(default_factory=list)
    error_stores: List[str] = Field(default_factory=list)


# ==========================================
# 6. Ranking & Fit Scoring Models
# ==========================================

class ProductFitScore(BaseModel):
    product_id: str
    product_name: str
    total_score: float = Field(..., ge=0.0, le=100.0, description="Normalized composite fit score (0-100)")
    is_eligible: bool = Field(True, description="False if a hard constraint was violated")

    # Score breakdown factors (weights sum to 100)
    category_score: float = Field(default=0.0, description="Category match contribution (max 20)")
    use_case_score: float = Field(default=0.0, description="Use case fit contribution (max 25)")
    feature_score: float = Field(default=0.0, description="Feature & specification match contribution (max 25)")
    budget_score: float = Field(default=0.0, description="Budget compliance & value contribution (max 20)")
    preference_score: float = Field(default=0.0, description="Soft preferences & brand fit contribution (max 10)")

    exact_matches: List[str] = Field(default_factory=list, description="Explicitly verified user constraints")
    partial_matches: List[str] = Field(default_factory=list, description="Partially or closely aligned features")
    unknown_attributes: List[str] = Field(default_factory=list, description="Attributes unknown on this product")
    violated_hard_constraints: List[str] = Field(default_factory=list, description="Hard constraints failed")


# ==========================================
# 7. Explanation & Recommendation Models
# ==========================================

class ProductRecommendation(BaseModel):
    product: Product
    fit_score: ProductFitScore
    explanation: str = Field(..., description="Natural language associate justification")
    key_benefits: List[str] = Field(default_factory=list, description="Top standout reasons to choose this item")
    trade_offs: List[str] = Field(default_factory=list, description="Honest limitations or compromises")
    unverified_aspects: List[str] = Field(default_factory=list, description="Specs that could not be verified")


# ==========================================
# 8. Zero-Result & Fallback Models
# ==========================================

class FallbackSuggestion(BaseModel):
    fallback_needed: bool = False
    reason: str = Field(..., description="Explanation of why zero or few results occurred")
    relaxed_constraints: Dict[str, Any] = Field(default_factory=dict, description="Constraints that were relaxed")
    original_constraints: Dict[str, Any] = Field(default_factory=dict, description="Original unrelaxed constraints")
    original_budget: Optional[float] = None
    proposed_budget: Optional[float] = None
    price_delta: Optional[float] = None
    exact_change_made: str = Field(default="", description="Precise human-readable diff description (e.g. '+25% budget increase')")
    remaining_unmet_requirements: List[str] = Field(default_factory=list, description="Requirements still unmet by the relaxed alternatives")
    relaxation_type: str = Field(default="budget_increase", description="'budget_increase' | 'relax_soft_preference' | 'relax_brand_filter' | 'catalog_broadening'")
    requires_user_approval: bool = Field(default=True, description="Strictly requires user confirmation before updating active session constraints")
    suggested_alternatives: List[Product] = Field(default_factory=list, description="Alternative products found")
    explanation: str = Field(..., description="Friendly explanation of the trade-off")


# ==========================================
# 8b. Context-Aware Follow-Up Models
# ==========================================

class ComplementarySuggestion(BaseModel):
    product: Product
    utility_explanation: str = Field(..., description="Why this accessory or companion product is uniquely useful")
    why_relevant: str = Field(..., description="Contextual pairing rationale (e.g. travel organizer for a 40L backpack)")
    price_formatted: str
    is_pushy: bool = False
    data_provenance: str = Field(default="Verified Catalog Demonstration")


# ==========================================
# 9. Session Memory Models
# ==========================================

class SessionContext(BaseModel):
    session_id: str
    turn_count: int = 0
    current_intent: Optional[ExtractedIntent] = None
    confirmed_constraints: Dict[str, Any] = Field(default_factory=dict)
    soft_preferences: List[str] = Field(default_factory=list)
    questions_asked: List[str] = Field(default_factory=list)
    shown_product_ids: List[str] = Field(default_factory=list)
    rejected_product_ids: List[str] = Field(default_factory=list)
    latest_refinements: List[str] = Field(default_factory=list)
    last_updated_at: datetime = Field(default_factory=datetime.utcnow)


# ==========================================
# 10. Orchestrator Unified Output
# ==========================================

class OrchestratorResponse(BaseModel):
    session_id: str
    turn_id: int
    action_taken: str = Field(..., description="'recommend', 'clarify', 'fallback', or 'error'")
    message: str = Field(..., description="Primary conversational associate response to the user")
    recommendations: List[ProductRecommendation] = Field(default_factory=list)
    clarification: Optional[ClarificationDecision] = None
    fallback: Optional[FallbackSuggestion] = None
    follow_up_suggestion: Optional[ComplementarySuggestion] = Field(
        default=None, 
        description="At most one relevant, non-pushy complementary product suggestion"
    )
    top_three_comparison: Optional[List[Dict[str, Any]]] = None
    session_summary: Optional[Dict[str, Any]] = None
    sources_consulted: List[str] = Field(default_factory=list, description="Stores searched during this turn")
    store_statuses: List[Dict[str, Any]] = Field(default_factory=list, description="Multi-store status summary")


# ==========================================
# 11. LangGraph Shared Workflow State
# ==========================================

from typing import TypedDict, Tuple

class ShopSenseGraphState(TypedDict, total=False):
    """
    Shared state for the LangGraph 10-Agent state machine.
    """
    session_id: str
    turn_id: int
    original_user_message: str
    input_source: str
    client_context: Dict[str, Any]

    # Agent Data Contracts
    normalized_query: Optional[IngestedQuery]
    current_intent: Optional[ExtractedIntent]
    previous_intent: Optional[ExtractedIntent]
    session_memory: Optional[SessionContext]
    clarification: Optional[ClarificationDecision]
    catalog_mapping: Optional[AttributeMappingResult]
    retrieved_candidates: List[Product]
    eligible_candidates: List[Product]
    ranked_candidates: List[Tuple[Product, ProductFitScore]]
    recommendations: List[ProductRecommendation]
    fallback: Optional[FallbackSuggestion]
    follow_up_suggestion: Optional[ComplementarySuggestion]

    # Operational & Audit Metadata
    data_source_status: str
    sources_consulted: List[str]
    store_statuses: List[Dict[str, Any]]
    error_information: Optional[str]
    workflow_status: str
    final_response: Optional[OrchestratorResponse]
