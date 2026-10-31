from app.agents.zero_result_fallback import ZeroResultFallbackAgent
from app.models.product import Product
from app.models.state import ExtractedIntent
from app.services.catalog_service import load_and_validate_catalog
from app.services.llm_service import deterministic_extract_intent
from app.services.retrieval_constraints import evaluate_recommendation_candidate


def _product(
    product_id: str,
    name: str,
    category: str = "footwear",
    subcategory: str = "trail_running",
    price: float = 120.0,
    attributes: dict | None = None,
    tags: list[str] | None = None,
) -> Product:
    return Product(
        product_id=product_id,
        product_name=name,
        brand="Test Brand",
        category=category,
        subcategory=subcategory,
        description=f"{name} for trail running.",
        price=price,
        currency="USD",
        normalized_price_usd=price,
        attributes=attributes or {},
        tags=tags or [],
        use_cases=["trail running"],
    )


def _intent(
    subcategory: str | None = "trail_running",
    budget: float | None = 150.0,
    features: list[str] | None = None,
) -> ExtractedIntent:
    return ExtractedIntent(
        category="footwear",
        subcategory=subcategory,
        category_is_explicit=True,
        subcategory_is_explicit=subcategory is not None,
        budget_max=budget,
        budget_currency="USD",
        is_budget_strict=budget is not None,
        feature_preferences=features or [],
        intended_use="trail running",
    )


def test_waterproof_trail_running_query_never_returns_grocery_products():
    intent = deterministic_extract_intent("Waterproof trail-running shoes under $150")
    fallback = ZeroResultFallbackAgent(load_and_validate_catalog()).generate_fallback(intent)

    assert fallback.result_kind in {"exact_matches", "related_alternatives"}
    assert fallback.suggested_alternatives
    assert all(product.category == "footwear" for product in fallback.suggested_alternatives)
    assert all(product.attributes.get("waterproof") is True for product in fallback.suggested_alternatives)
    assert all(product.normalized_price_usd <= 150 for product in fallback.suggested_alternatives)
    assert all(product.product_id != "dummyjson_31" for product in fallback.suggested_alternatives)


def test_running_shoes_under_100_returns_only_in_budget_footwear():
    intent = _intent("running_shoes", 100.0)
    barefoot = _product("barefoot", "Barefoot running shoe", subcategory="barefoot_running", price=89)
    grocery = _product("lemon", "Lemon", "groceries", "groceries", 0.79)

    fallback = ZeroResultFallbackAgent([barefoot, grocery]).generate_fallback(intent)

    assert [product.product_id for product in fallback.suggested_alternatives] == ["barefoot"]
    assert fallback.original_budget == fallback.proposed_budget == 100


def test_waterproof_hiking_shoes_over_budget_require_approval():
    intent = _intent("hiking_boots", 150.0, ["waterproof"])
    boot = _product(
        "waterproof-boot",
        "Waterproof hiking boot",
        subcategory="hiking_boots",
        price=189.95,
        attributes={"waterproof": True},
    )

    fallback = ZeroResultFallbackAgent([boot]).generate_fallback(intent)

    assert fallback.result_kind == "relaxed_alternatives"
    assert fallback.suggested_alternatives == [boot]
    assert fallback.proposed_budget == 189.95
    assert fallback.requires_user_approval is True
    assert fallback.relaxed_constraints["budget_max"] == 189.95


def test_waterproof_shoes_under_200_preserve_feature_and_budget():
    intent = _intent(None, 200.0, ["waterproof"])
    shoe = _product(
        "waterproof-shoe",
        "Waterproof hiking shoe",
        subcategory="hiking_boots",
        price=189.95,
        attributes={"waterproof": True},
    )

    fallback = ZeroResultFallbackAgent([shoe]).generate_fallback(intent)

    assert fallback.suggested_alternatives == [shoe]
    assert fallback.proposed_budget == 200
    assert fallback.relaxed_constraints == {}


def test_trail_running_without_waterproof_requirement_can_broaden_type():
    intent = _intent("trail_running", 150.0)
    road_shoe = _product(
        "road-shoe",
        "Road running shoe",
        subcategory="road_running",
        attributes={"waterproof": False},
    )

    fallback = ZeroResultFallbackAgent([road_shoe]).generate_fallback(intent)

    assert fallback.result_kind == "related_alternatives"
    assert fallback.suggested_alternatives == [road_shoe]
    assert fallback.relaxed_constraints["subcategory"] == "related catalog subcategories"
    assert fallback.requires_user_approval is True


def test_empty_footwear_catalog_returns_no_valid_alternatives():
    fallback = ZeroResultFallbackAgent([]).generate_fallback(_intent())

    assert fallback.result_kind == "no_valid_alternatives"
    assert fallback.suggested_alternatives == []
    assert fallback.relaxed_constraints == {}


def test_grocery_product_is_rejected_from_footwear_fallback():
    intent = _intent()
    food = _product("food", "Lemon", "groceries", "groceries", 0.79)

    evaluation = evaluate_recommendation_candidate(food, intent, allow_related_subcategory=True)
    fallback = ZeroResultFallbackAgent([food]).generate_fallback(intent)

    assert evaluation.is_eligible is False
    assert fallback.suggested_alternatives == []


