"""
Unit and Integration Tests for All 10 ShopSense AI Specialized Agents
Covers:
- Agent 1: Query Ingestion Agent (normalization, entity preservation, rejection)
- Agent 2: Intent and Constraint Extraction Agent (Pydantic schema, negations, strict vs flexible budget)
- Agent 3: Ambiguity and Clarification Agent (confidence gate, no repeated questions)
- Agent 4: Catalog Attribute Mapping Agent (synonyms, unit conversion, colloquial maps)
- Agent 5: Candidate Retrieval Agent (broad pool, hard constraints, exclusions, deduplication)
- Agent 6: Ranking and Fit Scoring Agent (deterministic weights, score breakdown, hard constraint disqualification)
- Agent 7: Explanation Generation Agent (evidence-grounded natural language justifications)
- Agent 8: Zero-Result and Fallback Agent (budget relaxation diffs, alternative suggestions)
- Agent 9: Session Memory Agent (turn tracking, constraint persistence, topic switching)
- Agent 10: Orchestrator Agent (end-to-end acceptance scenario & state transitions)
- FastAPI HTTP Chat Integration Test (/api/chat/)
"""

import pytest
from httpx import AsyncClient
from types import SimpleNamespace
import json

from app.models.state import (
    IngestedQuery,
    ExtractedIntent,
    PageProductEvidence,
    ProductFitScore,
    ProductRecommendation,
)
from app.agents.query_ingestion import QueryIngestionAgent
from app.agents.intent_extraction import IntentExtractionAgent
from app.agents.ambiguity_clarification import AmbiguityClarificationAgent
from app.agents.catalog_mapping import CatalogAttributeMappingAgent
from app.agents.candidate_retrieval import CandidateRetrievalAgent
from app.agents.ranking_fit import RankingFitScoringAgent
from app.agents.explanation_generation import ExplanationGenerationAgent
from app.agents.zero_result_fallback import ZeroResultFallbackAgent
from app.agents.session_memory import SessionMemoryAgent
from app.agents.orchestrator import OrchestratorAgent
from app.services.catalog_service import load_and_validate_catalog
from app.services.llm_service import deterministic_extract_intent


# ==========================================
# Agent 1: Query Ingestion Agent Tests
# ==========================================

def test_agent1_query_ingestion_valid():
    agent = QueryIngestionAgent()
    res = agent.ingest(
        session_id="sess_01",
        raw_message="   I need a   laptop under $1,000   with 16GB RAM, not black!   ",
        turn_id=1
    )
    assert not res.is_empty
    assert res.session_id == "sess_01"
    assert "$1,000" in res.sanitized_message
    assert "not black" in res.sanitized_message
    assert "  " not in res.sanitized_message


def test_agent1_query_ingestion_empty_rejection():
    agent = QueryIngestionAgent()
    res_empty = agent.ingest(session_id="sess_01", raw_message="    ")
    assert res_empty.is_empty
    assert res_empty.rejection_reason is not None

    res_symbols = agent.ingest(session_id="sess_01", raw_message="???")
    assert res_symbols.is_empty


# ==========================================
# Agent 2: Intent & Constraint Extraction Tests
# ==========================================

def test_agent2_intent_extraction_gift_and_budget():
    agent = IntentExtractionAgent()
    ingested = IngestedQuery(
        session_id="sess_02",
        raw_message="I need a birthday gift for my dad who enjoys hiking. Keep it under ₹8,000 and prioritize lightweight products.",
        sanitized_message="I need a birthday gift for my dad who enjoys hiking. Keep it under ₹8,000 and prioritize lightweight products."
    )
    intent = agent.extract(ingested)

    assert intent.shopping_intent == "gift_buying"
    assert intent.recipient == "dad"
    assert intent.occasion == "birthday"
    assert intent.intended_use == "hiking"
    assert intent.budget_max == 8000.0
    assert intent.budget_currency == "INR"
    assert intent.is_budget_strict is True
    assert "lightweight" in intent.soft_preferences
    assert intent.purchase_intent == "gift"
    assert any(
        constraint.name == "price"
        and constraint.operator == "<="
        and constraint.value == 8000.0
        for constraint in intent.explicit_constraints
    )


