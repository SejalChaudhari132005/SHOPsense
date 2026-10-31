from unittest.mock import patch

from app.agents.ambiguity_clarification import AmbiguityClarificationAgent
from app.agents.candidate_retrieval import CandidateRetrievalAgent
from app.agents.graph_orchestrator import ShopSenseWorkflow
from app.agents.intent_extraction import IntentExtractionAgent
from app.agents.session_memory import SessionMemoryAgent
from app.models.product import Product
from app.models.state import (
    AttributeMappingResult,
    ExtractedIntent,
    IngestedQuery,
)
from app.services.hybrid_retrieval import HybridSearchResult
from app.services.llm_service import deterministic_extract_intent
from app.services.retrieval_constraints import (
    evaluate_hard_constraints,
    evaluate_recommendation_candidate,
)


def _extract(query, previous=None):
    ingested = IngestedQuery(
        session_id="intent-regression",
        raw_message=query,
        sanitized_message=query,
    )
    with patch(
        "app.agents.intent_extraction.extract_intent_with_llm",
        side_effect=lambda text, history: deterministic_extract_intent(text, history),
    ):
        return IntentExtractionAgent().extract(ingested, previous_intent=previous)


def _product(product_id, name, category, price=10000.0):
    return Product(
        product_id=product_id,
        product_name=name,
        brand="Demo",
        category=category,
        subcategory=None,
        description="Demo catalog listing",
        price=price,
        currency="INR",
        normalized_price_usd=price / 83.3333,
        tags=[],
        use_cases=[],
        specifications={},
    )


def test_gift_discovery_keeps_category_unspecified_and_extracts_persona():
    intent = deterministic_extract_intent(
        "Suggest a birthday gift for my girlfriend around ₹50,000, premium look and feel"
    )

    assert intent.shopping_intent == "gift_buying"
    assert intent.purchase_intent == "gift"


def test_gift_activity_and_health_query_proceeds_without_category_question():
    query = (
        "I need something for my dad who's turning 60, he's into hiking "
        "but has bad knees, budget around 10000 INR"
    )
    intent = _extract(query)
    decision = AmbiguityClarificationAgent().evaluate(
        intent,
        raw_user_message=query,
    )

    assert intent.shopping_intent == "gift_buying"
    assert intent.purchase_intent == "gift"
    assert intent.recipient == "dad"
    assert intent.intended_use == "hiking"
    assert intent.category_hint == "fitness_outdoor"
    assert "joint discomfort" in intent.health_considerations
    assert decision.needs_clarification is False


def test_gift_discovery_keeps_category_unspecified_and_extracts_persona_details():
    intent = deterministic_extract_intent(
        "Suggest a birthday gift for my girlfriend around ₹50,000, premium look and feel"
    )

    assert intent.recipient == "girlfriend"
    assert intent.occasion == "birthday"
    assert intent.category is None
    assert intent.budget_max == 50000
    assert intent.budget_currency == "INR"
    assert intent.is_budget_strict is False
    assert "premium" in intent.soft_preferences


def test_category_discovery_uses_catalog_metadata_without_product_search():
    with patch(
        "app.agents.intent_extraction.extract_intent_with_llm",
        side_effect=lambda text, history: deterministic_extract_intent(text, history),
    ):
        response = ShopSenseWorkflow().execute_turn(
            "category-discovery-regression",
            "What categories of products do you offer?",
        )

    assert response.action_taken == "recommend"
    assert not response.recommendations
    assert "Beauty & Personal Care" in response.message
    assert "products" in response.message
    categories = response.session_summary["available_categories"]
    assert categories
    assert all(item["product_count"] > 0 for item in categories)


def test_beauty_and_care_is_an_explicit_catalog_category():
    intent = deterministic_extract_intent(
        "I want beauty and care products for my girlfriend's birthday"
    )

    assert intent.category == "beauty_personal_care"
    assert intent.category_is_explicit is True
    assert intent.purchase_intent == "gift"