def test_comparison_fallback_keeps_only_the_named_products():
    intent = ExtractedIntent(
        category="electronics",
        subcategory="audio",
        category_is_explicit=True,
        subcategory_is_explicit=True,
        comparison_product_ids=["headphones", "earbuds"],
        purchase_intent="comparison",
        budget_max=100,
        budget_currency="USD",
        is_budget_strict=True,
    )
    headphones = _product(
        "headphones",
        "QuietPulse 750 Headphones",
        "electronics",
        "headphones",
        price=280,
    )
    earbuds = _product(
        "earbuds",
        "SonicBuds Sport Earbuds",
        "electronics",
        "earbuds",
        price=130,
    )
    unrelated = _product(
        "speaker",
        "HomePod Mini Speaker",
        "electronics",
        "speakers",
        price=80,
    )

    fallback = ZeroResultFallbackAgent([headphones, earbuds, unrelated]).generate_fallback(intent)

    assert fallback.suggested_alternatives
    assert all(
        product.product_id in {"headphones", "earbuds"}
        for product in fallback.suggested_alternatives
    )


def test_product_with_missing_category_is_rejected():
    product = _product("unknown-category", "Trail shoe").model_copy(update={"category": ""})

    evaluation = evaluate_recommendation_candidate(product, _intent())

    assert evaluation.is_eligible is False
    assert "category" in " ".join(evaluation.violations).casefold()


def test_missing_waterproof_evidence_does_not_qualify():
    intent = _intent(features=["waterproof"])
    shoe = _product(
        "unknown-waterproof",
        "Trail running shoe",
        tags=["trail running"],
    )

    evaluation = evaluate_recommendation_candidate(shoe, intent)

    assert evaluation.is_eligible is False
    assert "waterproof" in " ".join(evaluation.violations).casefold()


def test_lightweight_feature_uses_documented_product_weight():
    catalog = load_and_validate_catalog()
    product = next(item for item in catalog if item.product_id == "prod_foot_001")
    intent = ExtractedIntent(
        category="footwear",
        subcategory="running_shoes",
        category_is_explicit=True,
        subcategory_is_explicit=True,
        feature_preferences=["lightweight", "waterproof"],
        budget_max=150,
        budget_currency="USD",
        is_budget_strict=True,
    )

    evaluation = evaluate_recommendation_candidate(product, intent)

    assert evaluation.is_eligible is True


def test_zero_result_with_no_compatible_products_does_not_claim_relaxation():
    food = _product("food", "Lemon", "groceries", "groceries", 0.79)
    fallback = ZeroResultFallbackAgent([food]).generate_fallback(_intent())

    assert fallback.result_kind == "no_valid_alternatives"
    assert fallback.relaxed_constraints == {}
    assert fallback.suggested_alternatives == []
    assert "could not find a valid product" in fallback.explanation.casefold()


def test_budget_relaxation_is_only_a_proposal_for_compatible_products():
    intent = ExtractedIntent(
        category="electronics",
        subcategory="laptops",
        category_is_explicit=True,
        subcategory_is_explicit=True,
        budget_max=100,
        budget_currency="USD",
        is_budget_strict=True,
    )
    laptop = _product(
        "laptop",
        "Notebook computer",
        "electronics",
        "laptops",
        300,
    )

    fallback = ZeroResultFallbackAgent([laptop]).generate_fallback(intent)

    assert fallback.suggested_alternatives == [laptop]
    assert fallback.requires_user_approval is True
    assert fallback.result_kind == "relaxed_alternatives"
    assert fallback.preserved_constraints["category"] == "electronics"
    assert fallback.proposed_budget == 300


def test_related_subcategory_fallback_requires_same_category():
    intent = _intent("trail_running")
    related = _product("road", "Road running shoe", subcategory="road_running")
    evaluation = evaluate_recommendation_candidate(
        related,
        intent,
        allow_related_subcategory=True,
    )

    assert evaluation.is_eligible is True


def test_unrelated_category_is_rejected_even_with_matching_text():
    intent = _intent("trail_running")
    product = _product(
        "electronics",
        "Waterproof trail running tracker",
        "electronics",
        "trail_running",
        attributes={"waterproof": True},
    )

    evaluation = evaluate_recommendation_candidate(
        product,
        intent,
        allow_related_subcategory=True,
    )

    assert evaluation.is_eligible is False
    assert any("Category" in violation for violation in evaluation.violations)


def test_final_recommendation_gate_rejects_food_and_accepts_relevant_shoe():
    intent = _intent(features=["waterproof"])
    food = _product(
        "food",
        "Waterproof Lemon trail running",
        "groceries",
        "groceries",
        attributes={"waterproof": True},
        tags=["trail running"],
    )
    shoe = _product(
        "shoe",
        "Waterproof trail running shoe",
        attributes={"waterproof": True},
    )

    assert not evaluate_recommendation_candidate(food, intent).is_eligible
    assert evaluate_recommendation_candidate(shoe, intent).is_eligible
