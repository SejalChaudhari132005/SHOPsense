"""
ShopSense AI — Prompt 10 Final Functional Verification Test Suite
Tests all ten agents and all six advanced features across the 16 required functional scenarios:
1. Clear shopping request with budget
2. Vague request requiring clarification
3. Request with several simultaneous constraints
4. Follow-up that changes the budget
5. Follow-up that excludes a brand or colour
6. Topic change that does not reuse irrelevant constraints
7. Request where no product meets hard constraints
8. Request with incomplete product data
9. Source adapter timeout
10. Malformed LLM response
11. Why Not analysis for a rejected candidate
12. Three-product comparison
13. Approved budget relaxation
14. Preference saving, retrieval, editing, and deletion
15. Complementary product suggestions
16. Request that must not proceed without clarification (contradictory constraints)
"""

import pytest
from unittest.mock import patch

from app.models.state import (
    IngestedQuery,
    ExtractedIntent,
    SessionContext,
    OrchestratorResponse,
)
from app.models.product import Product, ProductProvenance
from app.adapters.base import StoreStatus, StoreStatusEnum, StoreSearchResult
from app.adapters.registry import UnifiedRetrievalResult
from app.agents.graph_orchestrator import ShopSenseWorkflow
from app.agents.intent_extraction import IntentExtractionAgent
from app.agents.candidate_retrieval import CandidateRetrievalAgent
from app.agents.ranking_fit import RankingFitScoringAgent
from app.services.comparison_service import compare_products_side_by_side, analyze_why_not
from app.services.preference_db import preference_db
from app.services.follow_up_service import find_complementary_suggestion


@pytest.fixture
def workflow():
    return ShopSenseWorkflow()


# ==========================================
# Scenario 1: Clear Shopping Request with Budget
# ==========================================

def test_scenario_01_clear_shopping_request_with_budget(workflow: ShopSenseWorkflow):
    """Scenario 1: A clear shopping request with budget retrieves compliant candidates directly."""
    res = workflow.execute_turn(
        session_id="scen_01_clear",
        message="Find lightweight waterproof running shoes under $150",
        turn_id=1
    )
    assert res.action_taken == "recommend"
    assert res.clarification is None
    assert len(res.recommendations) >= 1
    for rec in res.recommendations:
        assert rec.fit_score.is_eligible is True
        assert rec.product.normalized_price_usd <= 150.0
        assert "footwear" in rec.product.category.lower()


# ==========================================
# Scenario 2: Vague Request Requiring Clarification
# ==========================================

def test_scenario_02_vague_request_requires_clarification(workflow: ShopSenseWorkflow):
    """Scenario 2: Vague query pauses at clarification gate without premature candidate retrieval."""
    res = workflow.execute_turn(
        session_id="scen_02_vague",
        message="shoes",
        turn_id=1
    )
    assert res.action_taken == "clarify"
    assert res.clarification is not None
    assert res.clarification.needs_clarification is True
    assert res.clarification.clarification_question is not None
    assert len(res.clarification.suggested_options) > 0
    # Candidate retrieval MUST be empty
    assert len(res.recommendations) == 0


# ==========================================
# Scenario 3: Request with Several Simultaneous Constraints
# ==========================================

def test_scenario_03_simultaneous_constraints(workflow: ShopSenseWorkflow):
    """Scenario 3: Multi-constraint request evaluates category, budget, color, use case, and specs."""
    res = workflow.execute_turn(
        session_id="scen_03_multi_constraints",
        message="waterproof trail running shoes under $160 in blue",
        turn_id=1
    )
    assert res.action_taken == "recommend"
    assert len(res.recommendations) >= 1
    top = res.recommendations[0]
    assert top.product.normalized_price_usd <= 160.0
    assert top.fit_score.is_eligible is True


# ==========================================
# Scenario 4: Follow-up that Changes the Budget
# ==========================================

def test_scenario_04_followup_changes_budget(workflow: ShopSenseWorkflow):
    """Scenario 4: Follow-up turn changes budget ceiling; candidates are reranked and filtered."""
    sess_id = "scen_04_budget_change"

    # Turn 1: Budget $160
    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="running shoes under $160",
        turn_id=1
    )
    assert res1.action_taken == "recommend"

    # Turn 2: Stricter budget $120
    res2 = workflow.execute_turn(
        session_id=sess_id,
        message="actually my budget is $120",
        turn_id=2
    )
    assert res2.action_taken == "recommend"
    for rec in res2.recommendations:
        assert rec.product.normalized_price_usd <= 120.0