def test_agent2_intent_extraction_negation_and_flexibility():
    agent = IntentExtractionAgent()
    ingested = IngestedQuery(
        session_id="sess_02",
        raw_message="waterproof running shoes around ₹5,000 not leather",
        sanitized_message="waterproof running shoes around ₹5,000 not leather"
    )
    intent = agent.extract(ingested)

    assert intent.category == "footwear"
    assert intent.budget_max == 5000.0
    assert intent.budget_currency == "INR"
    assert intent.is_budget_strict is False  # "around" means flexible
    assert "leather" in intent.exclusions
    assert "waterproof" in intent.soft_preferences
    assert any(
        constraint.name == "price" and constraint.operator == "approximately"
        for constraint in intent.explicit_constraints
    )


def test_agent2_budget_defaults_to_inr_and_converts_foreign_amounts():
    unmarked_budget = deterministic_extract_intent("electronics under 20000")
    usd_budget = deterministic_extract_intent("headphones under $100")

    assert unmarked_budget.budget_max == 20000.0
    assert unmarked_budget.budget_currency == "INR"
    assert usd_budget.budget_max == 8333.33
    assert usd_budget.budget_currency == "INR"


def test_agent2_health_inference_remains_a_soft_preference():
    intent = deterministic_extract_intent("Comfortable hiking shoes for bad knees")

    assert intent.health_considerations == ["joint discomfort"]
    assert any(
        preference.value == "joint-friendly / low-impact"
        and preference.evidence == "bad knees"
        for preference in intent.implicit_constraints
    )
    assert "joint-friendly" in intent.soft_preferences
    assert "joint-friendly" not in intent.feature_preferences


def test_agent2_explicit_query_terms_override_incorrect_llm_category(monkeypatch):
    from app.agents import intent_extraction

    monkeypatch.setattr(
        intent_extraction,
        "extract_intent_with_llm",
        lambda query, history: ExtractedIntent(
            category="bags_accessories",
            subcategory="backpacks",
        ),
    )
    query = "Suggest a lightweight packable rain jacket"

    intent = IntentExtractionAgent().extract(
        IngestedQuery(
            session_id="rain-jacket-category-override",
            raw_message=query,
            sanitized_message=query,
        )
    )

    assert intent.category == "clothing"
    assert intent.subcategory == "jackets"
    assert intent.category_is_explicit is True
    assert intent.subcategory_is_explicit is True


def test_agent2_groq_structured_extraction(monkeypatch):
    from app.services import llm_service

    response_payload = {
        "shopping_intent": "gift_buying",
        "purchase_intent": "gift",
        "category": "footwear",
        "subcategory": "boots",
        "budget_max": 100.0,
        "budget_currency": "USD",
        "is_budget_strict": False,
        "soft_preferences": [],
        "explicit_constraints": [],
        "implicit_constraints": [
            {
                "value": "joint-friendly / low-impact",
                "evidence": "bad knees",
                "confidence": 0.8,
            }
        ],
        "health_considerations": ["joint discomfort"],
    }

    class FakeCompletions:
        captured_messages = []

        def create(self, **kwargs):
            self.captured_messages = kwargs["messages"]
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(response_payload))
                    )
                ]
            )

    completions = FakeCompletions()
    monkeypatch.setattr(
        llm_service,
        "groq_client",
        SimpleNamespace(chat=SimpleNamespace(completions=completions)),
    )
    monkeypatch.setattr(llm_service.settings, "MOCK_LLM_FOR_TESTS", False)

    query = "Gift boots around $100 for someone with bad knees"
    intent = llm_service.extract_intent_with_llm(query)

    assert intent.purchase_intent == "gift"
    assert intent.budget_max == 8333.33
    assert intent.budget_currency == "INR"
    assert any(
        constraint.name == "price" and constraint.operator == "approximately"
        for constraint in intent.explicit_constraints
    )
    assert intent.implicit_constraints[0].evidence == "bad knees"
    assert completions.captured_messages[-1] == {"role": "user", "content": query}


