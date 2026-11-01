"""Shared hard-constraint checks for retrieval and fit ranking."""

import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Set, Tuple

from app.models.product import Product
from app.models.state import ExtractedIntent
from app.core.config import settings
from app.services.catalog_service import (
    CATEGORY_SYNONYMS,
    canonicalize_category,
    match_synonyms,
    product_matches_subcategory,
)
from app.services.currency_service import convert_currency


@dataclass(frozen=True)
class ConstraintEvaluation:
    is_eligible: bool
    violations: Tuple[str, ...]
    unknown_attributes: Tuple[str, ...]


def budget_ceiling_inr(intent: ExtractedIntent) -> Optional[float]:
    """Return the shared INR ceiling used for approximate and strict budgets."""
    if intent.budget_max is None:
        return None
    maximum = convert_currency(
        intent.budget_max,
        intent.budget_currency,
        "INR",
    )
    if intent.budget_is_approximate:
        return round(maximum * (1.0 + settings.BUDGET_APPROX_TOLERANCE), 2)
    return maximum


_FALLBACK_SUBCATEGORY_GROUPS = (
    frozenset({"laptop", "laptops", "notebook"}),
    frozenset({"audio", "headphones", "earbuds"}),
    frozenset({"backpack", "commuter_backpacks", "hiking_backpacks", "travel_backpacks"}),
    frozenset({
        "running_shoe",
        "running_shoes",
        "barefoot_running",
        "road_running",
        "trail_running",
        "outdoor_footwear",
        "hiking_boot",
        "hiking_boots",
    }),
)


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _catalog_evidence_text(product: Product) -> str:
    values: List[str] = [
        product.product_name,
        product.brand,
        product.category,
        product.subcategory or "",
        product.description,
        *product.tags,
        *product.use_cases,
        *(product.colours or []),
        *(product.sizes or []),
    ]
    for collection in (product.attributes, product.specifications):
        for key, value in collection.items():
            values.extend((str(key), str(value)))
    return " ".join(values).casefold()


def _product_exclusion_text(product: Product) -> str:
    values = [
        product.product_name,
        product.brand,
        product.category,
        product.subcategory or "",
        product.description,
        *product.tags,
        *product.use_cases,
        *(product.colours or []),
        *(product.sizes or []),
    ]
    for collection in (product.attributes, product.specifications):
        values.extend(
            f"{key} {value}" for key, value in collection.items()
        )
    return " ".join(values).casefold()


def _audience_text(product: Product) -> str:
    return " ".join([
        product.product_name,
        product.brand,
        product.category,
        product.subcategory or "",
        product.description,
        *product.tags,
        *product.use_cases,
    ]).casefold()


def _normalize_taxonomy_value(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().casefold()).strip("_")


def fallback_subcategories_compatible(
    product_subcategory: Optional[str],
    requested_subcategory: Optional[str],
) -> bool:
    """Allow only exact taxonomy entries or entries in an explicit fallback family."""
    if not product_subcategory or not requested_subcategory:
        return False
    actual = _normalize_taxonomy_value(product_subcategory)
    requested = _normalize_taxonomy_value(requested_subcategory)
    if product_matches_subcategory(product_subcategory, requested_subcategory):
        return True
    return any(
        actual in group and requested in group
        for group in _FALLBACK_SUBCATEGORY_GROUPS
    )


def _feature_is_verified(product: Product, feature: str) -> Optional[bool]:
    return resolve_verified_feature(product, feature)


def resolve_verified_feature(product: Product, feature: str) -> Optional[bool]:
    """Resolve a feature using structured evidence and explicit catalog tags."""
    normalized = _normalize_key(feature)
    if normalized == "lightweight":
        actual = resolve_hard_value(product, "lightweight")
        if isinstance(actual, bool):
            return actual
        evidence = _catalog_evidence_text(product)
        if re.search(r"\b(?:lightweight|ultralight|featherweight)\b", evidence):
            return True
        return None

    actual = resolve_hard_value(product, feature)
    if isinstance(actual, bool):
        return actual
    if actual is not None and str(actual).strip().casefold() in {"false", "no", "0"}:
        return False
    if actual is not None and str(actual).strip().casefold() in {"true", "yes", "1"}:
        return True

    if normalized == "waterproof":
        waterproof_level = resolve_feature_strength(product, "waterproof")
        return True if waterproof_level == 2 else False if waterproof_level == 1 else None

    product_text = _catalog_evidence_text(product)
    synonyms = list(match_synonyms(feature))
    synonyms.extend([
        feature.replace("_", " "),
        normalized.replace("_", " "),
    ])
    if normalized == "waterproof":
        synonyms = [
            synonym for synonym in synonyms
            if synonym.casefold() not in {"water-resistant", "water resistant"}
        ]
    if any(synonym.casefold() in product_text for synonym in synonyms if synonym.strip()):
        return True
    return None


