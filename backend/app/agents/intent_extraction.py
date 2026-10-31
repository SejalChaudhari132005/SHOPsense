"""
Agent 2: Intent and Constraint Extraction Agent
Parses ingested queries into structured Pydantic ExtractedIntent models.
Distinguishes strict ceilings from flexible preferences, preserves negations,
and merges relevant context from previous conversation turns.
"""

import re
import math
from typing import Optional, List, Dict
from app.models.state import IngestedQuery, ExtractedIntent, PageProductEvidence
from app.services.llm_service import (
    deterministic_extract_intent,
    extract_intent_with_llm,
    normalize_intent_contract,
)
from app.services.catalog_service import (
    canonicalize_category,
    find_catalog_product_by_name,
)
from app.services.currency_service import convert_currency


_EXPLICIT_CATEGORY_PHRASES = {
    "footwear": {
        "shoe", "shoes", "sneaker", "sneakers", "boot", "boots", "footwear",
        "sandals", "slippers", "trainers", "loafers",
    },
    "electronics": {
        "electronics", "electronic device", "laptop", "laptops", "notebook",
        "notebooks", "headphone", "headphones", "earbud", "earbuds", "charger",
        "chargers", "monitor", "monitors", "tablet", "tablets", "phone", "phones",
        "camera", "cameras",
    },
    "clothing": {
        "clothing", "clothes", "apparel", "shirt", "shirts", "pants", "jacket",
        "jackets", "dress", "dresses", "hoodie", "hoodies",
    },
    "travel_accessories": {
        "travel accessories", "luggage", "adapter", "adapters", "travel pillow", "packing cubes",
        "passport holder", "luggage strap",
    },
    "fitness_outdoor": {
        "fitness equipment", "outdoor equipment", "camping tent", "tent", "tents",
        "trekking pole", "trekking poles", "hiking pole", "hiking poles", "yoga mat",
        "yoga mats", "dumbbell", "dumbbells", "cricket helmet", "sports accessories",
    },
    "home_kitchen": {
        "kitchen", "cookware", "blender", "blenders", "coffee maker", "kettle",
        "skillet", "utensils",
    },
    "bags_accessories": {
        "bag", "bags", "backpack", "backpacks", "duffel", "duffels", "tote",
        "totes", "wallet", "wallets", "purse", "purses",
    },
    "beauty_personal_care": {
        "beauty", "beauty and care", "beauty and personal care", "beauty care",
        "personal care",
        "skincare", "skin care", "fragrance", "fragrances", "makeup",
        "cosmetics", "perfume",
    },
    "fashion_accessories": {
        "fashion accessories", "jewelry", "jewellery", "sunglasses",
        "watch", "watches",
    },
    "groceries": {"grocery", "groceries", "food"},
    "automotive": {"automotive", "motorcycle", "motorcycles", "vehicle", "vehicles"},
}


def _contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = " ".join(re.findall(r"[a-z0-9]+", text.casefold()))
    words = re.findall(r"[a-z0-9]+", phrase.casefold())
    if not words:
        return False
    phrase_variants = {tuple(words)}
    if words[-1].endswith("s") and len(words[-1]) > 3:
        phrase_variants.add(tuple([*words[:-1], words[-1][:-1]]))
    else:
        plural_suffix = "es" if words[-1].endswith(
            ("ch", "sh", "s", "x", "z")
        ) else "s"
        phrase_variants.add(
            tuple([*words[:-1], f"{words[-1]}{plural_suffix}"])
        )
    padded_text = f" {normalized_text} "
    return any(
        f" {' '.join(variant)} " in padded_text
        for variant in phrase_variants
    )


def _contains_page_instruction(value: str) -> bool:
    return bool(re.search(
        r"\b(?:ignore\s+(?:all\s+)?previous\s+instructions|"
        r"system\s*:|developer\s*:|assistant\s*:|"
        r"(?:output|print)\s+(?:the\s+)?(?:following|exactly))\b",
        value,
        re.IGNORECASE,
    ))