def test_agent2_followup_refinement_merging():
    agent = IntentExtractionAgent()
    # Turn 1
    t1_ingested = IngestedQuery(
        session_id="sess_02",
        raw_message="Find laptops under $1000",
        sanitized_message="Find laptops under $1000"
    )
    intent_t1 = agent.extract(t1_ingested)

    # Turn 2: Follow-up refinement
    t2_ingested = IngestedQuery(
        session_id="sess_02",
        raw_message="make it cheaper and only black",
        sanitized_message="make it cheaper and only black",
        turn_id=2
    )
    intent_t2 = agent.extract(t2_ingested, previous_intent=intent_t1)

    assert intent_t2.category == "electronics"
    assert intent_t2.subcategory == "laptops"
    assert intent_t2.budget_max == 66666.66  # 20% cheaper than INR equivalent of $1,000
    assert intent_t2.budget_currency == "INR"
    assert intent_t2.colour == "black"


def test_agent2_previous_intent_is_sent_as_extraction_context(monkeypatch):
    from app.agents import intent_extraction

    captured_history = []

    def fake_extract(_query, history):
        captured_history.extend(history)
        return ExtractedIntent()

    monkeypatch.setattr(intent_extraction, "extract_intent_with_llm", fake_extract)
    previous_intent = ExtractedIntent(
        shopping_intent="gift_buying",
        category="footwear",
        recipient="dad",
    )
    followup = IngestedQuery(
        session_id="sess_02",
        turn_id=2,
        raw_message="size 10",
        sanitized_message="size 10",
    )

    intent_extraction.IntentExtractionAgent().extract(
        followup,
        previous_intent=previous_intent,
    )

    assert len(captured_history) == 1
    assert captured_history[0]["role"] == "assistant"
    assert "structured shopping intent" in captured_history[0]["content"]
    assert '"recipient":"dad"' in captured_history[0]["content"]


# ==========================================
# Agent 3: Ambiguity & Clarification Tests
# ==========================================

def test_agent3_clarification_broad_query():
    agent = AmbiguityClarificationAgent(confidence_threshold=0.55)
    # Vague intent without budget, size, or activity
    vague_intent = ExtractedIntent(category="footwear")
    decision = agent.evaluate(vague_intent)

    assert decision.needs_clarification is True
    assert decision.clarification_question is not None
    assert len(decision.suggested_options) > 0


def test_agent3_clarification_sufficiently_clear_query():
    agent = AmbiguityClarificationAgent(confidence_threshold=0.55)
    # Clear query with category, activity, budget, and preference
    clear_intent = ExtractedIntent(
        category="footwear",
        intended_use="hiking",
        budget_max=5000.0,
        budget_currency="INR",
        soft_preferences=["waterproof"]
    )
    decision = agent.evaluate(clear_intent)

    # Should proceed autonomously without bothering user
    assert decision.needs_clarification is False
    assert decision.clarification_question is None


def test_agent3_gift_footwear_asks_for_missing_recipient_size():
    agent = AmbiguityClarificationAgent(confidence_threshold=0.55)
    intent = ExtractedIntent(
        shopping_intent="gift_buying",
        category="footwear",
        recipient="dad",
    )

    decision = agent.evaluate(intent)

    assert decision.needs_clarification is True
    assert decision.missing_critical_fields == ["recipient_size"]
    assert "size" in decision.clarification_question.lower()
    assert "size-free gift accessories" in decision.clarification_question.lower()
    assert decision.suggested_options == ["Show size-free gift accessories"]


def test_agent2_size_free_gift_choice_switches_away_from_sized_category():
    agent = IntentExtractionAgent()
    previous_intent = deterministic_extract_intent(
        "Birthday gift boots for my dad under $200"
    )
    followup = IngestedQuery(
        session_id="sess_02",
        turn_id=2,
        raw_message="Show size-free gift accessories",
        sanitized_message="Show size-free gift accessories",
    )

    intent = agent.extract(followup, previous_intent=previous_intent)

    assert intent.category is None
    assert intent.category_is_explicit is False
    assert intent.purchase_intent == "gift"
    assert intent.recipient == "dad"
    assert intent.budget_max == 16666.67
    assert intent.budget_currency == "INR"
    assert not any(constraint.name == "size" for constraint in intent.explicit_constraints)


