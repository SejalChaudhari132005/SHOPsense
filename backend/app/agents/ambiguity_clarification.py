"""
Agent 3: Ambiguity and Clarification Agent (Confidence-Gated Autonomy)
Evaluates multi-signal search readiness:
- Required-field completeness
- Constraint validity
- Ambiguous phrases (e.g. 'cheap', 'best', 'good' without parameters)
- Conflicting constraints (e.g. 'vegan' vs 'leather', '$25' vs 'high-end laptop')
- Catalog coverage & retrieval feasibility
- Risk of violating an important constraint
Records transparent decision_reason for proceeding autonomously or asking clarification.
"""

import re
from typing import List, Optional, Dict, Any, Tuple
from app.models.state import ExtractedIntent, ClarificationDecision
from app.models.product import Product
from app.services.catalog_service import canonicalize_category, load_and_validate_catalog


AMBIGUOUS_PHRASES = [
    r"\bcheap\b", r"\bcheapest\b", r"\bgood\b", r"\bbest\b", r"\bsomething nice\b",
    r"\baffordable\b", r"\bdecent\b", r"\bdurable\b", r"\bhigh quality\b"
]

KNOWN_CONFLICT_PAIRS = [
    ({"vegan", "cruelty-free"}, {"leather", "suede", "wool", "down"}),
    ({"budget", "cheap"}, {"luxury", "flagship", "high-end", "premium"}),
    ({"waterproof", "submersible"}, {"open-mesh", "mesh sandals", "breathable canvas"}),
]

CATEGORY_REQUIRED_ATTRIBUTES = {
    "footwear": ("size",),
    "clothing": ("size",),
}


