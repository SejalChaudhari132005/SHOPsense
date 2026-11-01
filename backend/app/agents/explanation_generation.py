"""
Agent 7: Explanation Generation Agent
Generates evidence-grounded conversational explanations for recommendations.
Highlights satisfied constraints, matched preferences, trade-offs, and unverified aspects
strictly based on structured product data without inventing specifications.
"""

from typing import List, Tuple
from app.models.product import Product
from app.models.state import ExtractedIntent, ProductFitScore, ProductRecommendation
from app.services.currency_service import format_price_in_inr
from app.services.retrieval_constraints import evaluate_recommendation_candidate
from app.services.llm_service import (
    generate_explanation_template,
    validate_explanation,
    generate_recommendation_narrative,
)


class ExplanationGenerationAgent:
    """
    Synthesizes honest associate-style justifications based strictly on verified attributes.
    """

    def explain(
        self,
        ranked_items: List[Tuple[Product, ProductFitScore]],
        intent: ExtractedIntent,
        top_k: int = 3
    ) -> List[ProductRecommendation]:
        recommendations: List[ProductRecommendation] = []

        eligible_items = [
            pair
            for pair in ranked_items
            if pair[1].is_eligible
            and evaluate_recommendation_candidate(pair[0], intent).is_eligible
        ][:top_k]

        for idx, (product, fit_score) in enumerate(eligible_items):
            # Extract key benefits from exact matches
            key_benefits = []
            for m in fit_score.exact_matches:
                if m.startswith(("category:", "subcategory:")) or m in {
                    "budget_sweet_spot",
                    "budget_friendly",
                }:
                    continue
                key_benefits.append(m.replace("use_case:", "Ideal for ").capitalize())

            # Detect meaningful trade-offs
            trade_offs = []
            if fit_score.budget_score < 18.0 and intent.budget_max:
                trade_offs.append(
                    f"Near upper budget limit ({format_price_in_inr(product.price, product.currency)})"
                )

            if intent.intended_use and fit_score.use_case_score == 0:
                trade_offs.append(
                    f"The catalog listing does not mention {intent.intended_use} as a use case"
                )

            # Check weight tradeoff
            weight = product.specifications.get("weight_kg")
            if weight and weight > 1.5 and "lightweight" in intent.soft_preferences:
                trade_offs.append(f"Heavier build ({weight}kg) prioritized durability over featherweight")

            # Check unverified aspects
            unverified_aspects = fit_score.unknown_attributes

            # Generate natural language associate explanation
            explanation_text = generate_explanation_template(product, intent, fit_score)
            if not validate_explanation(
                explanation_text,
                product,
                intent,
                fit_score,
            ):
                explanation_text = (
                    f"{product.brand} {product.product_name} matches your "
                    f"requested {product.category.replace('_', ' ')} category."
                )

            # Add comparative rank note if top candidate
            if idx == 0 and len(eligible_items) > 1:
                explanation_text += f" It ranked #1 overall due to highest alignment with your criteria (Fit Score: {fit_score.total_score}/100)."

            recommendations.append(
                ProductRecommendation(
                    product=product,
                    fit_score=fit_score,
                    explanation=explanation_text,
                    key_benefits=key_benefits[:3],
                    trade_offs=trade_offs,
                    unverified_aspects=unverified_aspects
                )
            )

        return recommendations

    def explain_with_analysis(
        self,
        ranked_items: List[Tuple[Product, ProductFitScore]],
        intent: ExtractedIntent,
        top_k: int = 3,
    ) -> Tuple[List[ProductRecommendation], str | None]:
        recommendations = self.explain(ranked_items, intent, top_k)
        return generate_recommendation_narrative(recommendations, intent)
