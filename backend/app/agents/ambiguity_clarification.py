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
from app.services.catalog_service import load_and_validate_catalog


AMBIGUOUS_PHRASES = [
    r"\bcheap\b", r"\bcheapest\b", r"\bgood\b", r"\bbest\b", r"\bsomething nice\b",
    r"\baffordable\b", r"\bdecent\b", r"\bdurable\b", r"\bhigh quality\b"
]

KNOWN_CONFLICT_PAIRS = [
    ({"vegan", "cruelty-free"}, {"leather", "suede", "wool", "down"}),
    ({"budget", "cheap"}, {"luxury", "flagship", "high-end", "premium"}),
    ({"waterproof", "submersible"}, {"open-mesh", "mesh sandals", "breathable canvas"}),
]


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

    def check_catalog_coverage(self, category: Optional[str]) -> bool:
        """Verifies if catalog contains products under the target category."""
        if not category:
            return True
        catalog = self._get_catalog()
        cat_lower = category.lower()
        return any(cat_lower in p.category.lower() or cat_lower in " ".join(p.tags).lower() for p in catalog)

    def evaluate(
        self,
        intent: ExtractedIntent,
        already_asked_questions: Optional[List[str]] = None,
        raw_user_message: str = ""
    ) -> ClarificationDecision:
        asked = already_asked_questions or []
        missing_critical: List[str] = []
        ambiguity_factors: List[str] = []

        # 1. Required-field completeness (0.0 to 1.0)
        completeness = 0.0
        if intent.category or intent.intended_use:
            completeness += 0.40
        else:
            missing_critical.append("category_or_use_case")

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
        coverage_feasible = self.check_catalog_coverage(intent.category)
        if not coverage_feasible:
            ambiguity_factors.append(f"No catalog coverage for requested category '{intent.category}'")

        # 6. Composite Confidence Score Calculation
        confidence = completeness
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
        elif "category_or_use_case" in missing_critical or (ambiguous_words and intent.budget_max is None):
            risk = "medium"
        else:
            risk = "low"

        # 8. Decision Mechanism
        needs_clarification = (
            confidence < self.confidence_threshold or
            bool(detected_conflicts) or
            bool(validity_issues) or
            "category_or_use_case" in missing_critical
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
            suggested_options = ["Under $50", "Under $100", "Under $250", "Flexible budget"]
            decision_reason = f"Clarification gated: constraint validity error ({validity_issues[0]})."
        elif "category_or_use_case" in missing_critical:
            question = "Could you tell me what type of product or activity you're shopping for (e.g., hiking gear, laptops, running shoes)?"
            suggested_options = ["Hiking & Outdoor", "Laptops & Tech", "Running Shoes", "Travel Bags"]
            decision_reason = "Clarification gated: missing critical category and intended use anchor."
        elif not coverage_feasible:
            question = f"We currently don't have catalog stock under '{intent.category}'. Would you like to explore related categories?"
            suggested_options = ["Footwear & Running", "Electronics & Laptops", "Travel & Backpacks"]
            decision_reason = f"Clarification gated: catalog coverage check failed for category '{intent.category}'."
        elif needs_clarification:
            if ambiguous_words and intent.budget_max is None:
                question = f"You mentioned looking for something '{ambiguous_words[0]}'. What target budget range should I focus on?"
                suggested_options = ["Under $50", "Under $100", "Under $200", "No budget limit"]
                decision_reason = f"Clarification gated: ambiguous phrase '{ambiguous_words[0]}' without quantified boundary (confidence: {confidence:.2f})."
            else:
                question = f"Do you have a target budget or specific features in mind for your {intent.category or 'purchase'}?"
                suggested_options = ["Under $100", "Under $250", "Top-rated only", "Flexible"]
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

