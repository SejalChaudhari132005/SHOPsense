"""
Agent 8: Zero-Result and Fallback Agent.

Finds only category-compatible alternatives, keeps requested features and exclusions
intact, and represents any budget or preference change as an approval proposal.
"""

from typing import Dict, List, Optional, Tuple

from app.models.product import Product
from app.models.state import ExtractedIntent, FallbackSuggestion
from app.services.catalog_service import load_and_validate_catalog, product_matches_subcategory
from app.services.catalog_service import canonicalize_category
from app.services.currency_service import (
    convert_currency,
    format_price_in_inr,
)
from app.services.retrieval_constraints import evaluate_recommendation_candidate
from app.core.config import settings


class ZeroResultFallbackAgent:
    """Generate transparent fallback options without crossing product categories."""

    def __init__(self, catalog: Optional[List[Product]] = None):
        self._catalog = catalog

    def _get_catalog(self) -> List[Product]:
        if self._catalog is None:
            self._catalog = load_and_validate_catalog()
        return self._catalog

    @staticmethod
    def _actions(products: List[Product], requires_approval: bool) -> List[Dict[str, object]]:
        actions: List[Dict[str, object]] = []
        if requires_approval:
            actions.extend([
                {"type": "fallback_approve", "label": "Use these relaxed requirements", "payload": {}},
                {"type": "fallback_reject", "label": "Keep my original requirements", "payload": {}},
            ])
        actions.extend(
            {
                "type": "select_product",
                "label": product.product_name,
                "payload": {"product_id": product.product_id},
            }
            for product in products[:3]
        )
        return actions

    @staticmethod
    def _price_inr(product: Product) -> float:
        return convert_currency(product.price, product.currency, "INR")

    def _compatible_candidates(
        self,
        intent: ExtractedIntent,
        *,
        keep_budget: bool,
    ) -> List[Product]:
        candidate_intent = intent
        if not keep_budget and intent.is_budget_strict:
            candidate_intent = intent.model_copy(update={"is_budget_strict": False})

        comparison_product_ids = set(intent.comparison_product_ids)
        requested_category = intent.category or intent.category_hint
        candidates = [
            product
            for product in self._get_catalog()
            if (
                not comparison_product_ids
                or product.product_id in comparison_product_ids
            )
            and (
                not requested_category
                or canonicalize_category(product.category)
                == canonicalize_category(requested_category)
            )
            if evaluate_recommendation_candidate(
                product,
                candidate_intent,
                allow_related_subcategory=True,
            ).is_eligible
        ]
        if not requested_category:
            return []
        if intent.subcategory and intent.subcategory_is_explicit:
            exact = [
                product
                for product in candidates
                if product_matches_subcategory(product.subcategory, intent.subcategory)
            ]
            if exact:
                candidates = exact
        return sorted(candidates, key=self._price_inr)

    @staticmethod
    def _category_change(
        intent: ExtractedIntent,
        candidates: List[Product],
    ) -> Tuple[Dict[str, object], List[str], str]:
        if not intent.subcategory or not intent.subcategory_is_explicit:
            return {}, [], "exact_matches"

        related = [
            product
            for product in candidates
            if not product_matches_subcategory(product.subcategory, intent.subcategory)
        ]
        if not related:
            return {}, [], "exact_matches"
        return (
            {"subcategory": "related catalog subcategories"},
            [f"Exact product type '{intent.subcategory}' was unavailable."],
            "related_alternatives",
        )

    def generate_fallback(
        self,
        intent: ExtractedIntent,
        rejection_reasons: Optional[Dict[str, str]] = None,
        near_misses: Optional[List[Product]] = None,
        relevance_scores: Optional[Dict[str, float]] = None,
    ) -> FallbackSuggestion:
        relevance_scores = relevance_scores or {}
        near_misses = [
            product for product in (near_misses or [])
            if relevance_scores.get(product.product_id, 0.0) >= settings.MIN_RELEVANCE
        ]
        near_misses.sort(
            key=lambda product: (
                -relevance_scores.get(product.product_id, 0.0),
                self._price_inr(product),
            )
        )
        original_constraints = {
            "category": intent.category,
            "subcategory": intent.subcategory,
            "product_query": intent.product_query,
            "budget_max": intent.budget_max,
            "budget_currency": intent.budget_currency,
            "hard_constraints": intent.hard_constraints,
            "feature_preferences": intent.feature_preferences,
            "exclusions": intent.exclusions,
            "colour": intent.colour,
            "brand": intent.brand,
            "soft_preferences": intent.soft_preferences,
        }
        preserved_constraints = {
            key: value
            for key, value in {
                "category": intent.category,
                "product_query": intent.product_query,
                "budget_max": intent.budget_max,
                "budget_currency": intent.budget_currency,
                "hard_constraints": intent.hard_constraints,
                "feature_preferences": intent.feature_preferences,
                "exclusions": intent.exclusions,
            }.items()
            if value not in (None, {}, [])
        }

        in_budget = self._compatible_candidates(intent, keep_budget=True)
        if in_budget:
            relaxed, unmet, result_kind = self._category_change(intent, in_budget)
            soft_changes: Dict[str, object] = {}
            relaxable_soft_preferences = [
                preference
                for preference in intent.soft_preferences
                if preference not in intent.feature_preferences
            ]
            if relaxable_soft_preferences:
                soft_changes["soft_preferences"] = "relaxed"
                unmet.extend(
                    f"Soft preference '{preference}' was not required for these alternatives."
                    for preference in relaxable_soft_preferences
                )
            if intent.brand:
                soft_changes["brand"] = "relaxed"
                unmet.append(f"Preferred brand '{intent.brand}' was not required.")
            if intent.colour:
                soft_changes["colour"] = "relaxed"
                unmet.append(f"Preferred colour '{intent.colour}' was not required.")
            relaxed.update(soft_changes)
            if soft_changes:
                result_kind = (
                    "related_alternatives"
                    if result_kind == "related_alternatives"
                    else "relaxed_alternatives"
                )

            if relaxed:
                explanation = (
                    "These are relevant alternatives within your original budget and category. "
                    "The listed changes need your approval before your search requirements change."
                )
                reason = "No exact result satisfied the complete request."
            else:
                explanation = (
                    "These are the few items for this need that remain relevant in the catalog; "
                    "no unrelated or cross-category products were used."
                )
                reason = "The search returned no candidates, but eligible catalog products remain."

            return FallbackSuggestion(
                fallback_needed=True,
                result_kind=result_kind,
                reason=reason,
                relaxed_constraints=relaxed,
                preserved_constraints=preserved_constraints,
                original_constraints=original_constraints,
                original_budget=intent.budget_max,
                proposed_budget=intent.budget_max,
                price_delta=0.0,
                exact_change_made=(
                    "; ".join(f"{key}: {value}" for key, value in relaxed.items())
                ),
                remaining_unmet_requirements=unmet,
                relaxation_type=(
                    "relax_soft_preference"
                    if soft_changes
                    else "catalog_broadening"
                    if relaxed
                    else "none"
                ),
                requires_user_approval=bool(relaxed),
                suggested_alternatives=(near_misses or in_budget)[:3],
                explanation=explanation,
                actions=self._actions(
                    (near_misses or in_budget)[:3],
                    bool(relaxed),
                ),
            )

        compatible_without_budget = self._compatible_candidates(intent, keep_budget=False)
        if intent.budget_max is not None and compatible_without_budget:
            minimum = min(compatible_without_budget, key=self._price_inr)
            minimum_price = convert_currency(
                minimum.price,
                minimum.currency,
                "INR",
            )
            budget_inr = convert_currency(
                intent.budget_max, intent.budget_currency, "INR"
            )
            price_delta = round(max(0.0, minimum_price - budget_inr), 2)
            category_change, unmet, _ = self._category_change(
                intent, compatible_without_budget
            )
            proposed_budget = round(minimum_price, 2)
            relaxed_constraints: Dict[str, object] = {
                "budget_max": proposed_budget,
                **category_change,
            }
            if price_delta:
                unmet.insert(
                    0,
                    f"Price exceeds the original budget by "
                    f"{format_price_in_inr(price_delta, 'INR')}.",
                )
            explanation = (
                f"The closest relevant option costs "
                f"{format_price_in_inr(minimum_price, 'INR')}, "
                f"above your {format_price_in_inr(budget_inr, 'INR')} limit. "
                "Your budget will not change unless you approve this proposal."
            )
            return FallbackSuggestion(
                fallback_needed=True,
                result_kind="relaxed_alternatives",
                reason="No compatible product fits the original budget.",
                relaxed_constraints=relaxed_constraints,
                preserved_constraints={
                    key: value
                    for key, value in preserved_constraints.items()
                    if key != "budget_max"
                },
                original_constraints=original_constraints,
                original_budget=intent.budget_max,
                proposed_budget=proposed_budget,
                price_delta=price_delta,
                exact_change_made=(
                    "Proposed budget increase to "
                    f"{format_price_in_inr(proposed_budget, 'INR')}"
                ),
                remaining_unmet_requirements=unmet,
                relaxation_type="budget_increase",
                requires_user_approval=True,
                suggested_alternatives=(near_misses or [minimum])[:3],
                explanation=explanation,
                actions=self._actions(
                    (near_misses or [minimum])[:3],
                    True,
                ),
            )

        return FallbackSuggestion(
            fallback_needed=True,
            result_kind="no_match" if not (intent.category or intent.category_hint) else "no_valid_alternatives",
            reason="No catalog products satisfy the preserved category, feature, and budget requirements.",
            relaxed_constraints={},
            preserved_constraints=preserved_constraints,
            original_constraints=original_constraints,
            original_budget=intent.budget_max,
            proposed_budget=intent.budget_max,
            price_delta=0.0,
            exact_change_made="",
            remaining_unmet_requirements=[
                "No relevant product was verified without changing a required constraint."
            ],
            relaxation_type="none",
            requires_user_approval=True,
            suggested_alternatives=[],
            explanation=(
                "I could not find a valid product in the requested category that meets your "
                "required features and budget. Those requirements remain unchanged. Tell me "
                "which requirement, if any, you would like to reconsider."
            ),
            actions=self._actions([], True),
        )