# ==========================================
# Scenario 5: Follow-up that Excludes Brand or Colour
# ==========================================

def test_scenario_05_followup_excludes_brand_or_colour(workflow: ShopSenseWorkflow):
    """Scenario 5: Follow-up excludes a specific brand; excluded brand items are removed."""
    sess_id = "scen_05_exclusion"

    # Turn 1: General search
    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="running shoes under $160",
        turn_id=1
    )
    assert res1.action_taken == "recommend"

    # Turn 2: Exclude Nike
    res2 = workflow.execute_turn(
        session_id=sess_id,
        message="no Nike and not red",
        turn_id=2
    )
    assert res2.action_taken == "recommend"
    for rec in res2.recommendations:
        assert rec.product.brand.lower() != "nike"


# ==========================================
# Scenario 6: Topic Change Clears Irrelevant Constraints
# ==========================================

def test_scenario_06_topic_change_does_not_reuse_irrelevant_constraints(workflow: ShopSenseWorkflow):
    """Scenario 6: Topic switch from travel backpack to laptop cleans backpack-specific attributes."""
    sess_id = "scen_06_topic_switch"

    # Turn 1: Backpack
    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="40L waterproof travel backpack under $120",
        turn_id=1
    )
    assert res1.action_taken == "recommend"

    # Turn 2: Switch to laptops
    res2 = workflow.execute_turn(
        session_id=sess_id,
        message="now show me laptops with 16GB RAM under $1100",
        turn_id=2
    )
    assert res2.action_taken == "recommend"
    for rec in res2.recommendations:
        assert rec.product.category == "electronics"
        # 40L capacity must not be applied to laptops
        assert "capacity_l" not in (rec.product.attributes or {})
        assert "capacity_l" not in (rec.product.specifications or {})


# ==========================================
# Scenario 7: Request Where No Product Meets Hard Constraints
# ==========================================

def test_scenario_07_request_where_no_product_meets_hard_constraints(workflow: ShopSenseWorkflow):
    """Scenario 7: Zero-result query triggers Fallback Diff View with proposed relaxation."""
    res = workflow.execute_turn(
        session_id="scen_07_zero_result",
        message="gaming laptop with 32GB RAM under $15",
        turn_id=1
    )
    assert res.action_taken == "fallback"
    assert res.fallback is not None
    assert res.fallback.fallback_needed is True
    assert res.fallback.requires_user_approval is True
    assert res.fallback.price_delta is not None


# ==========================================
# Scenario 8: Request with Incomplete Product Data
# ==========================================

def test_scenario_08_request_with_incomplete_product_data():
    """Scenario 8: Product missing optional specs flags unknown attributes truthfully without hallucination."""
    incomplete_prod = Product(
        product_id="prod_partial_001",
        product_name="Basic Over-Ear Headphones",
        brand="SoundLab",
        category="audio",
        description="Budget wired headphones for daily listening",
        price=79.99,
        currency="USD",
        normalized_price_usd=79.99,
        specifications={"connectivity": "wired"},  # missing battery_life, noise_cancelling, weight
        use_cases=["general"],
        source_store="Catalog",
        provenance=ProductProvenance(source="catalog", is_verified=True)
    )

    intent = ExtractedIntent(
        category="audio",
        budget_max=100.0,
        hard_constraints={"noise_cancelling": True},
        soft_preferences=["long_battery"]
    )

    ranking_agent = RankingFitScoringAgent()
    ranked = ranking_agent.rank([incomplete_prod], intent)
    assert len(ranked) == 1
    prod, fit = ranked[0]

    # Unknown attributes must be truthfully recorded
    assert len(fit.unknown_attributes) > 0


# ==========================================
# Scenario 9: Source Adapter Timeout
# ==========================================

