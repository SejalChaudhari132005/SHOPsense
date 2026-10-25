"""
Agent 2: Intent and Constraint Extraction Agent
Parses ingested queries into structured Pydantic ExtractedIntent models.
Distinguishes strict ceilings from flexible preferences, preserves negations,
and merges relevant context from previous conversation turns.
"""

from typing import Optional, List, Dict
from app.models.state import IngestedQuery, ExtractedIntent
from app.services.llm_service import extract_intent_with_llm


class IntentExtractionAgent:
    """
    Extracts structured commerce parameters using Groq LLM with deterministic validation.
    """

    def extract(
        self,
        ingested: IngestedQuery,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        previous_intent: Optional[ExtractedIntent] = None
    ) -> ExtractedIntent:
        if ingested.is_empty:
            return ExtractedIntent(
                shopping_intent="unknown",
                missing_or_uncertain=["empty_query"]
            )

        # 1. Structured extraction via centralized LLM service
        intent = extract_intent_with_llm(ingested.sanitized_message, conversation_history)

        # 2. Refinement & Context Merging
        # If this is a follow-up turn (e.g. "make it cheaper", "only black ones", "what about size 10")
        if previous_intent is not None:
            intent = self._merge_with_previous_context(intent, previous_intent, ingested.sanitized_message)

        # 2.5 Incorporate active tab / extracted product client_context
        ctx = ingested.client_context or {}
        extracted_prod = ctx.get("extractedProduct") or ctx.get("extracted_product") or {}

        ctx_cat = extracted_prod.get("category") or ctx.get("category")
        if not intent.category and ctx_cat:
            intent.category = ctx_cat

        ctx_brand = extracted_prod.get("brand") or ctx.get("brand")
        if not intent.brand and ctx_brand:
            intent.brand = ctx_brand

        ctx_price = extracted_prod.get("price") or ctx.get("price")
        if intent.budget_max is None and ctx_price is not None:
            try:
                if isinstance(ctx_price, (int, float)) and ctx_price > 0:
                    intent.budget_max = float(ctx_price)
                elif isinstance(ctx_price, str):
                    import re
                    clean_p = re.sub(r"[^\d.]", "", ctx_price)
                    if clean_p:
                        intent.budget_max = float(clean_p)
                ctx_curr = extracted_prod.get("currency") or ctx.get("currency")
                if ctx_curr:
                    intent.budget_currency = str(ctx_curr).upper()
            except (ValueError, TypeError):
                pass

        # 3. Validation & Uncertainty Detection
        missing = []
        if not intent.category and not intent.intended_use:
            missing.append("category_or_use_case")
        if intent.budget_max is None:
            missing.append("budget")

        intent.missing_or_uncertain = missing
        return intent

    def _merge_with_previous_context(
        self,
        current: ExtractedIntent,
        previous: ExtractedIntent,
        raw_text: str
    ) -> ExtractedIntent:
        """
        Preserves previously established constraints unless explicitly overridden by the user.
        """
        lower = raw_text.lower()

        # If user is changing topic completely (e.g. "now find a travel bag")
        if any(topic_change in lower for topic_change in ["now find", "instead show me", "switch to", "different item"]):
            return current  # Don't leak old category or specific constraints

        # If user specified a different category or subcategory, treat as a new topic
        if current.category and previous.category:
            from app.services.catalog_service import canonicalize_category
            canon_curr = canonicalize_category(current.category)
            canon_prev = canonicalize_category(previous.category)
            if canon_curr != canon_prev or (current.subcategory and previous.subcategory and current.subcategory != previous.subcategory):
                return current  # New product category: don't leak old constraints

        # Preserve Category & Subcategory if not re-specified
        if not current.category and previous.category:
            current.category = previous.category
        if not current.subcategory and previous.subcategory:
            current.subcategory = previous.subcategory

        # Preserve Intended Use & Persona
        if not current.intended_use and previous.intended_use:
            current.intended_use = previous.intended_use
        if not current.recipient and previous.recipient:
            current.recipient = previous.recipient
        if not current.occasion and previous.occasion:
            current.occasion = previous.occasion

        # Handle "make it cheaper" refinement
        if current.budget_max is None and any(
            phrase in lower for phrase in ["cheaper", "lower budget", "lower my budget", "less expensive", "reduce budget"]
        ):
            if previous.budget_max:
                # Lower budget ceiling by 20%
                current.budget_max = round(previous.budget_max * 0.8, 2)
                current.budget_currency = previous.budget_currency
                current.is_budget_strict = True
                current.is_refinement = True
        elif current.budget_max is None and previous.budget_max is not None:
            # Retain previous budget
            current.budget_max = previous.budget_max
            current.budget_currency = previous.budget_currency
            current.is_budget_strict = previous.is_budget_strict
        elif current.budget_max is not None and previous.budget_max is not None and current.budget_max != previous.budget_max:
            current.is_refinement = True

        # Merge soft preferences (deduplicated)
        merged_prefs = list(dict.fromkeys(previous.soft_preferences + current.soft_preferences))
        current.soft_preferences = merged_prefs

        # Retain previous size/colour if not overridden
        if not current.size and previous.size and "size" not in lower:
            current.size = previous.size
        if not current.colour and previous.colour and "color" not in lower and "colour" not in lower:
            current.colour = previous.colour

        # Merge hard constraints
        merged_hard = {**previous.hard_constraints, **current.hard_constraints}
        current.hard_constraints = merged_hard

        # Merge exclusions
        current.exclusions = list(dict.fromkeys(previous.exclusions + current.exclusions))

        return current
