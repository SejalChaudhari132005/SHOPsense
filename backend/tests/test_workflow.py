"""
LangGraph Orchestration Workflow Test Suite
Verifies:
1. Clear request returns recommendations
2. Ambiguous request returns clarification without prematurely retrieving
3. Follow-up answer continues the same session and retrieves
4. Budget update reranks candidates and enforces strict ceiling
5. Request with no eligible candidates triggers fallback
6. New topic resets irrelevant constraints without leaking
7. Simulated model/source failure handled gracefully
8. Multi-session isolation with LangGraph checkpointing
"""

import logging

import pytest
from unittest.mock import patch

from app.agents.graph_orchestrator import ShopSenseWorkflow
from app.models.state import OrchestratorResponse


@pytest.fixture
def workflow():
    return ShopSenseWorkflow()


# ==========================================
# 1. Clear Request Test
# ==========================================

def test_workflow_clear_request_returns_recommendations(workflow: ShopSenseWorkflow):
    """A sufficiently clear request should navigate the graph directly to recommendations."""
    query = "Find lightweight waterproof running shoes under $150"
    response: OrchestratorResponse = workflow.execute_turn(
        session_id="wf_sess_clear_01",
        message=query,
        turn_id=1
    )

    assert response.action_taken == "recommend"
    assert response.clarification is None
    assert len(response.recommendations) >= 1

    top_rec = response.recommendations[0]
    assert top_rec.fit_score.is_eligible is True
    assert top_rec.product.normalized_price_usd <= 150.0
    assert "running" in " ".join(top_rec.product.use_cases).lower()


def test_workflow_ranks_requested_running_shoes_above_unrelated_shoes(workflow: ShopSenseWorkflow):
    """The requested running-shoe type should affect ranking, not just retrieval."""
    from app.models.state import ExtractedIntent

    intent = ExtractedIntent(
        category="footwear",
        subcategory="running shoes",
        budget_max=10_000.0,
        budget_currency="INR",
        is_budget_strict=True,
        intended_use="everyday and casual use",
    )
    with patch.object(workflow.intent_extraction_agent, "extract", return_value=intent):
        response = workflow.execute_turn(
            session_id="wf_sess_running_casual",
            message="I need running shoes with a budget of ₹10,000 for everyday and casual use",
            turn_id=1,
        )

    assert response.action_taken == "recommend"
    assert any(
        recommendation.product.product_id == "prod_foot_001"
        for recommendation in response.recommendations
    )
    assert response.recommendations[0].product.product_id != "prod_foot_004"
    assert not any(
        recommendation.product.product_id == "prod_foot_004"
        for recommendation in response.recommendations
    )


def test_workflow_logs_executed_agents_without_logging_query(caplog, workflow: ShopSenseWorkflow):
    """The terminal log should show executed workflow stages without echoing user text."""
    caplog.set_level(logging.INFO, logger="app.agents.graph_orchestrator")
    query = "Find lightweight waterproof running shoes under $150"

    response = workflow.execute_turn(
        session_id="wf_sess_agent_logs",
        message=query,
        turn_id=1
    )

    assert response.action_taken == "recommend"
    assert "[Workflow] START session=wf_sess_agent_logs turn=1 source=text" in caplog.text
    assert "[Agent 01/10] START Query Ingestion" in caplog.text
    assert "[Agent 02/10] DONE Intent & Constraint Extraction" in caplog.text
    assert "intent=" in caplog.text
    assert '"budget_max":150.0' in caplog.text
    assert "[Agent 03/10] DONE Ambiguity & Clarification" in caplog.text
    assert "decision=search confidence=" in caplog.text
    assert "clarification=" in caplog.text
    assert "decision_reason" in caplog.text
    assert "[Agent 04/10] DONE Catalog Attribute Mapping" in caplog.text
    assert "mapping=" in caplog.text
    assert "[Agent 05/10] DONE Candidate Retrieval" in caplog.text
    assert "candidates=" in caplog.text
    assert "candidate_preview=" in caplog.text
    assert "[Agent 06/10] DONE Ranking & Fit Scoring" in caplog.text
    assert "ranking_preview=" in caplog.text
    assert "[Agent 07/10] DONE Explanation Generation" in caplog.text
    assert "recommendation_preview=" in caplog.text
    assert "[Agent 10/10] DONE Orchestrator Response" in caplog.text
    assert "action=recommend" in caplog.text
    assert "final_recommendations=" in caplog.text
    assert "[Workflow] DONE session=wf_sess_agent_logs turn=1 action=recommend" in caplog.text
    assert query not in caplog.text


