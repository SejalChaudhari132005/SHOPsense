"""
ShopSense AI — Centralized LLM & Natural Language Service
Wraps Groq API with robust timeouts, error handling, and deterministic fallback
capabilities so the system remains fast, resilient, and testable without a live API key.
"""

import os
import re
import json
import logging
from typing import Dict, List, Optional, Any

from app.core.config import settings
from app.models.state import ExtractedIntent, ProductFitScore
from app.models.product import Product
from app.services.catalog_service import canonicalize_category, match_synonyms

logger = logging.getLogger(__name__)

# Initialize Groq client if key is configured
groq_client = None
if settings.GROQ_API_KEY and not settings.MOCK_LLM_FOR_TESTS:
    try:
        from groq import Groq
        groq_client = Groq(api_key=settings.GROQ_API_KEY)
    except Exception as e:
        logger.warning(f"Could not initialize Groq client: {e}")


def deterministic_extract_intent(query: str, history: Optional[List[Dict[str, str]]] = None) -> ExtractedIntent:
    """
    Deterministic fallback parser for extracting intent, budget, recipient, occasion,
    negations, and constraints without requiring an LLM call.
    """
    text = query.strip()
    lower_text = text.lower()

    # 1. Shopping Intent
    shopping_intent = "product_search"
    recipient = None
    occasion = None

    if "gift" in lower_text or "present" in lower_text:
        shopping_intent = "gift_buying"
        # Recipient detection
        for r in ["dad", "father", "mom", "mother", "brother", "sister", "friend", "wife", "husband", "son", "daughter"]:
            if re.search(rf"\b{r}\b", lower_text):
                recipient = r
                break
        # Occasion detection
        for occ in ["birthday", "anniversary", "christmas", "holiday", "graduation"]:
            if occ in lower_text:
                occasion = occ
                break
    elif any(ref in lower_text for ref in ["cheaper", "only black", "show only", "change budget", "actually"]):
        shopping_intent = "refinement"

    # 2. Category & Intended Use
    category = None
    subcategory = None
    intended_use = None

    # Check activities/uses first
    for act in ["hiking", "trail running", "running", "travel", "programming", "camping", "gym", "yoga", "cooking"]:
        if act in lower_text:
            intended_use = act
            break

    # Check categories
    if any(k in lower_text for k in ["shoe", "shoes", "sneaker", "sneakers", "boot", "boots", "footwear", "loafer"]):
        category = "footwear"
    elif any(k in lower_text for k in ["laptop", "notebook", "headphone", "headphones", "earbud", "earbuds", "charger", "camera", "tech", "electronics"]):
        category = "electronics"
        if "laptop" in lower_text:
            subcategory = "laptops"
        elif any(h in lower_text for h in ["headphone", "earbud", "audio"]):
            subcategory = "audio"
    elif any(k in lower_text for k in ["backpack", "bag", "duffel", "tote", "pack"]):
        category = "bags_accessories"
    elif any(k in lower_text for k in ["jacket", "shirt", "pants", "chinos", "clothes", "clothing", "parka"]):
        category = "clothing"
    elif any(k in lower_text for k in ["tent", "bottle", "yoga mat", "dumbbells", "trekking pole", "weights", "outdoor"]):
        category = "fitness_outdoor"
    elif any(k in lower_text for k in ["blender", "espresso", "skillet", "kettle", "kitchen", "cookware"]):
        category = "home_kitchen"
    elif any(k in lower_text for k in ["pillow", "adapter", "packing cubes", "luggage strap"]):
        category = "travel_accessories"

    # If no category explicitly stated, but intended use is hiking, consider fitness_outdoor or footwear
    if not category and intended_use == "hiking":
        if any(w in lower_text for w in ["lightweight", "gear", "product", "item", "gift"]):
            # Broad search across outdoor categories
            category = "fitness_outdoor"

    # 3. Budget Extraction
    budget_max = None
    budget_min = None
    budget_currency = "USD"
    is_budget_strict = True

    # Check currency with word boundaries (prevents 'rs' matching 'dollars')
    if "$" in text or re.search(r"\b(?:usd|dollars?|bucks)\b", lower_text):
        budget_currency = "USD"
    elif "₹" in text or re.search(r"\b(?:inr|rupees|rs\.?)\b", lower_text):
        budget_currency = "INR"
    elif "€" in text or re.search(r"\b(?:eur|euros?)\b", lower_text):
        budget_currency = "EUR"
    elif "£" in text or re.search(r"\b(?:gbp|pounds?)\b", lower_text):
        budget_currency = "GBP"

    # Flexibility vs Strict limit
    if any(flex in lower_text for flex in ["around", "approx", "roughly", "about"]):
        is_budget_strict = False

    # Max budget regex (e.g. "under ₹8,000", "around ₹5,000", "below $1000", "<= 500", "under 8000")
    max_match = re.search(r"(?:under|below|less than|within|max|keep it under|around|about|approx|roughly)\s*[\$₹€£]?\s*(\d+(?:,\d+)*(?:\.\d+)?)", lower_text)
    if max_match:
        budget_max = float(max_match.group(1).replace(",", ""))
    else:
        # Direct currency amount (e.g. "₹8,000", "$150", "₹5,000")
        direct_curr_match = re.search(r"[\$₹€£]\s*(\d+(?:,\d+)*(?:\.\d+)?)", text)
        if direct_curr_match:
            budget_max = float(direct_curr_match.group(1).replace(",", ""))

    # 4. Soft Preferences & Features
    soft_preferences: List[str] = []
    if "lightweight" in lower_text or "light" in lower_text:
        soft_preferences.append("lightweight")
    if "waterproof" in lower_text or "gore-tex" in lower_text:
        soft_preferences.append("waterproof")
    if "long battery" in lower_text or "battery" in lower_text:
        soft_preferences.append("long_battery")
    if "noise cancelling" in lower_text or "anc" in lower_text:
        soft_preferences.append("noise_cancelling")
    if "cushioned" in lower_text or "comfortable" in lower_text:
        soft_preferences.append("cushioned")
    if "breathable" in lower_text:
        soft_preferences.append("breathable")
    if "durable" in lower_text:
        soft_preferences.append("durable")

    # 5. Exclusions & Negations
    exclusions: List[str] = []
    neg_matches = re.findall(r"(?:not|no|without|except)\s+([a-zA-Z0-9_-]+)", lower_text)
    for n in neg_matches:
        if n not in ("a", "an", "the", "too", "very"):
            exclusions.append(n)

    # 6. Physical Attributes (Brand, Size, Colour)
    colour = None
    for c in ["black", "white", "grey", "blue", "green", "orange", "tan", "navy", "silver"]:
        if re.search(rf"\b{c}\b", lower_text):
            colour = c
            break

    brand = None
    for b in ["alpinetrack", "zenith", "apex", "acoustix", "pulsewave", "voyager", "urbanstride", "nimbusrun"]:
        if b in lower_text:
            brand = b.capitalize()
            break

    size = None
    size_match = re.search(r"\bsize\s*(\d+(\.\d+)?|[xXsSmMlL]+)\b", lower_text)
    if size_match:
        size = size_match.group(1).upper()

    # 7. Hard Constraints
    hard_constraints: Dict[str, Any] = {}
    if "waterproof" in lower_text and any(strict in lower_text for strict in ["must be waterproof", "strictly waterproof", "needs to be waterproof"]):
        hard_constraints["waterproof"] = True

    return ExtractedIntent(
        shopping_intent=shopping_intent,
        category=category,
        subcategory=subcategory,
        budget_min=budget_min,
        budget_max=budget_max,
        budget_currency=budget_currency,
        is_budget_strict=is_budget_strict,
        hard_constraints=hard_constraints,
        soft_preferences=soft_preferences,
        intended_use=intended_use,
        recipient=recipient,
        occasion=occasion,
        size=size,
        colour=colour,
        brand=brand,
        feature_preferences=soft_preferences,
        exclusions=exclusions,
        is_refinement=shopping_intent == "refinement"
    )


