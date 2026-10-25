"""
Agent 5: Candidate Retrieval Agent
Retrieves a broad candidate pool from multiple store adapters (Local Catalog, Amazon India, Flipkart),
strictly enforces verified hard constraints, handles cross-store duplicates, tracks data quality/provenance,
and flags unverified optional attributes.
"""

from typing import List, Optional, Dict, Any
from app.models.product import Product
from app.models.state import ExtractedIntent, AttributeMappingResult, CandidateRetrievalResult
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    canonicalize_category,
)
from app.services.currency_service import normalize_price_to_usd
from app.services.deduplication_service import deduplicate_cross_store_candidates
from app.adapters.registry import StoreAdapterRegistry, adapter_registry


class CandidateRetrievalAgent:
    """
    Executes broad multi-store retrieval while preserving data integrity and provenance.
    """

    def __init__(
        self,
        catalog: Optional[List[Product]] = None,
        registry: Optional[StoreAdapterRegistry] = None
    ):
        self._catalog = catalog
        self._registry = registry or adapter_registry

    def _get_catalog(self) -> List[Product]:
        if self._catalog is None:
            self._catalog = load_and_validate_catalog()
        return self._catalog

    def retrieve(
        self,
        intent: ExtractedIntent,
        mapping: AttributeMappingResult,
        enabled_stores: Optional[List[str]] = None
    ) -> CandidateRetrievalResult:
        category = mapping.normalized_category or intent.category
        keywords = []
        if intent.category and intent.category != category:
            keywords.append(intent.category)
        if intent.subcategory:
            keywords.append(intent.subcategory)
        if intent.intended_use:
            keywords.append(intent.intended_use)
        if intent.soft_preferences:
            keywords.extend(intent.soft_preferences)

        query_str = " ".join(keywords) if keywords else (category or "")

        broad_candidates: List[Product] = []
        sources_consulted: List[str] = []
        store_statuses: List[Dict[str, Any]] = []
        partial_results: bool = False
        timed_out_stores: List[str] = []
        error_stores: List[str] = []

        # If a custom static catalog was supplied (e.g. for targeted unit tests)
        if self._catalog is not None:
            all_products = self._catalog
            sources_consulted = list({p.source_store for p in all_products})
            broad_candidates = search_by_category_and_keywords(
                all_products,
                category=category,
                keywords=keywords if keywords else None,
                match_all_keywords=False
            )
            if not broad_candidates and keywords:
                broad_candidates = search_by_category_and_keywords(
                    all_products,
                    category=None,
                    keywords=keywords,
                    match_all_keywords=False
                )
        else:
            # Multi-Store Discovery across all enabled store adapters
            retrieval_res = self._registry.search_all_sync(
                query=query_str,
                category=category,
                budget_max=intent.budget_max,
                currency=intent.budget_currency,
                limit_per_store=10,
                enabled_stores=enabled_stores
            )
            broad_candidates = retrieval_res.products
            sources_consulted = retrieval_res.sources_consulted
            store_statuses = [status.model_dump() for status in retrieval_res.store_statuses]
            partial_results = retrieval_res.partial_results
            timed_out_stores = retrieval_res.timed_out_stores
            error_stores = retrieval_res.error_stores

            # If multi-store returned zero with specific query, broaden search to category only
            if not broad_candidates and category:
                fallback_res = self._registry.search_all_sync(
                    query="",
                    category=category,
                    budget_max=intent.budget_max,
                    currency=intent.budget_currency,
                    limit_per_store=10,
                    enabled_stores=enabled_stores
                )
                broad_candidates = fallback_res.products

        # Step 2: Strict Hard Constraint Enforcement (Price ceiling, hard attributes, exclusions)
        candidates: List[Product] = []
        unverified: List[Product] = []
        elimination_reasons: Dict[str, str] = {}
        eliminated_count = 0

        # Compute max budget in USD if specified
        max_usd = None
        if intent.budget_max is not None:
            max_usd = normalize_price_to_usd(intent.budget_max, intent.budget_currency)

        for p in broad_candidates:
            # Ensure normalized USD benchmark price exists
            p_price_usd = p.normalized_price_usd or normalize_price_to_usd(p.price, p.currency)
            p.normalized_price_usd = p_price_usd

            # Hard budget check (Rule #11: Never silently relax hard limits)
            if intent.is_budget_strict and max_usd is not None:
                if p_price_usd > max_usd:
                    eliminated_count += 1
                    elimination_reasons[p.product_id] = (
                        f"Price (${p_price_usd:.2f} USD / {p.currency} {p.price:,.2f}) exceeds strict budget "
                        f"({intent.budget_currency} {intent.budget_max:,.0f} = ${max_usd:.2f} USD)"
                    )
                    continue

            # Exclusions check (e.g. "not leather")
            if intent.exclusions:
                prod_desc_and_tags = (
                    f"{p.product_name} {p.description} {' '.join(p.tags)} "
                    f"{' '.join(f'{k} {v}' for k, v in p.attributes.items())}"
                ).lower()
                excluded = False
                for ex in intent.exclusions:
                    if ex.lower() in prod_desc_and_tags:
                        eliminated_count += 1
                        elimination_reasons[p.product_id] = f"Violates exclusion constraint: contains '{ex}'"
                        excluded = True
                        break
                if excluded:
                    continue

            # Hard attributes check (e.g. must be waterproof)
            hard_failed = False
            IGNORED_HARD_KEYS = {
                "category", "subcategory", "budget", "budget_max", "budget_min", 
                "price", "currency", "shopping_intent", "is_budget_strict"
            }
            for hk, hv in intent.hard_constraints.items():
                if hk.lower() in IGNORED_HARD_KEYS:
                    continue

                actual_val = p.attributes.get(hk) or p.specifications.get(hk)
                if actual_val is None and hasattr(p, hk):
                    actual_val = getattr(p, hk)

                if actual_val is None:
                    # Check text blob if boolean requirement like waterproof or wireless
                    if isinstance(hv, bool) and hv:
                        text_blob = f"{p.product_name} {p.description} {' '.join(p.tags)} {' '.join(p.use_cases)}".lower()
                        if hk.lower() in text_blob:
                            actual_val = True

                if actual_val is None:
                    # Missing hard requirement makes it unverified for a confirmed match
                    unverified.append(p)
                    hard_failed = True
                    break
                elif isinstance(hv, bool):
                    if bool(actual_val) != hv:
                        eliminated_count += 1
                        elimination_reasons[p.product_id] = f"Hard constraint failed: '{hk}' is {actual_val}, expected {hv}"
                        hard_failed = True
                        break
                elif isinstance(hv, (int, float)) and isinstance(actual_val, (int, float)):
                    if actual_val < hv:
                        eliminated_count += 1
                        elimination_reasons[p.product_id] = f"Hard constraint failed: '{hk}' is {actual_val}, expected >= {hv}"
                        hard_failed = True
                        break
                elif str(actual_val).lower() != str(hv).lower():
                    eliminated_count += 1
                    elimination_reasons[p.product_id] = f"Hard constraint failed: '{hk}' is {actual_val}, expected {hv}"
                    hard_failed = True
                    break

            if hard_failed:
                continue

            candidates.append(p)

        # Step 3: Deduplication & Cross-Store Variant Grouping
        # Identifies identical items across stores, groups offers, and computes savings deltas
        deduped_candidates = deduplicate_cross_store_candidates(candidates)

        return CandidateRetrievalResult(
            candidates=deduped_candidates,
            total_found=len(deduped_candidates),
            sources_consulted=sources_consulted,
            unverified_candidates=unverified,
            eliminated_count=eliminated_count,
            elimination_reasons=elimination_reasons,
            store_statuses=store_statuses,
            partial_results=partial_results,
            timed_out_stores=timed_out_stores,
            error_stores=error_stores
        )