class AmbiguityClarificationAgent:
    """
    Multi-Signal Confidence-Gated Autonomy Controller.
    Decides deterministically whether to proceed autonomously or ask a targeted
    clarification question based on structural signals, not just LLM self-reporting.
    """

    def __init__(self, confidence_threshold: float = 0.55, catalog: Optional[List[Product]] = None):
        self.confidence_threshold = confidence_threshold
        self._catalog = catalog

    def _get_catalog(self) -> List[Product]:
        if self._catalog is None:
            self._catalog = load_and_validate_catalog()
        return self._catalog

    def detect_ambiguous_phrases(self, text: str) -> List[str]:
        """Detects subjective unquantified descriptors."""
        found = []
        lower = text.lower()
        for pattern in AMBIGUOUS_PHRASES:
            if re.search(pattern, lower):
                found.append(re.sub(r"\\b", "", pattern))
        return found

    def detect_conflicts(self, intent: ExtractedIntent, raw_user_message: str = "") -> List[str]:
        """Detects mutually contradictory constraint combinations."""
        conflicts = []
        raw_tokens = set(re.findall(r"\b[a-zA-Z-]+\b", raw_user_message.lower())) if raw_user_message else set()
        all_terms = set(
            [str(t).lower() for t in intent.soft_preferences] +
            [str(t).lower() for t in intent.feature_preferences] +
            [str(t).lower() for t in intent.exclusions] +
            [str(k).lower() for k in intent.hard_constraints.keys()] +
            [str(v).lower() for v in intent.hard_constraints.values()]
        ) | raw_tokens
        if intent.category:
            all_terms.add(intent.category.lower())
        if intent.intended_use:
            all_terms.add(intent.intended_use.lower())
        mat = getattr(intent, "material", None)
        if mat:
            all_terms.add(str(mat).lower())

        # Conflict 1: Vegan vs Animal Material
        is_vegan = any("vegan" in t or "cruelty-free" in t for t in all_terms)
        has_animal = any("leather" in t or "suede" in t or "wool" in t for t in all_terms)
        if is_vegan and has_animal:
            conflicts.append("Contradictory material requirements: 'vegan' combined with animal materials ('leather/suede')")

        # Conflict 2: Weight contradiction (ultralight vs heavy-duty)
        has_ultralight = any("ultralight" in t or "featherweight" in t for t in all_terms)
        has_heavy = any("heavy-duty" in t or "maximum weight" in t for t in all_terms)
        if has_ultralight and has_heavy:
            conflicts.append("Contradictory design requirements: 'ultralight' combined with 'heavy-duty' construction")

        # Conflict 3: Conflicting waterproof and open-mesh
        if (intent.hard_constraints.get("waterproof") or "waterproof" in all_terms) and any("open mesh" in t or "sandal" in t for t in all_terms):
            conflicts.append("Contradictory feature requirements: fully waterproof combined with open-mesh design")

        return conflicts

    def available_categories(self) -> List[str]:
        """Return the catalog's distinct product categories."""
        return sorted({product.category for product in self._get_catalog()})

    @staticmethod
    def _category_label(category: str) -> str:
        labels = {
            "beauty_personal_care": "Beauty & Personal Care",
            "fashion_accessories": "Fashion Accessories",
            "fitness_outdoor": "Fitness & Outdoor",
            "home_kitchen": "Home & Kitchen",
            "bags_accessories": "Bags & Accessories",
        }
        return labels.get(category, category.replace("_", " ").title())

    def check_catalog_coverage(
        self,
        category: Optional[str],
        subcategory: Optional[str] = None,
    ) -> bool:
        """Verify that the catalog supports the requested category and product type."""
        if not category:
            return True
        catalog = self._get_catalog()
        canonical_category = canonicalize_category(category)
        category_products = [
            product for product in catalog
            if canonicalize_category(product.category) == canonical_category
        ]
        if not category_products:
            return False
        if not subcategory:
            return True

        requested_terms = re.findall(r"[a-z0-9]+", subcategory.lower())
        if not requested_terms:
            return True
        requested_terms = [
            term[:-1] if len(term) > 3 and term.endswith("s") else term
            for term in requested_terms
        ]
        for product in category_products:
            catalog_text = " ".join([
                product.subcategory or "",
                product.product_name,
                product.description,
                *product.tags,
                *product.use_cases,
            ]).lower()
            catalog_terms = set(re.findall(r"[a-z0-9]+", catalog_text))
            catalog_terms.update(
                term[:-1] for term in list(catalog_terms)
                if len(term) > 3 and term.endswith("s")
            )
            if all(term in catalog_terms for term in requested_terms):
                return True
        return False

    def evaluate(
        self,
        intent: ExtractedIntent,
        already_asked_questions: Optional[List[str]] = None,
        raw_user_message: str = ""
    ) -> ClarificationDecision:
        asked = already_asked_questions or []
        if intent.shopping_intent == "category_discovery":
            return ClarificationDecision(
                needs_clarification=False,
                completeness_score=1.0,
                confidence_score=1.0,
                decision_reason="Category discovery is answerable from catalog metadata.",
                reason="Category discovery is answerable from catalog metadata.",
            )
        missing_critical: List[str] = []
        ambiguity_factors: List[str] = []

        # 1. Required-field completeness (0.0 to 1.0)
        completeness = 0.0
        missing_category_attributes: List[str] = []
        page_analysis_anchor = bool(intent.page_analysis_requested and intent.page_product)
        named_comparison = (
            intent.purchase_intent == "comparison"
            and len(intent.comparison_product_ids) >= 2
        )
        has_search_anchor = bool(
            intent.category
            or intent.category_hint
            or page_analysis_anchor
            or named_comparison
            or intent.intended_use
            or intent.health_considerations
        )
        if has_search_anchor:
            completeness += 0.40
        else:
            missing_critical.append("category_or_use_case")

        if named_comparison:
            completeness += 0.25

        if page_analysis_anchor:
            completeness += 0.25

        category = canonicalize_category(intent.category) if intent.category else None
        if intent.purchase_intent == "gift" and category in CATEGORY_REQUIRED_ATTRIBUTES:
            if "size" in CATEGORY_REQUIRED_ATTRIBUTES[category] and not intent.size:
                missing_category_attributes.append("recipient_size")
                missing_critical.append("recipient_size")

        if intent.budget_max is not None:
            completeness += 0.25

        if intent.soft_preferences or intent.feature_preferences or intent.hard_constraints:
            completeness += 0.20

        if intent.size or intent.colour or intent.brand or intent.recipient:
            completeness += 0.15

        # 2. Constraint validity
        validity_issues = []
        if intent.budget_max is not None and intent.budget_max <= 0:
            validity_issues.append("Non-positive budget boundary")

        # 3. Ambiguous subjective phrases without numerical boundaries
        ambiguous_words = self.detect_ambiguous_phrases(raw_user_message or intent.intended_use or "")
        if ambiguous_words and intent.budget_max is None:
            for w in ambiguous_words:
                ambiguity_factors.append(f"Subjective term '{w}' without explicit numerical budget")

        # 4. Conflicting constraints
        detected_conflicts = self.detect_conflicts(intent, raw_user_message)
        for c in detected_conflicts:
            ambiguity_factors.append(c)

        # 5. Catalog coverage & retrieval feasibility
        coverage_feasible = self.check_catalog_coverage(
            intent.category,
            intent.subcategory if intent.subcategory_is_explicit else None,
        )
        if not coverage_feasible:
            unsupported_item = intent.subcategory or intent.category
            ambiguity_factors.append(f"No catalog coverage for requested item '{unsupported_item}'")

        # 6. Composite Confidence Score Calculation
        confidence = completeness
        if missing_category_attributes:
            confidence -= 0.15
        if ambiguous_words and intent.budget_max is None:
            confidence -= 0.15
        if detected_conflicts:
            confidence -= 0.35
        if validity_issues:
            confidence -= 0.40
        if not coverage_feasible:
            confidence -= 0.20

        confidence = max(0.0, min(1.0, confidence))

        # 7. Risk Assessment
        if detected_conflicts or validity_issues:
            risk = "high"
        elif (
            "category_or_use_case" in missing_critical
            or missing_category_attributes
            or (ambiguous_words and intent.budget_max is None)
        ):
            risk = "medium"
        else:
            risk = "low"

        # 8. Decision Mechanism
        needs_clarification = (
            confidence < self.confidence_threshold or
            bool(detected_conflicts) or
            bool(validity_issues) or
            "category_or_use_case" in missing_critical or
            bool(missing_category_attributes)
        )

        question = None
        suggested_options = []
        decision_reason = ""

        if detected_conflicts:
            question = f"I noticed potentially conflicting requirements: {detected_conflicts[0]}. Could you clarify your preference?"
            suggested_options = ["Prioritize vegan materials", "Allow leather/suede", "Adjust budget limit"]
            decision_reason = f"Clarification gated: high risk of conflicting constraints ({detected_conflicts[0]})."
        elif validity_issues:
            question = "It looks like the budget specified is zero or negative. What target price range would you prefer?"
            suggested_options = ["Under ₹5,000", "Under ₹10,000", "Under ₹25,000", "Flexible budget"]
            decision_reason = f"Clarification gated: constraint validity error ({validity_issues[0]})."
        elif not coverage_feasible:
            categories = self.available_categories()
            category_labels = [category.replace("_", " ").title() for category in categories]
            category_labels = [
                label.replace("Fitness Outdoor", "Fitness & Outdoor")
                .replace("Home Kitchen", "Home & Kitchen")
                .replace("Bags Accessories", "Bags & Accessories")
                for label in category_labels
            ]
            unsupported_item = intent.subcategory or intent.category or "that product"
            question = (
                f"ShopSense doesn't currently offer {unsupported_item}. "
                f"We work with these product categories: {', '.join(category_labels)}. "
                "What would you like to explore?"
            )
            suggested_options = category_labels
            decision_reason = f"Clarification gated: no catalog coverage for requested item '{unsupported_item}'."
        elif "category_or_use_case" in missing_critical:
            categories = [
                self._category_label(category)
                for category in self.available_categories()
            ]
            if intent.purchase_intent == "gift":
                question = (
                    "What type of product would you like me to explore for the gift? "
                    f"Available catalog categories: {', '.join(categories)}."
                )
                suggested_options = categories
                decision_reason = (
                    "Clarification gated: gift intent has no user-selected category; "
                    "offering only categories present in the catalog."
                )
            else:
                question = (
                    "Could you tell me what type of product or activity you're shopping "
                    f"for? Available catalog categories: {', '.join(categories)}."
                )
                suggested_options = categories
                decision_reason = "Clarification gated: missing critical category and intended use anchor."
        elif missing_category_attributes:
            question = (
                "What size does the recipient wear for this gift? "
                "I can also switch to size-free gift accessories."
            )
            suggested_options = ["Show size-free gift accessories"]
            decision_reason = (
                "Clarification gated: the gift category requires recipient sizing "
                "to avoid unsuitable recommendations."
            )
        elif needs_clarification:
            if ambiguous_words and intent.budget_max is None:
                question = f"You mentioned looking for something '{ambiguous_words[0]}'. What target budget range should I focus on?"
                suggested_options = ["Under ₹5,000", "Under ₹10,000", "Under ₹20,000", "No budget limit"]
                decision_reason = f"Clarification gated: ambiguous phrase '{ambiguous_words[0]}' without quantified boundary (confidence: {confidence:.2f})."
            else:
                question = f"Do you have a target budget or specific features in mind for your {intent.category or 'purchase'}?"
                suggested_options = ["Under ₹10,000", "Under ₹25,000", "Top-rated only", "Flexible"]
                decision_reason = f"Clarification gated: confidence ({confidence:.2f}) below threshold ({self.confidence_threshold:.2f})."
        else:
            decision_reason = (
                f"Proceeding autonomously: confidence ({confidence:.2f}) meets threshold ({self.confidence_threshold:.2f}) "
                f"with valid constraints, {risk} risk, and verified catalog feasibility."
            )

        # Anti-badgering guard: do not repeat exact question
        if question and question in asked:
            needs_clarification = False
            question = None
            decision_reason = f"Clarification already attempted in previous turn; proceeding autonomously (anti-badgering guard)."

        return ClarificationDecision(
            needs_clarification=needs_clarification,
            completeness_score=round(completeness, 2),
            confidence_score=round(confidence, 2),
            clarification_question=question,
            suggested_options=suggested_options,
            missing_critical_fields=missing_critical,
            decision_reason=decision_reason,
            risk_assessment=risk,
            ambiguity_factors=ambiguity_factors,
            catalog_coverage_feasible=coverage_feasible,
            reason=decision_reason
        )
