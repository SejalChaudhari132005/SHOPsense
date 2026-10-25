"""
Agent 7: Explanation Generation Agent
Generates evidence-grounded conversational explanations for recommendations.
Highlights satisfied constraints, matched preferences, trade-offs, and unverified aspects
strictly based on structured product data without inventing specifications.
"""

from typing import List, Tuple
from app.models.product import Product
from app.models.state import ExtractedIntent, ProductFitScore, ProductRecommendation
from app.services.llm_service import generate_explanation_with_llm


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

        eligible_items = [pair for pair in ranked_items if pair[1].is_eligible][:top_k]

        for idx, (product, fit_score) in enumerate(eligible_items):
            # Extract key benefits from exact matches
            key_benefits = []
            for m in fit_score.exact_matches:
                if not m.startswith("category:") and m != "budget_sweet_spot":
                    key_benefits.append(m.replace("use_case:", "Ideal for ").capitalize())

            # Detect meaningful trade-offs
            trade_offs = []
            if fit_score.budget_score < 18.0 and intent.budget_max:
                trade_offs.append(f"Near upper budget limit (${product.normalized_price_usd:.2f})")

            # Check weight tradeoff
            weight = product.specifications.get("weight_kg")
            if weight and weight > 1.5 and "lightweight" in intent.soft_preferences:
                trade_offs.append(f"Heavier build ({weight}kg) prioritized durability over featherweight")

            # Check unverified aspects
            unverified_aspects = fit_score.unknown_attributes

            # Generate natural language associate explanation
            explanation_text = generate_explanation_with_llm(product, intent, fit_score)

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