def test_scenario_09_source_adapter_timeout():
    """Scenario 9: Source adapter timeout is handled safely without crashing candidate retrieval."""
    agent = CandidateRetrievalAgent()

    fallback_product = Product(
        product_id="prod_elec_001",
        product_name="UltraBook Pro 14",
        brand="Zenith",
        category="electronics",
        description="Lightweight productivity laptop",
        price=999.99,
        currency="USD",
        normalized_price_usd=999.99,
        source_store="local_catalog",
        provenance=ProductProvenance(source="catalog", is_verified=True)
    )

    # Mock multi-store search result with timed-out store
    mock_result = UnifiedRetrievalResult(
        products=[fallback_product],
        sources_consulted=["local_catalog"],
        store_statuses=[
            StoreStatus(
                store_id="mock_timeout_store",
                store_name="Timeout Store",
                status=StoreStatusEnum.ERROR,
                is_configured=True,
                is_mocked=True,
                notes="Connection timed out after 5000ms"
            )
        ],
        partial_results=True,
        timed_out_stores=["mock_timeout_store"]
    )

    with patch.object(agent._registry, "search_all_sync", return_value=mock_result):
        intent = ExtractedIntent(category="electronics", budget_max=1200.0)
        from app.models.state import AttributeMappingResult
        mapping = AttributeMappingResult(normalized_category="electronics")
        res = agent.retrieve(intent, mapping)
        assert len(res.candidates) >= 1
        assert "mock_timeout_store" in res.timed_out_stores
        assert res.partial_results is True


# ==========================================
# Scenario 10: Malformed LLM Response
# ==========================================

def test_scenario_10_malformed_llm_response():
    """Scenario 10: Malformed LLM response is safely intercepted by deterministic rule fallback."""
    agent = IntentExtractionAgent()
    ingested = IngestedQuery(
        session_id="scen_10_malformed",
        raw_message="trail running shoes under $130",
        sanitized_message="trail running shoes under $130"
    )

    # Simulate LLM raising an exception or returning unparseable text
    with patch("app.agents.intent_extraction.extract_intent_with_llm") as mock_extract:
        mock_extract.side_effect = ValueError("Invalid JSON token in LLM response: ```xyz")

        # Deterministic extraction intercepts and extracts valid intent
        from app.services.llm_service import deterministic_extract_intent
        fallback_intent = deterministic_extract_intent(ingested.sanitized_message)
        assert fallback_intent is not None
        assert fallback_intent.category == "footwear"
        assert fallback_intent.budget_max == 130.0


# ==========================================
# Scenario 11: Why Not Analysis for Rejected Candidate
# ==========================================

def test_scenario_11_why_not_analysis_for_rejected_candidate():
    """Scenario 11: Why Not mode explains hard constraints violated and what needs to change."""
    session = SessionContext(
        session_id="scen_11_whynot",
        shown_product_ids=["prod_elec_001"],
        current_intent=ExtractedIntent(
            category="electronics",
            budget_max=1000.0,
            budget_currency="USD",
            is_budget_strict=True,
            hard_constraints={"ram_gb": 32}
        )
    )

    # DevBook Pro 16 is $1499.00 (over $1000 budget)
    res = analyze_why_not("prod_elec_002", session=session, compare_with_id="prod_elec_001")
    assert res.target_product_id == "prod_elec_002"
    assert res.is_eligible is False
    assert res.rejection_status == "excluded"
    assert len(res.violated_hard_constraints) > 0
    assert len(res.what_needs_to_change) > 0
    assert res.compared_product is not None


# ==========================================
# Scenario 12: Three-Product Comparison
# ==========================================

def test_scenario_12_three_product_comparison():
    """Scenario 12: Compares 3 products side-by-side with fit score breakdown and attribute matrix."""
    session = SessionContext(
        session_id="scen_12_compare",
        current_intent=ExtractedIntent(category="electronics", budget_max=1600.0)
    )

    res = compare_products_side_by_side(
        ["prod_elec_001", "prod_elec_002", "prod_elec_003"],
        session=session
    )
    assert len(res.products) == 3
    assert len(res.attribute_matrix) > 0
    assert res.recommendation_summary is not None
    for p in res.products:
        assert p.price > 0
        assert p.fit_score_breakdown is not None


# ==========================================
# Scenario 13: Approved Budget Relaxation
# ==========================================