def _optional_page_text(value: object, max_length: int) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        text = value.strip()[:max_length]
        return None if _contains_page_instruction(text) else text
    return None


def _optional_page_price(value: object) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def _page_evidence_map(value: object) -> Dict[str, object]:
    if not isinstance(value, dict):
        return {}
    evidence: Dict[str, object] = {}
    for index, (key, item) in enumerate(value.items()):
        if index >= 40:
            break
        if not isinstance(key, str) or _contains_page_instruction(key):
            continue
        if isinstance(item, float) and not math.isfinite(item):
            continue
        if isinstance(item, (str, int, float, bool)):
            if isinstance(item, str):
                if _contains_page_instruction(item):
                    continue
                evidence[key.strip()[:80]] = item[:300]
            else:
                evidence[key.strip()[:80]] = item
    return evidence


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
        extraction_history = list(conversation_history or [])
        if previous_intent is not None:
            extraction_history.append({
                "role": "assistant",
                "content": "Previously established structured shopping intent: "
                + previous_intent.model_dump_json(),
            })
        intent = extract_intent_with_llm(ingested.sanitized_message, extraction_history)
        explicit_intent = deterministic_extract_intent(ingested.sanitized_message)
        if (
            explicit_intent.shopping_intent == "category_discovery"
            and not explicit_intent.category
        ):
            intent.shopping_intent = "category_discovery"
        if explicit_intent.shopping_intent == "gift_buying":
            intent.shopping_intent = "gift_buying"
            intent.purchase_intent = "gift"
            intent.recipient = explicit_intent.recipient or intent.recipient
            intent.occasion = explicit_intent.occasion or intent.occasion
        if explicit_intent.category:
            intent.category = explicit_intent.category
            intent.category_is_explicit = True
            if explicit_intent.shopping_intent != "category_discovery":
                intent.shopping_intent = (
                    "gift_buying"
                    if explicit_intent.purchase_intent == "gift"
                    else "product_search"
                )
        if explicit_intent.subcategory:
            intent.subcategory = explicit_intent.subcategory
            intent.subcategory_is_explicit = True
        if explicit_intent.budget_max is not None or explicit_intent.budget_min is not None:
            intent.budget_max = explicit_intent.budget_max
            intent.budget_min = explicit_intent.budget_min
            intent.budget_currency = explicit_intent.budget_currency
            intent.is_budget_strict = explicit_intent.is_budget_strict
        if explicit_intent.budget_unlimited:
            intent.budget_unlimited = True
            intent.budget_min = None
            intent.budget_max = None
        if explicit_intent.shopping_intent == "comparison":
            intent.shopping_intent = "comparison"
            intent.purchase_intent = "comparison"
            intent.comparison_product_ids = explicit_intent.comparison_product_ids
            if intent.comparison_product_ids:
                intent.product_query = None
        intent.soft_preferences = list(dict.fromkeys(
            intent.soft_preferences + explicit_intent.soft_preferences
        ))
        intent.feature_preferences = list(dict.fromkeys(
            intent.feature_preferences + explicit_intent.feature_preferences
        ))
        intent = normalize_intent_contract(intent, ingested.sanitized_message)

        matched_product = find_catalog_product_by_name(ingested.sanitized_message)
        if matched_product and intent.purchase_intent != "comparison":
            intent.category = matched_product.category
            intent.subcategory = matched_product.subcategory
            intent.product_query = matched_product.product_name
            intent.category_is_explicit = True
            intent.subcategory_is_explicit = True
        else:
            category = intent.category
            intent.category_is_explicit = bool(
                category
                and any(
                    _contains_phrase(ingested.sanitized_message, phrase)
                    for phrase in _EXPLICIT_CATEGORY_PHRASES.get(category, {category})
                )
            )
            if category and not intent.category_is_explicit:
                intent.category_hint = intent.category_hint or category
                intent.category = None
                intent.subcategory = None
            subcategory = intent.subcategory
            intent.subcategory_is_explicit = bool(
                subcategory
                and (
                    _contains_phrase(
                        ingested.sanitized_message,
                        subcategory.replace("_", " ").replace("-", " "),
                    )
                    or (
                        subcategory == "audio"
                        and any(
                            _contains_phrase(ingested.sanitized_message, term)
                            for term in ("headphones", "earbuds", "audio")
                        )
                    )
                    or (
                        subcategory in {"mens-watches", "womens-watches"}
                        and _contains_phrase(
                            ingested.sanitized_message, "watch"
                        )
                    )
                    or (
                        subcategory == "womens-dresses"
                        and any(
                            _contains_phrase(ingested.sanitized_message, term)
                            for term in ("dress", "dresses", "gown", "frock")
                        )
                    )
                )
            )
            query_text = ingested.sanitized_message.casefold()
            mentions_hiking = re.search(
                r"\b(?:hike|hikes|hiking|hiker|hikers)\b",
                query_text,
            )
            mentions_knee_discomfort = re.search(
                r"\b(?:knee|knees|joint|joints)\b.{0,40}"
                r"\b(?:pain|strain|ache|hurt|sore|discomfort)\b",
                query_text,
            )
            if mentions_hiking and mentions_knee_discomfort:
                intent.intended_use = intent.intended_use or "hiking"
                if "joint-friendly" not in intent.soft_preferences:
                    intent.soft_preferences.append("joint-friendly")

        size_free_choice = bool(
            previous_intent is not None
            and any(
                phrase in ingested.sanitized_message.casefold()
                for phrase in ("size-free", "size free", "without sizing")
            )
        )
        if size_free_choice:
            intent.exclude_sized_items = True
            intent.category_hint = intent.category or intent.category_hint
            if not intent.intended_use and previous_intent:
                intent.intended_use = previous_intent.intended_use
            intent.category_hint = category
            intent.category = None
            intent.subcategory = None
            intent.product_query = None
            intent.category_is_explicit = False
            intent.subcategory_is_explicit = False

        # 2. Refinement & Context Merging
        # If this is a follow-up turn (e.g. "make it cheaper", "only black ones", "what about size 10")
        if previous_intent is not None:
            if size_free_choice:
                intent.purchase_intent = previous_intent.purchase_intent
                intent.shopping_intent = previous_intent.shopping_intent
                intent.recipient = intent.recipient or previous_intent.recipient
                intent.occasion = intent.occasion or previous_intent.occasion
                if not intent.budget_unlimited and intent.budget_max is None:
                    intent.budget_min = previous_intent.budget_min
                    intent.budget_max = previous_intent.budget_max
                    intent.budget_currency = previous_intent.budget_currency
                    intent.is_budget_strict = previous_intent.is_budget_strict
            else:
                intent = self._merge_with_previous_context(
                    intent, previous_intent, ingested.sanitized_message
                )

        # 2.5 Incorporate active tab / extracted product client_context
        ctx = ingested.client_context or {}
        extracted_prod = ctx.get("extractedProduct") or ctx.get("extracted_product") or {}
        if not isinstance(extracted_prod, dict):
            extracted_prod = {}

        ctx_cat = _optional_page_text(
            extracted_prod.get("category") or ctx.get("category"),
            120,
        )
        if not intent.category and ctx_cat:
            intent.category = ctx_cat

        query_text = ingested.sanitized_message
        intent.page_analysis_requested = bool(
            re.search(
                r"\b(?:analy[sz]e|evaluate|review|assess|trade[\s-]?offs|"
                r"key specifications|specs|value for money|what do you think of)\b",
                query_text,
                re.IGNORECASE,
            )
        )
        if isinstance(extracted_prod, dict) and extracted_prod.get("product_name"):
            intent.page_product = PageProductEvidence(
                product_name=(
                    _optional_page_text(extracted_prod["product_name"], 240)
                    or "Product on active page"
                ),
                brand=_optional_page_text(extracted_prod.get("brand"), 120),
                price=_optional_page_price(extracted_prod.get("price")),
                currency=_optional_page_text(extracted_prod.get("currency"), 8),
                category=_optional_page_text(extracted_prod.get("category"), 120),
                source_store=_optional_page_text(extracted_prod.get("source_store"), 80),
                product_url=_optional_page_text(extracted_prod.get("product_url"), 500),
                specifications=_page_evidence_map(extracted_prod.get("specifications")),
                attributes=_page_evidence_map(extracted_prod.get("attributes")),
                availability=_optional_page_text(extracted_prod.get("availability"), 120),
            )

        if intent.page_product:
            page_category = _optional_page_text(intent.page_product.category, 120)
            if intent.page_analysis_requested and page_category:
                intent.category = page_category
                intent.category_is_explicit = True
            elif not intent.category and page_category:
                intent.category = page_category
            if (
                not intent.page_analysis_requested
                and not intent.brand
                and intent.page_product.brand
            ):
                intent.brand = intent.page_product.brand
            if (
                not intent.page_analysis_requested
                and intent.budget_max is None
                and intent.page_product.price is not None
            ):
                page_currency = (intent.page_product.currency or "INR").upper()
                intent.budget_max = convert_currency(
                    intent.page_product.price, page_currency, "INR"
                )
                intent.budget_currency = "INR"
            if intent.page_analysis_requested or not intent.product_query:
                intent.product_query = intent.page_product.product_name

        if intent.budget_unlimited:
            intent.budget_min = None
            intent.budget_max = None
            intent.explicit_constraints = [
                constraint
                for constraint in intent.explicit_constraints
                if constraint.name.casefold() != "price"
            ]

        # 3. Validation & Uncertainty Detection
        missing = []
        if (
            intent.shopping_intent != "category_discovery"
            and not intent.category
            and not (
                intent.category_hint
                or intent.intended_use
                or intent.product_query
                or intent.feature_preferences
                or intent.soft_preferences
                or intent.health_considerations
            )
        ):
            missing.append("category_or_use_case")
        if intent.budget_max is None:
            missing.append("budget")

        intent.missing_or_uncertain = missing
        return normalize_intent_contract(intent, ingested.sanitized_message)

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

        is_refinement = current.shopping_intent == "refinement" or any(
            phrase in lower
            for phrase in (
                "no budget limit", "without any budget restriction",
                "remove the budget", "make it cheaper", "only black",
                "only show", "size ", "color ", "colour ",
            )
        )
        new_gift_request = (
            current.purchase_intent == "gift"
            and not current.category
            and any(term in lower for term in ("gift", "present"))
            and bool(re.search(
                r"\b(?:suggest|find|recommend|looking for|i need|i want|"
                r"what are some|some good options|another)\b",
                lower,
            ))
        )
        if (
            new_gift_request
            or re.search(r"\b(?:new request|start over|new search)\b", lower)
        ) and not is_refinement:
            return current

        category_changed = bool(
            current.category
            and previous.category
            and canonicalize_category(current.category)
            != canonicalize_category(previous.category)
        )
        same_category = not category_changed
        if category_changed:
            current.subcategory = None
            current.product_query = None

        if current.category and previous.category and same_category:
            if not current.category_is_explicit:
                current.category_is_explicit = previous.category_is_explicit
            if (
                current.subcategory == previous.subcategory
                and not current.subcategory_is_explicit
            ):
                current.subcategory_is_explicit = previous.subcategory_is_explicit

        # Preserve Category & Subcategory if not re-specified
        if not current.category and previous.category and same_category and not new_gift_request:
            current.category = previous.category
            current.category_is_explicit = previous.category_is_explicit
        if not current.category_hint and previous.category_hint and same_category:
            current.category_hint = previous.category_hint
        current.exclude_sized_items = (
            current.exclude_sized_items or previous.exclude_sized_items
        )
        if not current.subcategory and previous.subcategory and same_category:
            current.subcategory = previous.subcategory
            current.subcategory_is_explicit = previous.subcategory_is_explicit
        if not current.product_query and previous.product_query and same_category:
            current.product_query = previous.product_query
        if not current.comparison_product_ids and previous.comparison_product_ids and same_category:
            current.comparison_product_ids = list(previous.comparison_product_ids)

        # Preserve Intended Use & Persona
        if not current.intended_use and previous.intended_use:
            current.intended_use = previous.intended_use
        if not current.health_considerations and previous.health_considerations:
            current.health_considerations = list(previous.health_considerations)
        if not current.recipient and previous.recipient:
            current.recipient = previous.recipient
        if not current.occasion and previous.occasion:
            current.occasion = previous.occasion

        if (
            current.purchase_intent == "self_use"
            and previous.purchase_intent in {"gift", "replacement"}
            and not any(term in lower for term in ["gift", "present", "replace", "replacement"])
        ):
            current.purchase_intent = previous.purchase_intent
        if not current.deadline and previous.deadline:
            current.deadline = previous.deadline
        if not current.skill_level and previous.skill_level:
            current.skill_level = previous.skill_level
        if same_category:
            current.health_considerations = list(dict.fromkeys(
                previous.health_considerations + current.health_considerations
            ))
            current.implicit_constraints = list({
                (item.value.casefold(), item.evidence.casefold()): item
                for item in previous.implicit_constraints + current.implicit_constraints
            }.values())

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
        elif current.budget_unlimited:
            current.budget_min = None
            current.budget_max = None
            current.explicit_constraints = [
                constraint
                for constraint in current.explicit_constraints
                if constraint.name.casefold() != "price"
            ]
        elif current.budget_max is None and current.budget_min is None and previous.budget_max is not None:
            # Retain previous budget
            current.budget_max = previous.budget_max
            current.budget_currency = previous.budget_currency
            current.is_budget_strict = previous.is_budget_strict
        elif current.budget_max is not None and previous.budget_max is not None and current.budget_max != previous.budget_max:
            current.is_refinement = True

        # Merge soft preferences (deduplicated)
        merged_prefs = list(dict.fromkeys(
            (previous.soft_preferences if same_category else [])
            + current.soft_preferences
        ))
        current.soft_preferences = merged_prefs
        current.feature_preferences = list(dict.fromkeys(
            (previous.feature_preferences if same_category else [])
            + current.feature_preferences
        ))

        # Retain previous size/colour if not overridden
        if same_category and not current.size and previous.size and "size" not in lower:
            current.size = previous.size
        if same_category and not current.colour and previous.colour and "color" not in lower and "colour" not in lower:
            current.colour = previous.colour

        # Merge hard constraints
        merged_hard = {
            **(previous.hard_constraints if same_category else {}),
            **current.hard_constraints,
        }
        current.hard_constraints = merged_hard

        # Merge exclusions
        current.exclusions = list(dict.fromkeys(
            (previous.exclusions if same_category else []) + current.exclusions
        ))

        replaced_constraint_names = set()
        if current.budget_max is not None and current.budget_max != previous.budget_max:
            replaced_constraint_names.add("price")
        if current.size and current.size != previous.size:
            replaced_constraint_names.add("size")
        if current.colour and current.colour != previous.colour:
            replaced_constraint_names.add("color")
        merged_constraints = [
            constraint
            for constraint in (previous.explicit_constraints if same_category else [])
            if constraint.name not in replaced_constraint_names
        ] + current.explicit_constraints
        if current.budget_unlimited:
            merged_constraints = [
                constraint for constraint in merged_constraints
                if constraint.name.casefold() != "price"
            ]
        current.explicit_constraints = list({
            (item.name, item.operator, str(item.value)): item
            for item in merged_constraints
        }.values())

        return current
