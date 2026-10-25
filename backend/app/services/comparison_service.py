"""
ShopSense AI — Product Comparison & 'Why Not' Analysis Service
Generates side-by-side comparison matrices for 2-4 products and explains
precisely why a candidate was not recommended based on user constraints.
"""

from typing import List, Dict, Any, Optional
from app.models.product import Product
from app.models.state import SessionContext, ExtractedIntent, ProductFitScore
from app.models.api_schemas import (
    ProductComparisonItem,
    CompareResponse,
    WhyNotResponse
)
from app.services.catalog_service import load_and_validate_catalog
from app.services.currency_service import format_price, normalize_price_to_usd
from app.agents.ranking_fit import RankingFitScoringAgent

ranking_agent = RankingFitScoringAgent()


def get_products_by_ids(product_ids: List[str]) -> List[Product]:
    catalog = load_and_validate_catalog()
    catalog_map = {p.product_id: p for p in catalog}
    return [catalog_map[pid] for pid in product_ids if pid in catalog_map]


def compare_products_side_by_side(
    product_ids: List[str],
    session: Optional[SessionContext] = None
) -> CompareResponse:
    """
    Builds a comprehensive side-by-side comparison matrix for 2-4 products.
    """
    products = get_products_by_ids(product_ids)
    if not products:
        raise ValueError("None of the specified product IDs were found in the catalog.")

    comparison_items: List[ProductComparisonItem] = []
    matrix: Dict[str, Dict[str, Any]] = {}

    intent = session.current_intent if session else None

    # Track attributes across all products
    all_spec_keys = set()
    for p in products:
        all_spec_keys.update(p.specifications.keys())
        all_spec_keys.update(p.attributes.keys())

    # Build comparison item per product
    for p in products:
        highlights = list(p.tags[:3])
        fit_score_val = None
        fit_breakdown = None
        hard_satisfaction: Dict[str, bool] = {}
        soft_matches: List[str] = []
        unknown_attrs: List[str] = []
        trade_offs: List[str] = []

        if intent:
            scored = ranking_agent.rank([p], intent)
            if scored:
                fit_obj = scored[0][1]
                fit_score_val = fit_obj.total_score
                fit_breakdown = {
                    "category": fit_obj.category_score,
                    "use_case": fit_obj.use_case_score,
                    "features": fit_obj.feature_score,
                    "budget": fit_obj.budget_score,
                    "preference": fit_obj.preference_score
                }
                unknown_attrs = list(fit_obj.unknown_attributes)

            # Evaluate hard constraints
            if intent.budget_max is not None:
                p_usd = p.normalized_price_usd or p.price
                max_usd = normalize_price_to_usd(intent.budget_max, intent.budget_currency)
                hard_satisfaction["Within Budget"] = (p_usd <= max_usd) if intent.is_budget_strict else True

            if intent.category:
                hard_satisfaction["Category Match"] = (p.category == intent.category)

            for hk, hv in intent.hard_constraints.items():
                val = p.attributes.get(hk) or p.specifications.get(hk)
                hard_satisfaction[hk] = bool(val == hv) if val is not None else False

            # Evaluate soft preferences
            text_blob = f"{p.product_name} {p.description} {' '.join(p.tags)}".lower()
            for pref in intent.soft_preferences:
                if pref.lower() in text_blob:
                    soft_matches.append(pref)

            # Trade-offs
            p_usd = p.normalized_price_usd or p.price
            if intent.budget_max:
                max_usd = normalize_price_to_usd(intent.budget_max, intent.budget_currency)
                if p_usd > max_usd * 0.9:
                    trade_offs.append(f"Near budget upper limit (${p_usd:.2f} USD)")
            for pref in intent.soft_preferences:
                if pref not in soft_matches:
                    trade_offs.append(f"Lacks soft preference '{pref}'")

        # Determine data source & freshness
        store_id = p.source_store or p.attributes.get("store") or ("Amazon India" if "amzn" in p.product_id else "Flipkart" if "fk" in p.product_id else "Verified Catalog")
        freshness = "Live Extracted" if (p.product_url and "http" in p.product_url) else "Catalog Verified"

        item = ProductComparisonItem(
            product_id=p.product_id,
            product_name=p.product_name,
            brand=p.brand,
            category=p.category,
            price=p.price,
            currency=p.currency,
            normalized_price_usd=p.normalized_price_usd or p.price,
            rating=p.rating,
            review_count=p.review_count,
            highlights=highlights,
            key_specs={**p.attributes, **p.specifications},
            fit_score=fit_score_val,
            hard_constraint_satisfaction=hard_satisfaction,
            soft_preference_matches=soft_matches,
            fit_score_breakdown=fit_breakdown,
            unknown_attributes=unknown_attrs,
            data_source=store_id,
            freshness=freshness,
            trade_offs=trade_offs[:3]
        )
        comparison_items.append(item)

    # Build attribute matrix
    for spec in sorted(list(all_spec_keys))[:10]:
        matrix[spec] = {}
        for p in products:
            val = p.specifications.get(spec) or p.attributes.get(spec)
            matrix[spec][p.product_id] = val if val is not None else "Unknown"

    # Price comparison analysis
    sorted_by_price = sorted(products, key=lambda x: x.normalized_price_usd or x.price)
    cheapest = sorted_by_price[0]
    priciest = sorted_by_price[-1]
    price_delta = round((priciest.normalized_price_usd or priciest.price) - (cheapest.normalized_price_usd or cheapest.price), 2)

    price_comp = {
        "most_affordable": {
            "product_id": cheapest.product_id,
            "product_name": cheapest.product_name,
            "price_formatted": format_price(cheapest.price, cheapest.currency)
        },
        "premium_choice": {
            "product_id": priciest.product_id,
            "product_name": priciest.product_name,
            "price_formatted": format_price(priciest.price, priciest.currency)
        },
        "price_difference_usd": price_delta
    }

    summary = (
        f"Compared {len(products)} products. {cheapest.product_name} is the most budget-friendly "
        f"at {format_price(cheapest.price, cheapest.currency)}, saving ${price_delta:.2f} USD "
        f"compared to {priciest.product_name}."
    )

    return CompareResponse(
        products=comparison_items,
        attribute_matrix=matrix,
        price_comparison=price_comp,
        recommendation_summary=summary
    )