def test_agent3_does_not_ask_for_gift_size_when_known():
    agent = AmbiguityClarificationAgent(confidence_threshold=0.55)
    intent = ExtractedIntent(
        shopping_intent="gift_buying",
        category="footwear",
        recipient="dad",
        size="10",
    )

    decision = agent.evaluate(intent)

    assert decision.needs_clarification is False
    assert "recipient_size" not in decision.missing_critical_fields


def test_agent3_no_repeated_questions():
    agent = AmbiguityClarificationAgent(confidence_threshold=0.55)
    vague_intent = ExtractedIntent()
    # First turn asks question
    d1 = agent.evaluate(vague_intent, already_asked_questions=[])
    assert d1.needs_clarification is True

    # Next turn with same question already recorded
    d2 = agent.evaluate(vague_intent, already_asked_questions=[d1.clarification_question])
    assert d2.needs_clarification is False, "Should not repeat identical question"


# ==========================================
# Agent 4: Catalog Attribute Mapping Tests
# ==========================================

def test_agent4_catalog_attribute_mapping():
    agent = CatalogAttributeMappingAgent()
    intent = ExtractedIntent(
        category="shoes",
        intended_use="walking",
        soft_preferences=["lightweight", "waterproof", "good for long walks"]
    )
    mapping = agent.map_attributes(intent)

    assert mapping.normalized_category == "footwear"
    assert "walking" in mapping.mapped_use_cases
    assert mapping.mapped_attributes["waterproof"] is True
    assert "weight_kg" in mapping.mapped_attributes
    assert len(mapping.explanations) > 0


# ==========================================
# Agent 5: Candidate Retrieval Tests
# ==========================================

def test_agent5_candidate_retrieval_and_exclusions():
    retrieval_agent = CandidateRetrievalAgent()
    mapping_agent = CatalogAttributeMappingAgent()

    # Query with strict budget and exclusion
    intent = ExtractedIntent(
        category="footwear",
        budget_max=130.0,
        budget_currency="USD",
        is_budget_strict=True,
        exclusions=["leather"]
    )
    mapping = mapping_agent.map_attributes(intent)
    result = retrieval_agent.retrieve(intent, mapping)

    assert result.total_found > 0
    for prod in result.candidates:
        # Strict ceiling respected
        assert prod.normalized_price_usd <= 130.0
        # Leather excluded
        desc_lower = (prod.product_name + " " + prod.description).lower()
        assert "leather" not in desc_lower


def test_laptop_search_excludes_other_electronics_and_explains_matches():
    intent = deterministic_extract_intent(
        "Find me a laptop for programming under ₹60,000"
    )
    mapping = CatalogAttributeMappingAgent().map_attributes(intent)
    retrieval = CandidateRetrievalAgent().retrieve(
        intent,
        mapping,
        enabled_stores=["local_catalog"],
    )
    ranked = RankingFitScoringAgent().rank(retrieval.candidates, intent)
    recommendations = ExplanationGenerationAgent().explain(ranked, intent)

    assert retrieval.candidates
    assert all(product.subcategory == "laptops" for product in retrieval.candidates)
    assert recommendations
    assert all(
        recommendation.product.subcategory == "laptops"
        for recommendation in recommendations
    )
    assert recommendations[0].fit_score.use_case_score == 0
    assert any("programming" in trade_off for trade_off in recommendations[0].trade_offs)
    assert "does not list it for programming" in recommendations[0].explanation
    assert all(
        "category:" not in benefit
        and "subcategory:" not in benefit
        and "budget_friendly" not in benefit
        for recommendation in recommendations
        for benefit in recommendation.key_benefits
    )
    assert all(
        "category:electronics" not in recommendation.explanation
        and "subcategory:laptops" not in recommendation.explanation
        and "budget_friendly" not in recommendation.explanation
        for recommendation in recommendations
    )

    charger = next(
        product
        for product in load_and_validate_catalog()
        if product.subcategory == "chargers"
    )
    charger_score = RankingFitScoringAgent().rank([charger], intent)[0][1]
    assert charger_score.is_eligible is False
    assert any(
        "does not match 'laptops'" in violation
        for violation in charger_score.violated_hard_constraints
    )


# ==========================================
# Agent 6: Ranking & Fit Scoring Tests
# ==========================================