def resolve_feature_strength(product: Product, feature: str) -> Optional[int]:
    """Return evidence strength: 2 for exact waterproof, 1 for water-resistant."""
    normalized = _normalize_key(feature)
    if normalized not in {"waterproof", "water_resistant"}:
        return 2 if resolve_verified_feature(product, feature) is True else None
    actual = resolve_hard_value(product, "waterproof")
    if actual is True:
        return 2
    actual_resistant = resolve_hard_value(product, "water_resistant")
    if actual_resistant is True:
        return 1
    evidence = _catalog_evidence_text(product)
    if re.search(r"\b(?:gore[\s-]?tex|waterproof|rainproof|weatherproof|ipx[78])\b", evidence):
        return 2
    if re.search(r"\bwater[\s-]?resistant\b", evidence):
        return 1
    return None


def evaluate_recommendation_candidate(
    product: Product,
    intent: ExtractedIntent,
    excluded_product_ids: Optional[Iterable[str]] = None,
    *,
    allow_related_subcategory: bool = False,
    budget_max_override: Optional[float] = None,
) -> ConstraintEvaluation:
    """Apply hard constraints, known-category validation, and requested feature evidence."""
    category = (product.category or "").strip()
    canonical_product_category = canonicalize_category(category) if category else ""
    violations: List[str] = []
    unknown: List[str] = []

    if not canonical_product_category or canonical_product_category not in CATEGORY_SYNONYMS:
        violations.append("Product category is missing or not in the catalog taxonomy.")
    if intent.category and intent.category_is_explicit:
        requested_category = canonicalize_category(intent.category)
        if canonical_product_category != requested_category:
            violations.append(
                f"Category '{category or 'unknown'}' does not match '{intent.category}'."
            )

    candidate_intent = intent
    if allow_related_subcategory and intent.subcategory_is_explicit:
        candidate_intent = intent.model_copy(
            update={"subcategory_is_explicit": False}
        )
    if budget_max_override is not None:
        candidate_intent = candidate_intent.model_copy(
            update={"budget_max": budget_max_override, "is_budget_strict": True}
        )

    base_evaluation = evaluate_hard_constraints(
        product,
        candidate_intent,
        excluded_product_ids=excluded_product_ids,
    )
    violations.extend(base_evaluation.violations)
    unknown.extend(base_evaluation.unknown_attributes)
    if intent.subcategory and intent.subcategory_is_explicit:
        if not product_matches_subcategory(product.subcategory, intent.subcategory):
            if not (
                allow_related_subcategory
                and fallback_subcategories_compatible(product.subcategory, intent.subcategory)
            ):
                violations.append(
                    f"Product type '{product.subcategory or 'unknown'}' is not compatible "
                    f"with '{intent.subcategory}'."
                )

    return ConstraintEvaluation(
        is_eligible=not violations,
        violations=tuple(dict.fromkeys(violations)),
        unknown_attributes=tuple(dict.fromkeys(unknown)),
    )


def resolve_hard_value(product: Product, key: str) -> Any:
    normalized_key = _normalize_key(key)
    if normalized_key in {"availability", "stock_status"}:
        return product.availability.value
    if normalized_key in {"in_stock", "available"}:
        return product.availability.value == "in_stock"
    if normalized_key in {"category"}:
        return product.category
    if normalized_key in {"subcategory", "product_type"}:
        return product.subcategory
    if normalized_key in {"brand"}:
        return product.brand
    if normalized_key in {"size", "sizes"}:
        return product.sizes
    if normalized_key in {"color", "colour", "colors", "colours"}:
        return product.colours
    if normalized_key in {"price", "price_max", "budget", "budget_max", "budget_min"}:
        return product.price

    for collection in (product.attributes, product.specifications):
        for actual_key, value in collection.items():
            if _normalize_key(str(actual_key)) == normalized_key:
                return value
    return None


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "yes", "1", "in_stock", "available"}:
            return True
        if lowered in {"false", "no", "0", "out_of_stock", "unavailable"}:
            return False
    return None