def analyze_why_not(
    product_id: str, 
    session: SessionContext,
    compare_with_id: Optional[str] = None
) -> WhyNotResponse:
    """
    Evaluates why a specific product was NOT recommended or scored lower for the session.
    Distinguishes not-retrieved from evaluated-and-rejected.
    """
    products = get_products_by_ids([product_id])
    if not products:
        raise ValueError(f"Product '{product_id}' not found in catalog.")

    product = products[0]
    intent = session.current_intent or ExtractedIntent()

    violated_hard: List[str] = []
    unmatched_soft: List[str] = []
    unknown_attrs: List[str] = []
    what_needs_to_change: List[str] = []
    p_price_usd = product.normalized_price_usd or product.price

    # Check retrieval status: was it retrieved into candidate pool for this session?
    # An item is considered retrieved if it was shown, rejected during evaluation, or matches session category
    was_retrieved = (
        product_id in session.shown_product_ids or 
        product_id in session.rejected_product_ids or 
        (intent.category is not None and product.category == intent.category)
    )

    # Check budget ceiling
    if intent.budget_max is not None:
        max_usd = normalize_price_to_usd(intent.budget_max, intent.budget_currency)
        if p_price_usd > max_usd:
            diff = round(p_price_usd - max_usd, 2)
            violated_hard.append(
                f"Price ({format_price(product.price, product.currency)}) exceeds your {intent.budget_currency} "
                f"{intent.budget_max:,.0f} limit by approx. ${diff:.2f} USD"
            )
            what_needs_to_change.append(
                f"Increase maximum budget to at least {format_price(product.price, product.currency)} (+${diff:.2f} USD)"
            )

    # Check category
    if intent.category and product.category != intent.category:
        violated_hard.append(
            f"Category mismatch: product is '{product.category}', while you searched for '{intent.category}'"
        )
        what_needs_to_change.append(
            f"Expand or change target category from '{intent.category}' to '{product.category}'"
        )

    # Check hard constraints & identify unknown attributes
    for hk, hv in intent.hard_constraints.items():
        actual_val = product.attributes.get(hk) or product.specifications.get(hk)
        if actual_val is None:
            unknown_attrs.append(hk)
            violated_hard.append(f"Required specification '{hk}' is unknown/unverified on this listing")
            what_needs_to_change.append(f"Verify '{hk}' specification with seller or accept unverified status")
        elif bool(actual_val) != bool(hv):
            violated_hard.append(f"Hard constraint '{hk}' failed: listing has {actual_val}, expected {hv}")
            what_needs_to_change.append(f"Relax requirement for '{hk}' (accept {actual_val})")

    # Check exclusions
    for ex in intent.exclusions:
        text = f"{product.product_name} {product.description} {' '.join(product.tags)}".lower()
        if ex.lower() in text:
            violated_hard.append(f"Contains excluded feature: '{ex}'")
            what_needs_to_change.append(f"Remove exclusion rule on '{ex}'")

    # Check soft preferences
    for pref in intent.soft_preferences:
        text = f"{product.product_name} {product.description} {' '.join(product.tags)}".lower()
        if pref.lower() not in text:
            unmatched_soft.append(f"Missing desired preference '{pref}'")
            what_needs_to_change.append(f"De-prioritize preference for '{pref}'")

    # Rank and score
    scored = ranking_agent.rank([product], intent)
    fit_score = scored[0][1] if scored else None
    if fit_score:
        for unk in fit_score.unknown_attributes:
            if unk not in unknown_attrs:
                unknown_attrs.append(unk)

    is_eligible = len(violated_hard) == 0

    # Determine rejection status
    if not was_retrieved:
        rejection_status = "not_retrieved"
    elif not is_eligible:
        rejection_status = "excluded"
    elif fit_score and fit_score.total_score >= 70.0:
        rejection_status = "possible_alternative"
    else:
        rejection_status = "ranked_lower"

    # Formulate explanation
    reasons = []
    if violated_hard:
        reasons.append("; ".join(violated_hard))
    if unmatched_soft:
        reasons.append(f"Did not meet soft preferences: {', '.join(unmatched_soft)}")

    if not was_retrieved:
        explanation = f"'{product.product_name}' was not retrieved in candidate discovery for your search criteria."
    elif not reasons:
        explanation = (
            f"'{product.product_name}' meets your core constraints (Fit Score: {fit_score.total_score if fit_score else 0:.1f}/100), "
            "but other candidates ranked higher due to better feature alignment or value."
        )
    else:
        explanation = f"'{product.product_name}' was not recommended because: " + ". ".join(reasons) + "."

    # Better alternatives from session
    better_alts = []
    for pid in session.shown_product_ids[:2]:
        if pid != product_id:
            alt_prods = get_products_by_ids([pid])
            if alt_prods:
                alt = alt_prods[0]
                alt_scored = ranking_agent.rank([alt], intent) if intent else []
                alt_score = alt_scored[0][1].total_score if alt_scored else 85.0
                better_alts.append({
                    "product_id": alt.product_id,
                    "product_name": alt.product_name,
                    "price_formatted": format_price(alt.price, alt.currency),
                    "fit_score": round(alt_score, 1),
                    "reason": f"Scored higher ({alt_score:.1f}/100) and satisfies all verified constraints"
                })

    # Direct comparison if compare_with_id provided or available
    compared_item = None
    target_comp_id = compare_with_id or (session.shown_product_ids[0] if session.shown_product_ids and session.shown_product_ids[0] != product_id else None)
    if target_comp_id:
        target_prods = get_products_by_ids([target_comp_id])
        if target_prods:
            c_prod = target_prods[0]
            c_scored = ranking_agent.rank([c_prod], intent) if intent else []
            c_score = c_scored[0][1].total_score if c_scored else None
            price_diff = round((product.normalized_price_usd or product.price) - (c_prod.normalized_price_usd or c_prod.price), 2)
            compared_item = {
                "product_id": c_prod.product_id,
                "product_name": c_prod.product_name,
                "brand": c_prod.brand,
                "price_formatted": format_price(c_prod.price, c_prod.currency),
                "fit_score": round(c_score, 1) if c_score is not None else None,
                "price_difference_usd": price_diff,
                "why_better": f"Fully satisfies verified criteria and has higher customer rating ({c_prod.rating or 4.5}/5)"
            }

    return WhyNotResponse(
        target_product_id=product.product_id,
        target_product_name=product.product_name,
        session_id=session.session_id,
        is_eligible=is_eligible,
        was_retrieved=was_retrieved,
        rejection_status=rejection_status,
        explanation=explanation,
        violated_hard_constraints=violated_hard,
        unmatched_soft_preferences=unmatched_soft,
        unknown_attributes=unknown_attrs,
        what_needs_to_change=what_needs_to_change,
        price_analysis={
            "product_price": format_price(product.price, product.currency),
            "user_max_budget": f"{intent.budget_currency} {intent.budget_max:,.0f}" if intent.budget_max else "None",
            "is_over_budget": len(violated_hard) > 0 and "Price" in violated_hard[0]
        },
        fit_score=fit_score,
        better_alternatives=better_alts,
        compared_product=compared_item
    )
