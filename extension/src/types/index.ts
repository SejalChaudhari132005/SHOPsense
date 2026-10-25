// ShopSense AI — Shared TypeScript Type Definitions
// Exactly matches FastAPI backend schemas (models/product.py, models/state.py, models/api_schemas.py)

export type AvailabilityStatus = 'in_stock' | 'low_stock' | 'out_of_stock' | 'preorder' | 'unknown';
export type DataSourceType = 'local_demo' | 'verified_partner' | 'extension_scraped' | 'manual_seed' | 'unknown';

export interface ShippingInfo {
  free_shipping: boolean;
  estimated_days?: number | null;
  shipping_cost?: number | null;
  currency?: string | null;
  carrier?: string | null;
}

export interface ProductProvenance {
  is_sample_data: boolean;
  data_source_type: DataSourceType;
  verified: boolean;
  confidence_score: number;
  missing_fields: string[];
  notes?: string | null;
}

export interface Product {
  product_id: string;
  product_name: string;
  brand: string;
  category: string;
  subcategory?: string | null;
  description: string;
  price: number;
  currency: string;
  normalized_price_usd?: number | null;
  product_url?: string | null;
  image_url?: string | null;
  source_store: string;
  source_product_id?: string | null;
  attributes: Record<string, any>;
  use_cases: string[];
  tags: string[];
  sizes?: string[] | null;
  colours?: string[] | null;
  specifications: Record<string, any>;
  availability: AvailabilityStatus;
  rating?: number | null;
  review_count?: number | null;
  shipping_information?: ShippingInfo | null;
  last_verified_at?: string | null;
  data_source_type: DataSourceType;
  provenance: ProductProvenance;
}

export interface ProductFitScore {
  product_id: string;
  product_name: string;
  total_score: number;
  is_eligible: boolean;
  category_score: number;
  use_case_score: number;
  feature_score: number;
  budget_score: number;
  preference_score: number;
  exact_matches: string[];
  partial_matches: string[];
  unknown_attributes: string[];
  violated_hard_constraints: string[];
}

export interface ProductRecommendation {
  product: Product;
  fit_score: ProductFitScore;
  explanation: string;
  key_benefits: string[];
  trade_offs: string[];
  unverified_aspects: string[];
}

export interface ClarificationDecision {
  needs_clarification: boolean;
  completeness_score: number;
  confidence_score?: number;
  clarification_question?: string | null;
  suggested_options: string[];
  missing_critical_fields: string[];
  decision_reason?: string | null;
  risk_assessment?: 'low' | 'medium' | 'high' | string;
  ambiguity_factors?: string[];
  reason?: string | null;
}

export interface FallbackSuggestion {
  fallback_needed: boolean;
  reason: string;
  relaxed_constraints: Record<string, any>;
  original_constraints: Record<string, any>;
  original_budget?: number | null;
  proposed_budget?: number | null;
  price_delta?: number | null;
  exact_change_made?: string;
  remaining_unmet_requirements?: string[];
  relaxation_type?: 'budget_increase' | 'relax_soft_preference' | 'relax_brand_filter' | 'catalog_broadening' | string;
  requires_user_approval?: boolean;
  suggested_alternatives: Product[];
  explanation: string;
}

export interface ComplementarySuggestion {
  product: Product;
  utility_explanation: string;
  why_relevant: string;
  price_formatted: string;
  is_pushy?: boolean;
  data_provenance: string;
}

export interface OrchestratorResponse {
  session_id: string;
  turn_id: number;
  action_taken: 'recommend' | 'clarify' | 'fallback' | 'error' | string;
  message: string;
  recommendations: ProductRecommendation[];
  clarification?: ClarificationDecision | null;
  fallback?: FallbackSuggestion | null;
  follow_up_suggestion?: ComplementarySuggestion | null;
  top_three_comparison?: Array<Record<string, any>> | null;
  session_summary?: Record<string, any> | null;
  sources_consulted?: string[];
  store_statuses?: Array<Record<string, any>>;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant' | 'system';
  text: string;
  timestamp: number;
  turnId?: number;
  actionTaken?: string;
  recommendations?: ProductRecommendation[];
  clarification?: ClarificationDecision | null;
  fallback?: FallbackSuggestion | null;
  follow_up_suggestion?: ComplementarySuggestion | null;
  topThreeComparison?: Array<Record<string, any>> | null;
  sourcesConsulted?: string[];
  storeStatuses?: Array<Record<string, any>>;
  isError?: boolean;
}

export interface ProductComparisonItem {
  product_id: string;
  product_name: string;
  brand: string;
  category: string;
  price: number;
  currency: string;
  normalized_price_usd: number;
  rating?: number | null;
  review_count?: number | null;
  highlights: string[];
  advantages?: string[];
  key_specs: Record<string, any>;
  fit_score?: number | null;
  hard_constraint_satisfaction?: Record<string, boolean>;
  soft_preference_matches?: string[];
  fit_score_breakdown?: Record<string, number> | null;
  unknown_attributes?: string[];
  data_source?: string;
  freshness?: string;
  trade_offs?: string[];
}

export interface CompareResponse {
  products: ProductComparisonItem[];
  attribute_matrix: Record<string, Record<string, any>>;
  price_comparison: Record<string, any>;
  recommendation_summary: string;
}

export interface WhyNotResponse {
  target_product_id: string;
  target_product_name: string;
  session_id: string;
  is_eligible: boolean;
  was_retrieved?: boolean;
  rejection_status?: 'excluded' | 'ranked_lower' | 'possible_alternative' | 'not_retrieved' | string;
  explanation: string;
  violated_hard_constraints: string[];
  unmatched_soft_preferences: string[];
  unknown_attributes?: string[];
  what_needs_to_change?: string[];
  changes_needed_for_eligibility?: string[];
  price_analysis?: Record<string, any> | null;
  fit_score?: ProductFitScore | null;
  better_alternatives: Array<Record<string, any>>;
  compared_product?: Record<string, any> | null;
  recommended_comparison?: Record<string, any> | null;
}

export interface PreferenceState {
  user_id: string;
  consent_given: boolean;
  is_memory_enabled: boolean;
  memory_status: 'active' | 'disabled' | 'no_consent' | string;
  preferences?: {
    preferred_categories?: string[];
    preferred_brands?: string[];
    shoe_size?: string | null;
    apparel_size?: string | null;
    budget_tier?: string | null;
    [key: string]: any;
  } | null;
  durable_preferences?: Record<string, any> | null;
  last_updated_at?: string | null;
}

export interface RefineRequest {
  session_id: string;
  message?: string | null;
  new_budget_max?: number | null;
  new_budget_currency?: string | null;
  new_colour?: string | null;
  new_size?: string | null;
  new_brand?: string | null;
  added_preferences?: string[];
  removed_preferences?: string[];
}

export interface BackendHealth {
  status: string;
  version: string;
  activeAgents: number;
  groq_configured?: boolean;
  environment?: string;
}

export interface PageContext {
  supported: boolean;
  isProductPage?: boolean;
  host: string;
  url: string;
  title: string;
  price?: string | null;
  brand?: string | null;
  category?: string | null;
  imageUrl?: string | null;
  error?: string;
  extractedProduct?: import('./extraction').ExtractedProduct | null;
}

export * from './extraction';
