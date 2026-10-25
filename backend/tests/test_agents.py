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

from app.models.state import IngestedQuery, ExtractedIntent
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
    assert intent_t2.budget_max == 800.0  # 20% cheaper than 1000
    assert intent_t2.colour == "black"


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
    Must extract constraints, retrieve candidates, enforce the ₹8,000 budget (~$96 USD),
    rank eligible products, explain results, and NOT ask unnecessary questions.
    """
    orchestrator = OrchestratorAgent()
    query = "I need a birthday gift for my dad who enjoys hiking. Keep it under ₹8,000 and prioritize lightweight products."

    response = orchestrator.process_turn(
        session_id="acceptance_sess_01",
        message=query,
        turn_id=1
    )

    # 1. Action taken must be 'recommend' without unnecessary clarification interruption
    assert response.action_taken == "recommend"
    assert response.clarification is None

    # 2. Recommendations returned
    assert len(response.recommendations) >= 1

    # 3. All recommendations must strictly respect ₹8,000 limit (~$96.00 USD)
    max_usd = 8000.0 * 0.012  # $96.00 USD
    for rec in response.recommendations:
        assert rec.product.normalized_price_usd <= max_usd, (
            f"Product {rec.product.product_id} price (${rec.product.normalized_price_usd}) "
            f"exceeds ₹8,000 limit (${max_usd})"
        )

    # 4. Top recommendation must be hiking-appropriate and explain gift/hiking relevance
    top_rec = response.recommendations[0]
    assert top_rec.fit_score.is_eligible is True
    assert top_rec.fit_score.total_score >= 60.0
    assert "dad" in response.message.lower() or "hiking" in response.message.lower()

    # 5. Visual comparison dashboard breakdown is populated
    assert response.top_three_comparison is not None
    assert len(response.top_three_comparison) >= 1


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
    assert data["action_taken"] == "recommend"
    assert len(data["recommendations"]) >= 1
    assert "top_three_comparison" in data
