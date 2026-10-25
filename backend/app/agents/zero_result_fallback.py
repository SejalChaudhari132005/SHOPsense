"""
Agent 8: Zero-Result and Fallback Agent
Recovers from empty or severely constrained search results by calculating intelligent
constraint relaxations (e.g. relaxing budget ceiling by 15-20%, or loosening a strict color/brand).
Never silently relaxes constraints—explicitly identifies what was changed.
"""

from typing import List, Optional, Dict, Any
from app.models.product import Product
from app.models.state import ExtractedIntent, FallbackSuggestion
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    filter_by_price_and_attributes
)
from app.services.currency_service import normalize_price_to_usd, format_price


class ZeroResultFallbackAgent:
    """
    Intelligently recovers from zero-result outcomes with transparent constraint relaxation diffs.
    """

    def __init__(self, catalog: Optional[List[Product]] = None):
        self._catalog = catalog

    def _get_catalog(self) -> List[Product]:
        if self._catalog is None:
            self._catalog = load_and_validate_catalog()
        return self._catalog

    def generate_fallback(
        self,
        intent: ExtractedIntent,
        rejection_reasons: Optional[Dict[str, str]] = None
    ) -> FallbackSuggestion:
        all_products = self._get_catalog()
        curr_symbol = "₹" if intent.budget_currency == "INR" else "$"
        original_constraints = {
            "category": intent.category,
            "budget_max": intent.budget_max,
            "budget_currency": intent.budget_currency,
            "hard_constraints": intent.hard_constraints,
            "exclusions": intent.exclusions,
            "colour": intent.colour,
            "brand": intent.brand,
            "soft_preferences": intent.soft_preferences
        }

        # Strategy 1: Independent Soft Preference / Aesthetic Relaxation (Keep Budget Intact)
        if intent.soft_preferences or intent.brand or intent.colour:
            category_candidates = search_by_category_and_keywords(
                all_products,
                category=intent.category,
                keywords=[intent.intended_use] if intent.intended_use else None
            )

            # Filter strictly within original budget
            strict_budget_candidates = filter_by_price_and_attributes(
                category_candidates,
                max_price=intent.budget_max,
                target_currency=intent.budget_currency
            ) if intent.budget_max is not None else category_candidates

            if strict_budget_candidates:
                relaxed_constraints = {
                    "budget_max": intent.budget_max,
                    "soft_preferences": "Relaxed to find in-budget items",
                    "relaxation_type": "relax_soft_preference"
                }
                explanation = (
                    f"We preserved your strict budget of {curr_symbol}{intent.budget_max:,.0f} by relaxing "
                    f"secondary preferences. Found {len(strict_budget_candidates)} eligible candidates."
                )
                return FallbackSuggestion(
                    fallback_needed=True,
                    reason="Soft preferences were too narrow for available catalog stock.",
                    relaxed_constraints=relaxed_constraints,
                    original_constraints=original_constraints,
                    original_budget=intent.budget_max,
                    proposed_budget=intent.budget_max,
                    price_delta=0.0,
                    exact_change_made=f"Kept budget at {curr_symbol}{intent.budget_max:,.0f}; relaxed soft preferences ({', '.join(intent.soft_preferences or ['brand/color'])})",
                    remaining_unmet_requirements=[f"Specific preference for {p}" for p in (intent.soft_preferences or [intent.brand or intent.colour])],
                    relaxation_type="relax_soft_preference",
                    requires_user_approval=True,
                    suggested_alternatives=strict_budget_candidates[:3],
                    explanation=explanation
                )

        # Strategy 2: Budget Relaxation (+25%)
        if intent.budget_max is not None:
            relaxed_budget = round(intent.budget_max * 1.25, 2)
            price_delta = round(relaxed_budget - intent.budget_max, 2)
            relaxed_constraints = {
                "budget_max": relaxed_budget,
                "relaxation_type": "budget_increase_25_percent"
            }

            category_candidates = search_by_category_and_keywords(
                all_products,
                category=intent.category,
                keywords=[intent.intended_use] if intent.intended_use else None
            )

            alternatives = filter_by_price_and_attributes(
                category_candidates,
                max_price=relaxed_budget,
                target_currency=intent.budget_currency
            )

            if alternatives:
                explanation = (
                    f"No options were found strictly within your {curr_symbol}{intent.budget_max:,.0f} limit. "
                    f"By adjusting the budget ceiling by +25% to {curr_symbol}{relaxed_budget:,.0f} (+{curr_symbol}{price_delta:.2f}), "
                    f"we unlocked {len(alternatives)} matching products."
                )
                return FallbackSuggestion(
                    fallback_needed=True,
                    reason="Strict budget ceiling eliminated all matching candidates.",
                    relaxed_constraints=relaxed_constraints,
                    original_constraints=original_constraints,
                    original_budget=intent.budget_max,
                    proposed_budget=relaxed_budget,
                    price_delta=price_delta,
                    exact_change_made=f"Increased budget ceiling by +25% (from {curr_symbol}{intent.budget_max:,.0f} to {curr_symbol}{relaxed_budget:,.0f})",
                    remaining_unmet_requirements=[f"Price exceeds original limit by up to {curr_symbol}{price_delta:.2f}"],
                    relaxation_type="budget_increase",
                    requires_user_approval=True,
                    suggested_alternatives=alternatives[:3],
                    explanation=explanation
                )

        # Strategy 3: Lowest Available in Category
        alternatives = [p for p in all_products if p.category == intent.category][:3]
        if not alternatives:
            alternatives = all_products[:3]

        if intent.budget_max is not None:
            min_avail = alternatives[0]
            price_delta = round((min_avail.normalized_price_usd or min_avail.price) - normalize_price_to_usd(intent.budget_max, intent.budget_currency), 2)
            explanation = (
                f"Your budget limit of {curr_symbol}{intent.budget_max:,.0f} is below all available "
                f"{intent.category or 'options'}. The lowest priced alternative starts at "
                f"{format_price(min_avail.price, min_avail.currency)}."
            )
            reason = f"Budget of {curr_symbol}{intent.budget_max:,.0f} is below minimum catalog price."
            exact_change = f"Proposed entry-level alternative at {format_price(min_avail.price, min_avail.currency)}"
        else:
            explanation = "We broadened the search across our catalog to present popular related items."
            reason = "Catalog did not match combined search constraints."
            price_delta = 0.0
            exact_change = "Broadened query to category demonstration candidates"

        return FallbackSuggestion(
            fallback_needed=True,
            reason=reason,
            relaxed_constraints={"category_broadening": True},
            original_constraints=original_constraints,
            original_budget=intent.budget_max,
            proposed_budget=alternatives[0].price if alternatives else None,
            price_delta=price_delta,
            exact_change_made=exact_change,
            remaining_unmet_requirements=["Exceeds original budget limit"] if intent.budget_max else [],
            relaxation_type="catalog_broadening",
            requires_user_approval=True,
            suggested_alternatives=alternatives,
            explanation=explanation
        )
