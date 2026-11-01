"""Agent 5: Hybrid retrieval and verified hard filtering over the local catalog."""

import logging
import inspect
from pathlib import Path
from typing import List, Optional, Dict, Any, Set

from app.core.config import settings
from app.models.product import Product
from app.models.state import ExtractedIntent, AttributeMappingResult, CandidateRetrievalResult
from app.services.catalog_service import (
    canonicalize_category,
    find_catalog_product_by_name,
    load_and_validate_catalog,
    product_matches_subcategory,
)
from app.services.hybrid_retrieval import get_hybrid_catalog_index, cosine_to_relevance
from app.services.retrieval_constraints import evaluate_hard_constraints
from app.adapters.registry import StoreAdapterRegistry, adapter_registry

logger = logging.getLogger(__name__)


class CandidateRetrievalAgent:
    """
    Executes broad multi-store retrieval while preserving data integrity and provenance.
    """

    EXACT_FALLBACK_CONFIDENCE_THRESHOLD = 60.0

    def __init__(
        self,
        catalog: Optional[List[Product]] = None,
        registry: Optional[StoreAdapterRegistry] = None
    ):
        self._catalog = catalog
        self._catalog_is_injected = catalog is not None
        self._catalog_signature = None
        self._registry = registry or adapter_registry

    def _get_catalog(self) -> List[Product]:
        if self._catalog_is_injected:
            return self._catalog or []

        catalog_path = Path(settings.CATALOG_PATH)
        try:
            stat = catalog_path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None

        if self._catalog is None or signature != self._catalog_signature:
            self._catalog = load_and_validate_catalog(str(catalog_path))
            self._catalog_signature = signature
        return self._catalog

    @staticmethod
    def build_retrieval_query(
        intent: ExtractedIntent,
        mapping: AttributeMappingResult,
        query_text: Optional[str],
    ) -> str:
        slots = [
            intent.product_query,
            intent.intended_use,
            *intent.health_considerations,
            *intent.feature_preferences,
            *intent.soft_preferences,
            *mapping.expansions,
            intent.category_hint,
        ]
        if intent.category and intent.category_is_explicit:
            slots.append(intent.category)
        if intent.subcategory and intent.subcategory_is_explicit:
            slots.append(intent.subcategory)
        values = list(dict.fromkeys(
            value.strip() for value in slots
            if isinstance(value, str) and value.strip()
        ))
        return " ".join(values)

    def retrieve(
        self,
        intent: ExtractedIntent,
        mapping: AttributeMappingResult,
        enabled_stores: Optional[List[str]] = None,
        query_text: Optional[str] = None,
        excluded_product_ids: Optional[List[str]] = None,
    ) -> CandidateRetrievalResult:
        category = mapping.normalized_category or intent.category
        catalog = self._get_catalog()
        query_str = self.build_retrieval_query(intent, mapping, query_text)
        allowed_product_ids: Set[str] = set()
        unverified: List[Product] = []
        elimination_reasons: Dict[str, str] = {}
        eliminated_count = 0
        for product in catalog:
            evaluation = evaluate_hard_constraints(
                product,
                intent,
                excluded_product_ids=excluded_product_ids,
            )
            if evaluation.is_eligible:
                allowed_product_ids.add(product.product_id)
            else:
                eliminated_count += 1
                elimination_reasons[product.product_id] = "; ".join(evaluation.violations)
                if evaluation.unknown_attributes:
                    unverified.append(product)

        comparison_product_ids = set(intent.comparison_product_ids)
        if comparison_product_ids:
            allowed_product_ids.intersection_update(comparison_product_ids)

        hybrid_index = get_hybrid_catalog_index(catalog)
        requirement_count = (
            len(intent.feature_preferences)
            + len(intent.hard_constraints)
            + len(intent.exclusions)
            + int(bool(intent.size))
            + int(bool(intent.colour))
            + int(bool(intent.brand))
        )
        candidate_limit = 20
        search_parameters = inspect.signature(hybrid_index.search).parameters
        if "limit" in search_parameters or any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in search_parameters.values()
        ):
            hybrid_result = hybrid_index.search(
                query_str,
                allowed_product_ids=allowed_product_ids,
                limit=candidate_limit,
            )
        else:
            # Preserve compatibility with injected indexes from older callers.
            hybrid_result = hybrid_index.search(
                query_str,
                allowed_product_ids=allowed_product_ids,
            )
        hybrid_candidates = [
            hybrid_index.products_by_id[product_id]
            for product_id in hybrid_result.product_ids[:candidate_limit]
        ]
        relevance_scores: Dict[str, float] = {}
        semantic_scores = getattr(hybrid_result, "semantic_scores", {})
        bm25_coverage = getattr(hybrid_result, "bm25_coverage", {})
        for product in hybrid_candidates:
            product_id = product.product_id
            semantic_relevance = cosine_to_relevance(
                semantic_scores.get(product_id, -1.0)
            ) if semantic_scores else 0.0
            coverage = bm25_coverage.get(product_id, 0.0)
            relevance = max(
                semantic_relevance,
                coverage,
            ) if semantic_scores else 0.8 * coverage
            if (
                intent.category
                and intent.category_is_explicit
                and canonicalize_category(product.category)
                == canonicalize_category(intent.category)
            ):
                relevance = max(relevance, 0.55)
                if (
                    intent.subcategory
                    and intent.subcategory_is_explicit
                    and product_matches_subcategory(
                        product.subcategory,
                        intent.subcategory,
                    )
                ):
                    relevance = max(relevance, 0.65)
            # Compatibility for older injected test doubles; production
            # indexes always provide semantic/corpus signals.
            if not semantic_scores and not bm25_coverage:
                relevance = hybrid_result.rrf_scores.get(product_id, 0.0) / 100.0
            relevance_scores[product_id] = relevance
        passing_ids = {
            product_id for product_id, relevance in relevance_scores.items()
            if relevance > settings.MIN_RELEVANCE
        }
        near_misses = [
            product for product in hybrid_candidates
            if product.product_id not in passing_ids
        ][:3]
        hybrid_candidates = [
            product for product in hybrid_candidates
            if product.product_id in passing_ids
        ]
        hybrid_product_ids = {
            product.product_id for product in hybrid_candidates
        }
        comparison_incomplete = bool(
            comparison_product_ids
            and not comparison_product_ids.issubset(hybrid_product_ids)
        )
        exact_fallback_used = False
        if (
            not hybrid_candidates
            or comparison_incomplete
        ):
            if comparison_product_ids:
                exact_fallback_candidates = [
                    product
                    for product in catalog
                    if product.product_id in comparison_product_ids
                ]
            else:
                exact_product = find_catalog_product_by_name(
                    query_text or intent.product_query or ""
                )
                if exact_product is None and intent.product_query:
                    exact_product = find_catalog_product_by_name(intent.product_query)
                exact_fallback_candidates = [exact_product] if exact_product else []

            exact_fallback_candidates = [
                product
                for product in exact_fallback_candidates
                if product.product_id in allowed_product_ids
                and evaluate_hard_constraints(
                    product,
                    intent,
                    excluded_product_ids=excluded_product_ids,
                ).is_eligible
            ]
            if exact_fallback_candidates:
                hybrid_candidates = exact_fallback_candidates
                exact_fallback_used = True
                logger.info(
                    "Hybrid retrieval relevance gate returned no passing candidates; using exact catalog fallback.",
                )

        adapter_candidates: List[Product] = []
        sources_consulted: List[str] = ["local_catalog"]
        store_statuses: List[Dict[str, Any]] = []
        partial_results: bool = False
        timed_out_stores: List[str] = []
        error_stores: List[str] = []

        candidate_by_id: Dict[str, Product] = {}
        accepted_catalog_ids = (
            {product.product_id for product in hybrid_candidates}
            if not exact_fallback_used
            else {product.product_id for product in exact_fallback_candidates}
        )
        catalog_product_ids = {product.product_id for product in catalog}
        for product in [*hybrid_candidates, *adapter_candidates]:
            if (
                product.product_id in catalog_product_ids
                and product.product_id not in accepted_catalog_ids
            ):
                continue
            candidate_by_id.setdefault(product.product_id, product)

        eligible_candidates: List[Product] = []
        for product in candidate_by_id.values():
            evaluation = evaluate_hard_constraints(
                product,
                intent,
                excluded_product_ids=excluded_product_ids,
            )
            if evaluation.is_eligible:
                eligible_candidates.append(product)
            else:
                eliminated_count += 1
                elimination_reasons[product.product_id] = "; ".join(evaluation.violations)
                if evaluation.unknown_attributes and product not in unverified:
                    unverified.append(product)

        retrieval_scores: Dict[str, float] = {}
        retrieval_sources: Dict[str, List[str]] = {}
        for product in eligible_candidates:
            product_id = product.product_id
            retrieval_scores[product_id] = float(
                1.0 if exact_fallback_used else relevance_scores.get(product_id, 0.0)
            )
            if exact_fallback_used:
                relevance_scores[product_id] = 1.0
            sources = (
                ["exact_fallback"]
                if exact_fallback_used
                else list(hybrid_result.retrieval_sources.get(product_id, []))
            )
            if product in adapter_candidates and "store_search" not in sources:
                sources.append("store_search")
            retrieval_sources[product_id] = sources

        return CandidateRetrievalResult(
            candidates=eligible_candidates,
            total_found=len(eligible_candidates),
            retrieval_scores=retrieval_scores,
            retrieval_sources=retrieval_sources,
            retrieval_mode=(
                "exact_fallback"
                if exact_fallback_used
                else hybrid_result.retrieval_mode
            ),
            relevance_scores=relevance_scores,
            near_misses=near_misses,
            sources_consulted=sources_consulted,
            unverified_candidates=unverified,
            eliminated_count=eliminated_count,
            elimination_reasons=elimination_reasons,
            store_statuses=store_statuses,
            partial_results=partial_results,
            timed_out_stores=timed_out_stores,
            error_stores=error_stores
        )
