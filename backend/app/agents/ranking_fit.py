"""
Agent 6: Ranking and Fit Scoring Agent
Deterministic, mathematically sound multi-factor scoring system (0-100).
Enforces hard constraints before ranking so that a high score never compensates
for a broken rule. Distinguishes exact, partial, and unknown attributes.
"""

import re
from typing import Dict, List, Optional, Tuple
from app.models.product import Product
from app.models.state import ExtractedIntent, ProductFitScore
from app.services.currency_service import convert_currency
from app.services.catalog_service import (
    canonicalize_category,
    match_synonyms,
    product_matches_subcategory,
)
from app.services.retrieval_constraints import evaluate_hard_constraints, resolve_hard_value


class RankingFitScoringAgent:
    """
    Ranks candidate products using a deterministic weighted matrix.
    Category (20%) + Use Case (25%) + Features (25%) + Budget (20%) + Preferences/Brand (10%) = 100%
    """

    def rank(
        self,
        candidates: List[Product],
        intent: ExtractedIntent,
        retrieval_scores: Optional[Dict[str, float]] = None,
        retrieval_sources: Optional[Dict[str, List[str]]] = None,
        excluded_product_ids: Optional[List[str]] = None,
    ) -> List[Tuple[Product, ProductFitScore]]:
        scored_pairs: List[Tuple[Product, ProductFitScore]] = []
        retrieval_scores = retrieval_scores or {}
        retrieval_sources = retrieval_sources or {}
        has_retrieval_scores = bool(retrieval_scores)

        max_inr = None
        if intent.budget_max is not None:
            max_inr = convert_currency(
                intent.budget_max, intent.budget_currency, "INR"
            )

        for p in candidates:
            p_price_inr = convert_currency(p.price, p.currency, "INR")
            exact_matches: List[str] = []
            partial_matches: List[str] = []
            unknown_attributes: List[str] = []
            constraint_result = evaluate_hard_constraints(
                p,
                intent,
                excluded_product_ids=excluded_product_ids,
            )
            violated_hard = list(constraint_result.violations)
            unknown_attributes.extend(constraint_result.unknown_attributes)

            # 1. Hard Constraint Verification
            is_eligible = constraint_result.is_eligible
            relevance = retrieval_scores.get(
                p.product_id,
                1.0 if not has_retrieval_scores else 0.0,
            )
            for hk in intent.hard_constraints:
                val = resolve_hard_value(p, hk)
                if val is None:
                    if hk not in unknown_attributes:
                        unknown_attributes.append(hk)
                elif not any(
                    f"'{hk}'" in violation for violation in violated_hard
                ):
                    exact_matches.append(hk)

            # 2. Factor 1: Category Match (Max 20.0)
            category_score = 0.0
            if intent.category and intent.category_is_explicit:
                if canonicalize_category(p.category) == canonicalize_category(intent.category):
                    category_score = 20.0
                    exact_matches.append(f"category:{p.category}")
                else:
                    category_score = 0.0
            else:
                category_score = 15.0  # open category query

            # 3. Factor 2: Use-Case Fit (Max 25.0)
            use_case_score = 0.0
            if intent.intended_use:
                product_text = " ".join([
                    p.product_name,
                    p.description,
                    p.subcategory or "",
                    *p.tags,
                    *p.use_cases,
                ]).lower().replace("_", " ")
                use_terms = [
                    term for term in re.findall(r"[a-z0-9]+", intent.intended_use.lower())
                    if term not in {"and", "or", "use", "for", "the", "a", "an", "to", "with"}
                ]
                use_synonyms = {
                    "everyday": ("everyday", "daily", "day-to-day"),
                    "daily": ("daily", "everyday", "day-to-day"),
                    "casual": ("casual", "walking"),
                }
                matched_use_terms = [
                    term for term in use_terms
                    if any(
                        synonym in product_text
                        for synonym in use_synonyms.get(term, (term,))
                    )
                ]
                if use_terms:
                    use_case_score = 25.0 * len(matched_use_terms) / len(use_terms)
                    if len(matched_use_terms) == len(use_terms):
                        exact_matches.append(f"use_case:{intent.intended_use.lower()}")
                    elif matched_use_terms:
                        partial_matches.append(
                            f"use_case:{','.join(matched_use_terms)}"
                        )
            else:
                use_case_score = 20.0
            if intent.subcategory and product_matches_subcategory(p.subcategory, intent.subcategory):
                exact_matches.append(f"subcategory:{intent.subcategory}")

            # 4. Factor 3: Feature & Spec Matches (Max 25.0)
            feature_score = 0.0
            features_to_check = intent.feature_preferences or intent.soft_preferences
            if features_to_check:
                points_per_feat = 25.0 / len(features_to_check)
                for feat in features_to_check:
                    clean_f = feat.lower()
                    syns = match_synonyms(clean_f)

                    # Check attributes, specifications, and tags
                    found = False
                    # Check lightweight
                    if clean_f == "lightweight":
                        weight = p.specifications.get("weight_kg") or p.attributes.get("weight_kg")
                        if weight is not None and weight <= 1.5:
                            feature_score += points_per_feat
                            exact_matches.append(f"lightweight ({weight}kg)")
                            found = True
                        elif weight is None:
                            unknown_attributes.append("weight_kg")

                    # Check waterproof
                    elif clean_f == "waterproof":
                        wp = p.attributes.get("waterproof") or p.specifications.get("waterproof")
                        if wp is True:
                            feature_score += points_per_feat
                            exact_matches.append("waterproof")
                            found = True
                        elif wp is None:
                            unknown_attributes.append("waterproof")

                    # Check text matches in tags and descriptions
                    if not found:
                        prod_text = f"{p.product_name} {p.description} {' '.join(p.tags)}".lower()
                        if any(s in prod_text for s in syns):
                            feature_score += points_per_feat
                            exact_matches.append(feat)
                        else:
                            # Not found
                            pass
            else:
                feature_score = 20.0

            # 5. Factor 4: Budget Compliance & Value Fit (Max 20.0)
            budget_score = 0.0
            if max_inr is not None:
                if p_price_inr <= max_inr:
                    # Ideal sweet spot: between 50% and 95% of user's max budget
                    ratio = p_price_inr / max_inr
                    if 0.5 <= ratio <= 0.95:
                        budget_score = 20.0
                        exact_matches.append("budget_sweet_spot")
                    elif ratio < 0.5:
                        # Excellent savings
                        budget_score = 17.0
                        exact_matches.append("budget_friendly")
                    else:
                        # Treat a strict budget as a ceiling for relevant products, not a
                        # preference for spending less on unrelated subcategories.
                        matches_requested_subcategory = (
                            not intent.subcategory
                            or any(match.startswith("subcategory:") for match in exact_matches)
                        )
                        budget_score = (
                            20.0
                            if intent.is_budget_strict and matches_requested_subcategory
                            else 15.0
                        )
                else:
                    # Over budget (never rank as budget match when strict)
                    if intent.is_budget_strict:
                        budget_score = 0.0
                    else:
                        over_ratio = (p_price_inr - max_inr) / max_inr
                        budget_score = max(0.0, 10.0 - (over_ratio * 20.0))
            else:
                budget_score = 15.0

            # 6. Factor 5: Soft Preferences & Brand Fit (Max 10.0)
            preference_score = 0.0
            if intent.brand:
                if p.brand.lower() == intent.brand.lower():
                    preference_score += 3.0
                    exact_matches.append(f"brand:{p.brand}")
            else:
                preference_score += 3.0

            if intent.colour:
                if p.colours and any(intent.colour.lower() in c.lower() for c in p.colours):
                    preference_score += 3.0
                    exact_matches.append(f"colour:{intent.colour}")
                elif not p.colours:
                    unknown_attributes.append("colours")
            else:
                preference_score += 3.0

            product_evidence = " ".join(
                [p.product_name, p.description, *p.tags, *p.use_cases]
            ).casefold()
            if (
                "premium" in intent.soft_preferences
                and p.rating is not None
                and p.rating >= 4.3
                and (p.review_count or 0) >= 20
            ):
                preference_score += 2.0
                exact_matches.append(
                    f"premium quality signal: rating {p.rating:.1f}/5 "
                    f"from {p.review_count} reviews"
                )
            if intent.purchase_intent == "gift":
                if any(term in product_evidence for term in (
                    "gift", "gift set", "giftable", "gift box", "presentation box",
                )):
                    preference_score += 2.0
                    exact_matches.append("catalog listing identifies gift presentation")
                elif p.rating is not None and p.rating >= 4.5 and (p.review_count or 0) >= 20:
                    preference_score += 1.0
                    exact_matches.append(
                        f"strong catalog rating: {p.rating:.1f}/5 "
                        f"from {p.review_count} reviews"
                    )
                commodity_terms = (
                    "body wash", "hand soap", "body and face lotion",
                    "shampoo", "toothpaste", "deodorant",
                )
                if any(term in product_evidence for term in commodity_terms):
                    preference_score -= 2.0
                    partial_matches.append(
                        "everyday personal-care item is a weaker gift fit"
                    )
            preference_score = min(10.0, preference_score)

            # Total score
            total = category_score + use_case_score + feature_score + budget_score + preference_score
            normalized_total = min(100.0, max(0.0, round(total, 1)))

            # If hard constraint failed, total score is zeroed out for recommendation eligibility
            if not is_eligible:
                normalized_total = 0.0
            elif has_retrieval_scores:
                normalized_total = round(normalized_total * (0.75 + 0.25 * relevance), 1)

            fit_score = ProductFitScore(
                product_id=p.product_id,
                product_name=p.product_name,
                total_score=normalized_total,
                is_eligible=is_eligible,
                retrieval_score=retrieval_scores.get(p.product_id, 0.0),
                relevance=relevance,
                retrieval_sources=retrieval_sources.get(p.product_id, []),
                category_score=round(category_score, 1),
                use_case_score=round(use_case_score, 1),
                feature_score=round(feature_score, 1),
                budget_score=round(budget_score, 1),
                preference_score=round(preference_score, 1),
                exact_matches=exact_matches,
                partial_matches=partial_matches,
                unknown_attributes=unknown_attributes,
                violated_hard_constraints=violated_hard
            )

            scored_pairs.append((p, fit_score))

        # Preserve fit as the primary rank; retrieval relevance breaks close ties.
        scored_pairs.sort(
            key=lambda pair: (
                pair[1].is_eligible,
                pair[1].total_score,
                pair[1].retrieval_score,
                pair[0].rating or 0.0,
                pair[0].review_count or 0,
            ),
            reverse=True,
        )
        return scored_pairs