# ==========================================
# 2. Ambiguous Request Test
# ==========================================

def test_workflow_ambiguous_request_returns_clarification(caplog, workflow: ShopSenseWorkflow):
    """
    CRITICAL BEHAVIOR:
    An ambiguous request must return a clarification question.
    It must NOT trigger candidate retrieval as though the question had already been answered.
    """
    caplog.set_level(logging.INFO, logger="app.agents.graph_orchestrator")
    query = "Find shoes"
    response: OrchestratorResponse = workflow.execute_turn(
        session_id="wf_sess_ambig_01",
        message=query,
        turn_id=1
    )

    assert response.action_taken == "clarify"
    assert response.clarification is not None
    assert response.clarification.needs_clarification is True
    assert response.clarification.clarification_question is not None
    assert "[Agent 03/10] DONE Ambiguity & Clarification" in caplog.text
    assert "decision=clarify" in caplog.text
    assert "needs_clarification" in caplog.text
    assert response.clarification.clarification_question in caplog.text
    assert "[Agent 05/10] START Candidate Retrieval" not in caplog.text
    # Retrieval MUST be empty
    assert len(response.recommendations) == 0


# ==========================================
# 3. Follow-up Answer Continues Session
# ==========================================

def test_workflow_followup_answer_continues_session(workflow: ShopSenseWorkflow):
    """
    On turn 2, the user answers the clarification question.
    The workflow merges context into the existing session state and resumes retrieval.
    """
    sess_id = "wf_sess_multiturn_01"

    # Turn 1: Vague query
    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="Find shoes",
        turn_id=1
    )
    assert res1.action_taken == "clarify"

    # Turn 2: Follow-up answer with details
    res2 = workflow.execute_turn(
        session_id=sess_id,
        message="trail running shoes for wet weather under $130",
        turn_id=2
    )
    assert res2.action_taken == "recommend"
    assert len(res2.recommendations) >= 1
    # Verify TerraStride trail shoes returned
    assert any("TerraStride" in r.product.product_name for r in res2.recommendations)


def test_workflow_exact_product_query_survives_budget_followup(workflow: ShopSenseWorkflow):
    """An exact catalog product must not be hidden by broad category keywords or result limits."""
    sess_id = "wf_sess_cricket_helmet_budget"

    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="suggest a cricket helmet",
        turn_id=1,
    )
    assert res1.action_taken == "clarify"

    res2 = workflow.execute_turn(
        session_id=sess_id,
        message="Under $100",
        turn_id=2,
    )

    assert res2.action_taken == "recommend"
    assert any(r.product.product_id == "dummyjson_144" for r in res2.recommendations)
    helmet = next(r.product for r in res2.recommendations if r.product.product_id == "dummyjson_144")
    assert helmet.normalized_price_usd <= 100.0
    assert helmet.image_url == (
        "https://cdn.dummyjson.com/product-images/"
        "sports-accessories/cricket-helmet/thumbnail.webp"
    )
    assert all(r.product.category == "fitness_outdoor" for r in res2.recommendations)


def test_workflow_packable_rain_jacket_is_not_misclassified_as_a_bag(workflow: ShopSenseWorkflow):
    response = workflow.execute_turn(
        session_id="wf_sess_packable_rain_jacket",
        message="Suggest a lightweight packable rain jacket",
        turn_id=1,
    )

    assert response.action_taken == "recommend"
    assert any(
        recommendation.product.product_id == "prod_cloth_001"
        for recommendation in response.recommendations
    )
    assert all(
        recommendation.product.category == "clothing"
        and recommendation.product.subcategory == "jackets"
        for recommendation in response.recommendations
    )


