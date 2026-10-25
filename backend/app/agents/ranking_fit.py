"""
Agent 6: Ranking and Fit Scoring Agent
Deterministic, mathematically sound multi-factor scoring system (0-100).
Enforces hard constraints before ranking so that a high score never compensates
for a broken rule. Distinguishes exact, partial, and unknown attributes.
"""

from typing import List, Tuple
from app.models.product import Product
from app.models.state import ExtractedIntent, ProductFitScore
from app.services.currency_service import normalize_price_to_usd
from app.services.catalog_service import canonicalize_category, match_synonyms


class RankingFitScoringAgent:
    """
    Ranks candidate products using a deterministic weighted matrix.
    Category (20%) + Use Case (25%) + Features (25%) + Budget (20%) + Preferences/Brand (10%) = 100%
    """

    def rank(
        self,
        candidates: List[Product],
        intent: ExtractedIntent
    ) -> List[Tuple[Product, ProductFitScore]]:
        scored_pairs: List[Tuple[Product, ProductFitScore]] = []

        max_usd = None
        if intent.budget_max is not None:
            max_usd = normalize_price_to_usd(intent.budget_max, intent.budget_currency)

        for p in candidates:
            p_price_usd = p.normalized_price_usd or normalize_price_to_usd(p.price, p.currency)
            exact_matches: List[str] = []
            partial_matches: List[str] = []
            unknown_attributes: List[str] = []
            violated_hard: List[str] = []

            # 1. Hard Constraint Verification
            is_eligible = True
            if intent.is_budget_strict and max_usd is not None and p_price_usd > max_usd:
                is_eligible = False
                violated_hard.append(f"Price (${p_price_usd:.2f}) exceeds budget (${max_usd:.2f})")

            for hk, hv in intent.hard_constraints.items():
                val = p.attributes.get(hk) or p.specifications.get(hk)
                if val is None:
                    unknown_attributes.append(hk)
                elif bool(val) != bool(hv):
                    is_eligible = False
                    violated_hard.append(f"{hk} != {hv}")
                else:
                    exact_matches.append(hk)

            # 2. Factor 1: Category Match (Max 20.0)
            category_score = 0.0
            if intent.category:
                if canonicalize_category(p.category) == canonicalize_category(intent.category):
                    category_score = 20.0
                    exact_matches.append(f"category:{p.category}")
                else:
                    category_score = 5.0
            else:
                category_score = 15.0  # open category query

            # 3. Factor 2: Use-Case Fit (Max 25.0)
            use_case_score = 0.0
            if intent.intended_use:
                clean_use = intent.intended_use.lower()
                prod_uses = [u.lower() for u in p.use_cases]
                if any(clean_use in u or u in clean_use for u in prod_uses):
                    use_case_score = 25.0
                    exact_matches.append(f"use_case:{clean_use}")
                elif any(clean_use in t.lower() for t in p.tags):
                    use_case_score = 18.0
                    partial_matches.append(f"tag:{clean_use}")
                else:
                    use_case_score = 5.0
            else:
                use_case_score = 20.0

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
            if max_usd is not None:
                if p_price_usd <= max_usd:
                    # Ideal sweet spot: between 50% and 95% of user's max budget
                    ratio = p_price_usd / max_usd
                    if 0.5 <= ratio <= 0.95:
                        budget_score = 20.0
                        exact_matches.append("budget_sweet_spot")
                    elif ratio < 0.5:
                        # Excellent savings
                        budget_score = 17.0
                        exact_matches.append("budget_friendly")
                    else:
                        # Very close to limit
                        budget_score = 15.0
                else:
                    # Over budget (never rank as budget match when strict)
                    if intent.is_budget_strict:
                        budget_score = 0.0
                    else:
                        over_ratio = (p_price_usd - max_usd) / max_usd
                        budget_score = max(0.0, 10.0 - (over_ratio * 20.0))
            else:
                budget_score = 15.0

            # 6. Factor 5: Soft Preferences & Brand Fit (Max 10.0)
            preference_score = 0.0
            if intent.brand:
                if p.brand.lower() == intent.brand.lower():
                    preference_score += 6.0
                    exact_matches.append(f"brand:{p.brand}")
            else:
                preference_score += 4.0

            if intent.colour:
                if p.colours and any(intent.colour.lower() in c.lower() for c in p.colours):
                    preference_score += 4.0
                    exact_matches.append(f"colour:{intent.colour}")
                elif not p.colours:
                    unknown_attributes.append("colours")
            else:
                preference_score += 4.0

            # Total score
            total = category_score + use_case_score + feature_score + budget_score + preference_score
            normalized_total = min(100.0, max(0.0, round(total, 1)))

            # If hard constraint failed, total score is zeroed out for recommendation eligibility
            if not is_eligible:
                normalized_total = 0.0

            fit_score = ProductFitScore(
                product_id=p.product_id,
                product_name=p.product_name,
                total_score=normalized_total,
                is_eligible=is_eligible,
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

        # Sort eligible products descending by score
        scored_pairs.sort(key=lambda pair: (pair[1].is_eligible, pair[1].total_score), reverse=True)
        return scored_pairs