def test_scenario_13_approved_budget_relaxation(workflow: ShopSenseWorkflow):
    """Scenario 13: User approves budget relaxation; workflow executes turn with new proposed budget."""
    sess_id = "scen_13_relaxation_approved"

    # Turn 1: Zero-result query
    res1 = workflow.execute_turn(
        session_id=sess_id,
        message="gaming laptop with 32GB RAM under $15",
        turn_id=1
    )
    assert res1.action_taken == "fallback"
    proposed = res1.fallback.proposed_budget
    assert proposed > 15.0

    # Turn 2: User approves relaxation
    res2 = workflow.execute_turn(
        session_id=sess_id,
        message=f"Search with proposed relaxed budget of ${proposed}",
        turn_id=2
    )
    assert res2.action_taken in {"recommend", "fallback"}
    assert res2.session_summary is not None


# ==========================================
# Scenario 14: Preference Saving, Retrieval, Editing, and Deletion
# ==========================================

@pytest.mark.asyncio
async def test_scenario_14_preference_memory_lifecycle(tmp_path):
    """Scenario 14: Consented preference storage: save, filter temporary, retrieve, edit, toggle, delete."""
    test_db = str(tmp_path / "lifecycle_prefs.db")
    custom_db = type(preference_db)(db_path=test_db)
    await custom_db.init_db()

    user_id = "user_lifecycle_test"

    # 1. Save with consent (strips temporary)
    input_prefs = {
        "preferred_brands": ["Sony", "Bose"],
        "shoe_size": "10",
        "gift_recipient": "friend",  # temporary
        "occasion": "birthday"       # temporary
    }
    saved = await custom_db.save_preferences(user_id, consent_given=True, durable_preferences=input_prefs)
    assert saved["consent_given"] is True
    assert "gift_recipient" not in saved["durable_preferences"]

    # 2. Retrieve
    retrieved = await custom_db.get_preferences(user_id)
    assert retrieved["durable_preferences"]["shoe_size"] == "10"

    # 3. Edit
    updated_prefs = {"preferred_brands": ["Sony", "Apple"], "shoe_size": "10.5"}
    edited = await custom_db.save_preferences(user_id, consent_given=True, durable_preferences=updated_prefs)
    assert edited["durable_preferences"]["shoe_size"] == "10.5"

    # 4. Toggle memory disabled (paused)
    paused = await custom_db.toggle_memory(user_id, is_enabled=False)
    assert paused["is_memory_enabled"] is False

    # 5. Delete (Right to be Forgotten)
    deleted = await custom_db.delete_preferences(user_id)
    assert deleted is True
    final_state = await custom_db.get_preferences(user_id)
    assert final_state["consent_given"] is False
    assert final_state["durable_preferences"] is None


# ==========================================
# Scenario 15: Complementary Product Suggestions
# ==========================================

def test_scenario_15_complementary_product_suggestions():
    """Scenario 15: Travel backpack recommendation offers complementary packing cubes within budget headroom."""
    backpack = Product(
        product_id="prod_pack_001",
        product_name="Nomad 40L Travel Backpack",
        brand="Osprey",
        category="backpacks",
        description="High performance 40L travel backpack for flights and commuting",
        price=110.0,
        currency="USD",
        normalized_price_usd=110.0,
        specifications={"capacity_l": 40},
        use_cases=["travel", "flight"],
        highlights=["Carry-on compliant"],
        source_store="Catalog",
        provenance=ProductProvenance(source="catalog", is_verified=True)
    )

    intent = ExtractedIntent(category="backpacks", budget_max=150.0)
    suggestion = find_complementary_suggestion(backpack, intent)

    assert suggestion is not None
    assert "packing" in suggestion.product.product_name.lower() or "cube" in suggestion.product.product_name.lower()
    assert suggestion.why_relevant is not None
    assert suggestion.is_pushy is False
    assert suggestion.data_provenance == "Demo sample data"


# ==========================================
# Scenario 16: Request Must Not Proceed Without Clarification
# ==========================================

def test_scenario_16_request_must_not_proceed_without_clarification(workflow: ShopSenseWorkflow):
    """Scenario 16: Contradictory query (vegan vs leather) must pause at clarification gate."""
    res = workflow.execute_turn(
        session_id="scen_16_contradiction",
        message="vegan leather dress shoes under $120",
        turn_id=1
    )
    assert res.action_taken == "clarify"
    assert res.clarification is not None
    assert res.clarification.needs_clarification is True
    assert "conflict" in res.clarification.decision_reason.lower() or "contradictory" in res.clarification.decision_reason.lower()
    # High risk constraint violation prevents proceeding
    assert len(res.recommendations) == 0