def test_workflow_travel_adapter_honors_inr_budget_and_type(workflow: ShopSenseWorkflow):
    response = workflow.execute_turn(
        session_id="wf_sess_travel_adapter",
        message="I need a universal travel adapter under \u20b92,500",
        turn_id=1,
    )

    assert response.action_taken == "recommend"
    assert [recommendation.product.product_id for recommendation in response.recommendations] == [
        "prod_trav_002"
    ]
    assert response.recommendations[0].product.price <= 2500


def test_workflow_named_comparison_uses_only_requested_products(workflow: ShopSenseWorkflow):
    response = workflow.execute_turn(
        session_id="wf_sess_audio_comparison",
        message="Compare QuietPulse 750 headphones and SonicBuds Sport earbuds",
        turn_id=1,
    )

    expected_ids = {"prod_elec_004", "prod_elec_005"}
    assert response.action_taken == "recommend"
    assert {recommendation.product.product_id for recommendation in response.recommendations} == expected_ids
    assert {
        comparison["product_id"]
        for comparison in response.top_three_comparison or []
    } == expected_ids

    over_budget = workflow.execute_turn(
        session_id="wf_sess_audio_comparison",
        message="Under $100",
        turn_id=2,
    )
    assert over_budget.action_taken == "fallback"
    assert all(
        product.product_id in expected_ids
        for product in over_budget.fallback.suggested_alternatives
    )


# ==========================================
# 4. Budget Update Reranks Candidates
# ==========================================

def test_workflow_budget_update_reranks_candidates(workflow: ShopSenseWorkflow):
    """
    Updating budget on turn 2 strictly eliminates products above the new ceiling
    and recalculates top rankings.
    """
    sess_id = "wf_sess_budget_rerank_01"

    # Turn 1: High budget ($1600) allows DevBook Pro 16 ($1499) and ZenBook 14 ($899)
    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="Laptop for programming under $1600",
        turn_id=1
    )
    assert res1.action_taken == "recommend"
    assert any(r.product.product_id == "prod_elec_002" for r in res1.recommendations)
    assert any(r.product.product_id == "prod_elec_001" for r in res1.recommendations)

    # Turn 2: User lowers budget: "actually, reduce my budget to $900"
    res2 = workflow.execute_turn(
        session_id=sess_id,
        message="actually, reduce my budget to $900",
        turn_id=2
    )
    assert res2.action_taken == "recommend"
    # DevBook Pro ($1499) MUST be eliminated by strict ceiling
    for rec in res2.recommendations:
        assert rec.product.normalized_price_usd <= 900.0

    assert not any(r.product.product_id == "prod_elec_002" for r in res2.recommendations)
    # ZenBook Ultra 14 ($899.99) now ranks #1
    top_prod_t2 = res2.recommendations[0].product
    assert top_prod_t2.product_id == "prod_elec_001"
    assert all(rec.product.currency == "INR" for rec in res2.recommendations)
    assert all(rec.product.normalized_price_usd <= 900.0 for rec in res2.recommendations)


def test_workflow_unsupported_product_type_lists_available_categories(workflow: ShopSenseWorkflow):
    """Unsupported product types should explain the actual catalog categories."""
    from app.models.state import ExtractedIntent

    intent = ExtractedIntent(category="bags_accessories", subcategory="necklaces")
    with patch.object(workflow.intent_extraction_agent, "extract", return_value=intent):
        response = workflow.execute_turn(
            session_id="wf_sess_unsupported_category",
            message="I want a necklace",
            turn_id=1,
        )

    assert response.action_taken == "clarify"
    assert "doesn't currently offer necklaces" in response.message
    for category in (
        "Footwear",
        "Clothing",
        "Electronics",
        "Travel Accessories",
        "Fitness & Outdoor",
        "Home & Kitchen",
        "Bags & Accessories",
    ):
        assert category in response.message
    assert response.clarification is not None
    assert response.clarification.catalog_coverage_feasible is False