def test_category_selection_continues_prior_gift_flow_into_retrieval():
    session_id = "category-selection-regression"
    workflow = ShopSenseWorkflow()
    with patch(
        "app.agents.intent_extraction.extract_intent_with_llm",
        side_effect=lambda text, history: deterministic_extract_intent(text, history),
    ):
        first = workflow.execute_turn(
            session_id,
            "Suggest a birthday gift for my girlfriend around ₹50,000, premium look and feel",
        )
        selected = workflow.execute_turn(session_id, "Beauty and Personal Care")
        refined = workflow.execute_turn(
            session_id,
            "Suggest some good options for beauty and personal care around ₹3,000",
        )
        continued = workflow.execute_turn(session_id, "Suggest products")

    assert first.action_taken == "clarify"
    assert selected.recommendations
    assert selected.session_summary["session_id"] == session_id
    assert refined.recommendations
    assert continued.recommendations
    assert "catalog currently includes" not in selected.message.casefold()
    assert all(
        recommendation.product.category == "beauty_personal_care"
        for recommendation in continued.recommendations
    )
    assert all(
        recommendation.product.price <= 3000
        for recommendation in continued.recommendations
    )


def test_female_gift_recipient_excludes_explicit_mens_listing():
    product = _product(
        "mens-lotion",
        "Vaseline Men Body and Face Lotion",
        "beauty_personal_care",
    )
    intent = deterministic_extract_intent(
        "Beauty and personal care birthday gift for my girlfriend under ₹3,000"
    )

    evaluation = evaluate_hard_constraints(product, intent)

    assert not evaluation.is_eligible
    assert any("marketed for men" in violation for violation in evaluation.violations)


def test_new_travel_gift_does_not_inherit_beauty_category_or_budget():
    previous = deterministic_extract_intent(
        "Beauty and care birthday gift under ₹10,000"
    )
    current = _extract("What are some good travel gifts?", previous)

    assert current.category is None
    assert current.budget_max is None
    assert current.intended_use == "travel"
    assert current.purchase_intent == "gift"


def test_category_change_replaces_category_but_keeps_relevant_budget_and_gift_context():
    previous = deterministic_extract_intent(
        "Beauty and care birthday gift for my girlfriend under ₹50,000"
    )
    current = _extract("Jewellery", previous)

    assert current.category == "fashion_accessories"
    assert current.subcategory is None
    assert current.budget_max == 50000
    assert current.purchase_intent == "gift"
    assert current.recipient == "girlfriend"
    assert current.occasion == "birthday"


def test_no_budget_limit_removes_previous_budget_but_keeps_category():
    previous = deterministic_extract_intent("headphones under ₹20,000")
    current = _extract("No budget limit", previous)

    assert current.category == "electronics"
    assert current.subcategory == "audio"
    assert current.budget_unlimited is True
    assert current.budget_min is None
    assert current.budget_max is None
    assert not any(item.name == "price" for item in current.explicit_constraints)


def test_parser_extracts_budget_ranges_and_minimums_in_inr():
    ranged = deterministic_extract_intent("Between ₹20,000 and ₹40,000")
    minimum = deterministic_extract_intent("Show options above ₹10,000")

    assert ranged.budget_min == 20000
    assert ranged.budget_max == 40000
    assert ranged.budget_currency == "INR"
    assert minimum.budget_min == 10000
    assert minimum.budget_max is None


def test_explicit_mens_watches_never_returns_womens_watches_or_other_accessories():
    query = "suggest best watches for men under 10000"
    ingested = IngestedQuery(
        session_id="mens-watch-regression",
        raw_message=query,
        sanitized_message=query,
    )
    with patch(
        "app.agents.intent_extraction.extract_intent_with_llm",
        side_effect=lambda text, history: deterministic_extract_intent(text, history),
    ):
        intent = IntentExtractionAgent().extract(ingested)
    retrieval = CandidateRetrievalAgent().retrieve(
        intent,
        AttributeMappingResult(normalized_category=intent.category),
        query_text=query,
    )

    assert intent.subcategory == "mens-watches"
    assert intent.subcategory_is_explicit is True
    assert intent.recipient == "men"
    assert retrieval.candidates
    assert all(product.subcategory == "mens-watches" for product in retrieval.candidates)