def evaluate_hard_constraints(
    product: Product,
    intent: ExtractedIntent,
    excluded_product_ids: Optional[Iterable[str]] = None,
) -> ConstraintEvaluation:
    """Return eligibility using only mandatory intent fields and explicit exclusions."""
    violations: List[str] = []
    unknown: List[str] = []
    excluded_ids = set(excluded_product_ids or ())
    product_text = _product_exclusion_text(product)
    audience_text = _audience_text(product)

    # Recipient gender signals are only used when both sides contain explicit
    # evidence. Missing recipient/product metadata remains eligible.
    female_recipient = intent.recipient and intent.recipient.casefold() in {
        "girlfriend", "wife", "mother", "mom", "daughter", "sister",
    }
    male_recipient = intent.recipient and intent.recipient.casefold() in {
        "men", "males", "boyfriend", "husband", "father", "dad", "son", "brother",
    }
    male_only_listing = bool(
        re.search(r"\b(?:men|men's|mens|male)\b", audience_text)
    )
    female_only_listing = bool(
        re.search(r"\b(?:women|women's|womens|female)\b", audience_text)
    )
    if female_recipient and male_only_listing:
        violations.append(
            "Product is explicitly marketed for men and does not match the recipient."
        )
    if male_recipient and female_only_listing:
        violations.append(
            "Product is explicitly marketed for women and does not match the recipient."
        )

    if product.product_id in excluded_ids:
        violations.append("Product was excluded from this session.")
    if product.availability.value == "out_of_stock":
        violations.append("Product is out of stock.")
    if intent.exclude_sized_items and (
        product.requires_size or product.category in {"footwear", "clothing"}
    ):
        violations.append("Product requires sizing and was excluded by the user.")

    if intent.category and intent.category_is_explicit:
        if canonicalize_category(product.category) != canonicalize_category(intent.category):
            violations.append(
                f"Category '{product.category}' does not match '{intent.category}'"
            )

    if intent.subcategory and intent.subcategory_is_explicit:
        if not product_matches_subcategory(product.subcategory, intent.subcategory):
            violations.append(
                f"Product type '{product.subcategory or 'unknown'}' does not match "
                f"'{intent.subcategory}'"
            )
        elif _normalize_key(intent.subcategory) in {"dress", "dresses", "womens_dresses"}:
            dress_evidence = re.search(
                r"\b(?:dress|dresses|gown|gowns|frock|frocks|skirt|skirts)\b",
                product_text,
            )
            if not dress_evidence:
                violations.append(
                    "Product listing does not contain verified dress evidence."
                )

    product_price_inr = convert_currency(product.price, product.currency, "INR")
    if intent.budget_min is not None:
        minimum_inr = convert_currency(intent.budget_min, intent.budget_currency, "INR")
        if product_price_inr < minimum_inr:
            violations.append("Price is below the requested minimum.")
    if (
        intent.budget_max is not None
        and (intent.is_budget_strict or intent.budget_is_approximate)
    ):
        maximum_inr = budget_ceiling_inr(intent)
        if maximum_inr is not None and product_price_inr > maximum_inr:
            violations.append("Price exceeds the strict budget ceiling.")

    for exclusion in intent.exclusions:
        if exclusion.strip() and exclusion.casefold() in product_text:
            violations.append(f"Product matches excluded term '{exclusion}'.")

    ignored_keys = {
        "category",
        "subcategory",
        "product_type",
        "budget",
        "budget_max",
        "budget_min",
        "price",
        "price_max",
        "currency",
        "shopping_intent",
        "is_budget_strict",
    }
    for key, expected in intent.hard_constraints.items():
        normalized_key = _normalize_key(key)
        if normalized_key in ignored_keys:
            continue
        actual = (
            resolve_verified_feature(product, key)
            if isinstance(expected, bool)
            else resolve_hard_value(product, key)
        )
        if actual is None:
            unknown.append(key)
            continue
        if isinstance(expected, bool):
            actual_bool = _as_bool(actual)
            if actual_bool is None:
                unknown.append(key)
            elif actual_bool != expected:
                violations.append(f"Hard constraint failed: '{key}' is {actual}.")
        elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
            try:
                if float(actual) < float(expected):
                    violations.append(
                        f"Hard constraint failed: '{key}' is {actual}, expected at least {expected}."
                    )
            except (TypeError, ValueError):
                unknown.append(key)
                violations.append(f"Required attribute '{key}' is not verifiable.")
        elif isinstance(actual, (list, tuple, set)):
            expected_text = str(expected).casefold()
            if not any(str(value).casefold() == expected_text for value in actual):
                violations.append(f"Hard constraint failed: '{key}' does not match.")
        elif str(actual).casefold() != str(expected).casefold():
            violations.append(f"Hard constraint failed: '{key}' does not match.")

    return ConstraintEvaluation(
        is_eligible=not violations,
        violations=tuple(violations),
        unknown_attributes=tuple(unknown),
    )