def test_inferred_knee_brace_does_not_block_downhill_hiking_retrieval(
    workflow: ShopSenseWorkflow,
):
    """An inferred unsupported label must not override a semantic catalog match."""
    from app.models.state import ExtractedIntent

    llm_intent = ExtractedIntent(
        category="fitness_outdoor",
        category_is_explicit=False,
        subcategory="knee brace",
        intended_use="downhill hiking",
    )
    with patch(
        "app.agents.intent_extraction.extract_intent_with_llm",
        return_value=llm_intent,
    ):
        response = workflow.execute_turn(
            session_id="wf_sess_knee_support_semantic",
            message="need something to ease knee strain on downhill hikes",
            turn_id=1,
        )

    assert response.action_taken == "recommend"
    assert any(
        recommendation.product.product_id == "prod_fit_004"
        for recommendation in response.recommendations
    )


# ==========================================
# 5. Request with No Eligible Candidates
# ==========================================

def test_workflow_no_eligible_candidates_triggers_fallback(workflow: ShopSenseWorkflow):
    """
    When strict constraints yield zero matches, the graph branches to ZeroResultFallback.
    """
    query = "Find a laptop under $10 with 64GB RAM"
    response = workflow.execute_turn(
        session_id="wf_sess_fallback_01",
        message=query,
        turn_id=1
    )

    assert response.action_taken == "fallback"
    assert response.fallback is not None
    assert response.fallback.fallback_needed is True
    assert len(response.fallback.suggested_alternatives) >= 1
    assert "budget" in response.fallback.explanation.lower()


# ==========================================
# 6. New Topic Resets Irrelevant Constraints
# ==========================================

def test_workflow_new_topic_resets_irrelevant_constraints(workflow: ShopSenseWorkflow):
    """
    A topic switch (e.g. 'now find a travel bag') must clear old shoe-specific constraints
    (such as size 10 or footwear category).
    """
    sess_id = "wf_sess_topic_switch_01"

    # Turn 1: Footwear with size 10
    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="Find running shoes size 10 in black",
        turn_id=1
    )
    assert res1.action_taken == "recommend"

    # Turn 2: Complete topic switch
    res2 = workflow.execute_turn(
        session_id=sess_id,
        message="now find a travel bag under $120 for weekend trips",
        turn_id=2
    )
    assert res2.action_taken == "recommend"
    for r in res2.recommendations:
        assert r.product.category == "bags_accessories"
        # Shoes must not be returned
        assert r.product.category != "footwear"


# ==========================================
# 7. Model / Source Failure Resilience
# ==========================================

def test_workflow_model_failure_resilience(workflow: ShopSenseWorkflow):
    """
    If the LLM service raises an unexpected timeout or error, the workflow
    recovers gracefully with deterministic fallback rather than crashing.
    """
    with patch("app.agents.intent_extraction.extract_intent_with_llm", side_effect=TimeoutError("Groq API timed out")):
        response = workflow.execute_turn(
            session_id="wf_sess_fail_01",
            message="Find hiking boots under $200",
            turn_id=1
        )
        # Even with LLM timeout, deterministic fallback extracts and returns valid recommendations
        assert response.action_taken in ("recommend", "clarify")
        assert response.message is not None


# ==========================================
# 8. Multi-Session Isolation Test
# ==========================================

def test_workflow_multi_session_isolation(workflow: ShopSenseWorkflow):
    """
    Ensures that concurrent or separate sessions maintain isolated state in LangGraph.
    """
    sess_laptop = "sess_laptop_user"
    sess_tent = "sess_tent_user"

    # User A searches laptops
    res_a = workflow.execute_turn(session_id=sess_laptop, message="Find laptop under $1000", turn_id=1)
    assert res_a.action_taken == "recommend"
    assert res_a.recommendations[0].product.category == "electronics"

    # User B searches tents
    res_b = workflow.execute_turn(session_id=sess_tent, message="Find ultralight tent under $300", turn_id=1)
    assert res_b.action_taken == "recommend"
    assert res_b.recommendations[0].product.category == "fitness_outdoor"

    # User A follows up: "make it cheaper" -> must stay in laptop category!
    res_a2 = workflow.execute_turn(session_id=sess_laptop, message="make it cheaper", turn_id=2)
    assert res_a2.action_taken in ("recommend", "fallback")
    if res_a2.recommendations:
        assert res_a2.recommendations[0].product.category == "electronics"