def test_agent6_ranking_fit_scoring():
    retrieval_agent = CandidateRetrievalAgent()
    ranking_agent = RankingFitScoringAgent()
    mapping_agent = CatalogAttributeMappingAgent()

    intent = ExtractedIntent(
        category="electronics",
        subcategory="laptops",
        intended_use="programming",
        budget_max=1000.0,
        budget_currency="USD",
        soft_preferences=["lightweight"]
    )
    mapping = mapping_agent.map_attributes(intent)
    retrieval = retrieval_agent.retrieve(intent, mapping)
    ranked = ranking_agent.rank(retrieval.candidates, intent)

    assert len(ranked) >= 1
    top_prod, top_score = ranked[0]
    # ZenBook 14 ($899.99, lightweight 1.25kg, programming tags) should score high
    assert top_score.is_eligible is True
    assert top_score.total_score >= 70.0
    assert "category:electronics" in top_score.exact_matches


def test_agent6_distinct_products_do_not_all_tie():
    catalog = load_and_validate_catalog()
    products = [
        product for product in catalog
        if product.category == "footwear"
    ][:3]
    intent = deterministic_extract_intent(
        "running shoes under ₹16000 for daily running"
    )

    ranked = RankingFitScoringAgent().rank(products, intent)

    assert len({score.total_score for _, score in ranked}) > 1


# ==========================================
# Agent 7: Explanation Generation Tests
# ==========================================

def test_agent7_explanation_generation():
    retrieval_agent = CandidateRetrievalAgent()
    ranking_agent = RankingFitScoringAgent()
    explainer = ExplanationGenerationAgent()
    mapping_agent = CatalogAttributeMappingAgent()

    intent = ExtractedIntent(
        category="electronics",
        intended_use="programming",
        budget_max=1000.0,
        budget_currency="USD",
        soft_preferences=["lightweight"]
    )
    mapping = mapping_agent.map_attributes(intent)
    retrieval = retrieval_agent.retrieve(intent, mapping)
    ranked = ranking_agent.rank(retrieval.candidates, intent)
    recommendations = explainer.explain(ranked, intent, top_k=2)

    assert len(recommendations) >= 1
    top_rec = recommendations[0]
    assert top_rec.product is not None
    assert "recommend" in top_rec.explanation.lower()
    assert len(top_rec.key_benefits) > 0


def test_agent7_batches_grounded_narratives_with_page_specifications(monkeypatch):
    from app.services import llm_service

    product = load_and_validate_catalog()[0]
    recommendation = ProductRecommendation(
        product=product,
        fit_score=ProductFitScore(
            product_id=product.product_id,
            product_name=product.product_name,
            total_score=82.0,
            exact_matches=["category:electronics"],
        ),
        explanation="Deterministic explanation.",
    )
    intent = ExtractedIntent(
        page_analysis_requested=True,
        page_product=PageProductEvidence(
            product_name="Page Laptop",
            price=899.99,
            currency="USD",
            specifications={"RAM": "16GB", "Storage": "512GB SSD"},
        ),
    )
    completions_calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            completions_calls.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps({
                                "page_analysis": "The captured page lists 16GB RAM and 512GB SSD.",
                                "recommendations": [{
                                    "product_id": product.product_id,
                                    "explanation": "A catalog match with verified electronics category.",
                                }],
                            })
                        )
                    )
                ]
            )

    monkeypatch.setattr(
        llm_service,
        "groq_client",
        SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )
    monkeypatch.setattr(llm_service.settings, "MOCK_LLM_FOR_TESTS", False)

    updated, page_analysis = llm_service.generate_recommendation_narrative(
        [recommendation],
        intent,
    )

    assert len(completions_calls) == 1
    evidence = json.loads(completions_calls[0]["messages"][-1]["content"])
    assert evidence["page_product"]["specifications"]["RAM"] == "16GB"
    assert evidence["recommendations"][0]["product_id"] == product.product_id
    assert updated[0].explanation == "A catalog match with verified electronics category."
    assert page_analysis == "The captured page lists 16GB RAM and 512GB SSD."


# ==========================================
# Agent 8: Zero-Result Fallback Tests
# ==========================================