def extract_intent_with_llm(query: str, history: Optional[List[Dict[str, str]]] = None) -> ExtractedIntent:
    """
    Extracts structured intent using Groq LLM if available, falling back to deterministic parser.
    """
    if groq_client is not None and not settings.MOCK_LLM_FOR_TESTS:
        try:
            system_prompt = (
                "You are an expert shopping assistant entity extractor. "
                "Analyze the user message and extract shopping constraints into clean JSON. "
                "Keys: shopping_intent ('product_search'|'refinement'|'comparison'), "
                "category (e.g. 'footwear', 'electronics', 'clothing', 'bags_accessories', 'fitness_outdoor'), "
                "subcategory (e.g. 'laptops', 'running shoes', 'headphones', 'backpacks'), "
                "budget_min (float or null), budget_max (float or null), budget_currency ('USD'|'INR'|'EUR'|'GBP'), "
                "is_budget_strict (bool), "
                "hard_constraints (dict of non-negotiable physical attributes like {'waterproof': true, 'noise_cancelling': true, 'ram_gb': 16}. Never put budget, price, or category inside hard_constraints), "
                "soft_preferences (list of strings), intended_use (string or null), "
                "recipient (string or null), occasion (string or null), size (string or null), colour (string or null), "
                "brand (string or null), exclusions (list of strings)."
            )
            response = groq_client.chat.completions.create(
                model=settings.GROQ_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                response_format={"type": "json_object"},
                temperature=0.0,
                timeout=5.0
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            return ExtractedIntent(**parsed)
        except Exception as e:
            logger.warning(f"Groq intent extraction failed or timed out: {e}. Using deterministic parser.")

    return deterministic_extract_intent(query, history)


def generate_explanation_with_llm(
    product: Product, 
    intent: ExtractedIntent, 
    fit_score: ProductFitScore
) -> str:
    """
    Generates a personalized, truthful associate explanation based on verified structured facts.
    """
    # Deterministic factual template
    reasons = []

    # Category and Use Case Fit
    if intent.intended_use and intent.intended_use in " ".join(product.use_cases).lower():
        reasons.append(f"specifically engineered for {intent.intended_use}")

    # Budget Fit
    curr_symbol = "₹" if intent.budget_currency == "INR" else "$"
    if intent.budget_max:
        reasons.append(f"stays within your {curr_symbol}{intent.budget_max:,.0f} budget")

    # Matched Features
    for match in fit_score.exact_matches:
        reasons.append(f"delivers verified {match}")

    # Build cohesive explanation
    reason_str = ", ".join(reasons) if reasons else "matches your core criteria well"
    brand_title = f"{product.brand} {product.product_name}"

    explanation = f"I recommend the {brand_title} because it {reason_str}."

    # Note trade-offs or unknown aspects honestly (Rule #9, #10)
    if fit_score.unknown_attributes:
        unknown_str = ", ".join(fit_score.unknown_attributes)
        explanation += f" Note: {unknown_str} is unverified on this listing."

    return explanation