def test_watch_plural_is_explicit_in_full_intent_extraction():
    intent = _extract("suggest best watches for men under 10000")

    assert intent.subcategory == "mens-watches"
    assert intent.subcategory_is_explicit is True


def test_automotive_product_requests_are_not_category_discovery():
    for query in (
        "suggest 3 best automotive products",
        "recommend some automotive products",
        "I'm looking for automotive products",
    ):
        intent = deterministic_extract_intent(query)
        assert intent.category == "automotive"
        assert intent.shopping_intent == "product_search"


def test_gift_without_category_asks_one_question_using_real_categories():
    decision = AmbiguityClarificationAgent().evaluate(
        deterministic_extract_intent(
            "Suggest a birthday gift for my girlfriend under ₹50,000"
        )
    )

    assert decision.needs_clarification is True
    assert "What type of product" in decision.clarification_question
    assert decision.suggested_options
    assert "Beauty & Personal Care" in decision.suggested_options


def test_hard_category_and_budget_filters_precede_hybrid_retrieval(monkeypatch):
    products = [
        _product("beauty-1", "Dior fragrance", "beauty_personal_care", 20000),
        _product("beauty-2", "Skincare set", "beauty_personal_care", 25000),
        _product("tech-1", "Tablet", "electronics", 30000),
        _product("beauty-over", "Beauty device", "beauty_personal_care", 60000),
    ]

    class FakeIndex:
        products_by_id = {product.product_id: product for product in products}

        def search(self, query, allowed_product_ids, limit):
            ids = sorted(allowed_product_ids)[:limit]
            return HybridSearchResult(
                bm25_ids=ids,
                semantic_ids=ids,
                product_ids=ids,
                rrf_scores={product_id: 100.0 for product_id in ids},
                retrieval_sources={product_id: ["bm25", "semantic"] for product_id in ids},
                semantic_available=True,
                retrieval_mode="hybrid",
                latency_ms={},
            )

    monkeypatch.setattr(
        "app.agents.candidate_retrieval.get_hybrid_catalog_index",
        lambda catalog: FakeIndex(),
    )
    intent = ExtractedIntent(
        category="beauty_personal_care",
        category_is_explicit=True,
        budget_max=50000,
        budget_currency="INR",
        is_budget_strict=True,
    )
    result = CandidateRetrievalAgent(catalog=products).retrieve(
        intent,
        AttributeMappingResult(normalized_category="beauty_personal_care"),
        query_text="beauty gift",
    )

    assert {product.category for product in result.candidates} == {
        "beauty_personal_care"
    }
    assert all(product.price <= 50000 for product in result.candidates)


def test_soft_feature_unknown_does_not_reject_product_as_a_hard_failure():
    product = _product("soft-feature", "Outdoor shoes", "footwear")
    intent = ExtractedIntent(
        category="footwear",
        category_is_explicit=True,
        feature_preferences=["waterproof"],
    )

    assert evaluate_hard_constraints(product, intent).is_eligible
    assert evaluate_recommendation_candidate(product, intent).is_eligible


def test_usd_ranking_benchmark_is_not_serialized_to_client():
    product = _product("currency-check", "Catalog item", "electronics")

    assert "normalized_price_usd" not in product.model_dump()


def test_session_memory_clears_removed_budget_and_category():
    memory = SessionMemoryAgent()
    session_id = "removed-budget-regression"
    memory.reset_session(session_id)
    memory.update_session(
        session_id,
        ExtractedIntent(
            category="beauty_personal_care",
            budget_max=10000,
            budget_currency="INR",
        ),
    )
    updated = memory.update_session(
        session_id,
        ExtractedIntent(budget_unlimited=True),
    )

    assert "budget_max" not in updated.confirmed_constraints
    assert "category" not in updated.confirmed_constraints
    memory.reset_session(session_id)