def test_agent8_zero_result_fallback_budget_relaxation():
    fallback_agent = ZeroResultFallbackAgent()
    # Unrealistic budget for a laptop ($5.00)
    strict_intent = ExtractedIntent(
        category="electronics",
        subcategory="laptops",
        budget_max=5.0,
        budget_currency="USD",
        is_budget_strict=True
    )
    suggestion = fallback_agent.generate_fallback(strict_intent)

    assert suggestion.fallback_needed is True
    assert len(suggestion.suggested_alternatives) > 0
    assert "budget" in suggestion.explanation.lower()


# ==========================================
# Agent 9: Session Memory Tests
# ==========================================

def test_agent9_session_memory():
    memory = SessionMemoryAgent()
    session_id = "test_mem_001"

    intent = ExtractedIntent(
        category="footwear",
        budget_max=100.0,
        budget_currency="USD",
        soft_preferences=["waterproof"]
    )
    session = memory.update_session(
        session_id=session_id,
        intent=intent,
        shown_product_ids=["prod_foot_001"],
        asked_question="What size?"
    )

    assert session.turn_count == 1
    assert session.confirmed_constraints["budget_max"] == 100.0
    assert "prod_foot_001" in session.shown_product_ids
    assert "What size?" in session.questions_asked

    # Test feedback
    memory.record_feedback(session_id, "prod_foot_001", accepted=False)
    assert "prod_foot_001" in session.rejected_product_ids


# ==========================================
# Agent 10: Orchestrator Agent & Acceptance Scenario
# ==========================================

def test_agent10_orchestrator_acceptance_scenario():
    """
    CRITICAL ACCEPTANCE CRITERIA:
    'I need a birthday gift for my dad who enjoys hiking. Keep it under ₹8,000 and prioritize lightweight products.'
    Must extract gift, occasion, recipient, activity, and budget without inventing a
    category; it should ask which catalog category to explore.
    """
    orchestrator = OrchestratorAgent()
    query = "I need a birthday gift for my dad who enjoys hiking. Keep it under ₹8,000 and prioritize lightweight products."

    response = orchestrator.process_turn(
        session_id="acceptance_sess_01",
        message=query,
        turn_id=1
    )

    assert response.action_taken == "clarify"
    assert response.clarification is not None
    assert response.recommendations == []
    assert "gift" in response.message.lower()
    intent = orchestrator.workflow.session_memory_agent.get_or_create_session(
        "acceptance_sess_01"
    ).current_intent
    assert intent is not None
    assert intent.category is None
    assert intent.budget_max == 8000
    assert intent.recipient == "dad"
    assert intent.occasion == "birthday"
    assert intent.intended_use == "hiking"


def test_agent10_orchestrator_clarification_flow():
    orchestrator = OrchestratorAgent()
    # Extremely vague request
    response = orchestrator.process_turn(
        session_id="clarify_sess_01",
        message="Find shoes",
        turn_id=1
    )
    assert response.action_taken == "clarify"
    assert response.clarification is not None
    assert response.clarification.needs_clarification is True
    assert len(response.clarification.suggested_options) > 0


def test_agent10_orchestrator_refinement_flow():
    orchestrator = OrchestratorAgent()
    sess_id = "refine_sess_01"

    # Turn 1
    res1 = orchestrator.process_turn(
        session_id=sess_id,
        message="Find lightweight laptop under $1000",
        turn_id=1
    )
    assert res1.action_taken == "recommend"

    # Turn 2: Refinement "make it cheaper"
    res2 = orchestrator.process_turn(
        session_id=sess_id,
        message="make it cheaper",
        turn_id=2
    )
    assert res2.action_taken in ("recommend", "fallback")
    # Verified that previous category (laptops) was preserved
    if res2.recommendations:
        for r in res2.recommendations:
            assert r.product.category == "electronics"


# ==========================================
# FastAPI HTTP Chat Endpoint Integration Test
# ==========================================

@pytest.mark.asyncio
async def test_api_chat_endpoint_e2e(async_client: AsyncClient):
    payload = {
        "message": "I need a birthday gift for my dad who enjoys hiking. Keep it under ₹8,000 and prioritize lightweight products.",
        "session_id": "api_test_sess_01",
        "turn_id": 1
    }
    response = await async_client.post("/api/chat/", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["action_taken"] == "clarify"
    assert data["recommendations"] == []
    assert "Available catalog categories" in data["message"]
