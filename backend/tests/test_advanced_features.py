"""
ShopSense AI — Prompt 9 Advanced Features Test Suite
Tests all six advanced features and an end-to-end multi-feature scenario:
1. Why Not Mode (hard constraints, unknown attributes, what needs to change, rejection status, comparison)
2. Consented Preference Memory Across Sessions (durable vs temporary, view/edit/delete, toggle, user isolation)
3. Visual Comparison Dashboard (hard/soft satisfaction, fit breakdown, unknown attributes, freshness, trade-offs)
4. Budget-Relaxation Diff View (original vs proposed constraints, price delta, unmet requirements, approval flag)
5. Context-Aware Follow-Up Suggestions (utility explanation, non-pushy, <= 1 item, verified demonstration)
6. Confidence-Gated Autonomy (clear, ambiguous, contradictory, underspecified queries with decision_reason)
7. End-to-End Multi-Feature Scenario
"""

import pytest
from httpx import AsyncClient
from app.models.state import ExtractedIntent, SessionContext
from app.models.product import Product
from app.agents.orchestrator import OrchestratorAgent
from app.agents.ambiguity_clarification import AmbiguityClarificationAgent
from app.agents.zero_result_fallback import ZeroResultFallbackAgent
from app.services.comparison_service import compare_products_side_by_side, analyze_why_not
from app.services.preference_db import preference_db, separate_durable_from_temporary
from app.services.follow_up_service import find_complementary_suggestion


# ==========================================
# Feature 1: Why Not Mode Tests
# ==========================================

@pytest.mark.asyncio
async def test_why_not_mode_comprehensive():
    """
    Feature 1: Explains hard constraint violations, missed preferences, unknown attributes,
    rejection status ('excluded', 'ranked_lower', 'not_retrieved'), what needs to change,
    and side-by-side comparison with a recommended candidate.
    """
    session = SessionContext(
        session_id="sess_whynot_test_01",
        shown_product_ids=["prod_elec_001"],  # UltraBook Pro ($999.99)
        current_intent=ExtractedIntent(
            category="electronics",
            budget_max=1000.0,
            budget_currency="USD",
            is_budget_strict=True,
            hard_constraints={"ram_gb": 32},
            soft_preferences=["lightweight", "oled"]
        )
    )

    # 1. Product over budget and missing specs (DevBook Pro 16 - $1499.00)
    res = analyze_why_not("prod_elec_002", session=session, compare_with_id="prod_elec_001")
    assert res.target_product_id == "prod_elec_002"
    assert res.is_eligible is False
    assert res.was_retrieved is True
    assert res.rejection_status == "excluded"
    assert len(res.violated_hard_constraints) > 0
    assert len(res.what_needs_to_change) > 0
    # Price analysis
    assert res.price_analysis["is_over_budget"] is True
    # Direct comparison with UltraBook Pro
    assert res.compared_product is not None
    assert res.compared_product["product_id"] == "prod_elec_001"
    assert res.compared_product["price_difference_usd"] > 0

    # 2. Product in catalog but not retrieved / mismatched category
    sess_footwear = SessionContext(
        session_id="sess_footwear_test",
        shown_product_ids=["prod_foot_001"],
        current_intent=ExtractedIntent(category="footwear", budget_max=150.0)
    )
    # DevBook Pro is an electronics laptop, but user searched footwear
    res_not_retrieved = analyze_why_not("prod_elec_001", session=sess_footwear)
    assert res_not_retrieved.rejection_status in {"not_retrieved", "excluded"}
    assert any("category" in c.lower() for c in res_not_retrieved.violated_hard_constraints)


# ==========================================
# Feature 2: Preference Memory Across Sessions Tests
# ==========================================

@pytest.mark.asyncio
async def test_preference_memory_durable_vs_temporary_and_toggle(tmp_path):
    """
    Feature 2:
    - Explicit consent required
    - Durable preferences saved (brands, sizes, materials)
    - Temporary shopping constraints (recipient, occasion, gift) strictly excluded
    - Controls to view, edit, disable (toggle), and delete
    - User/profile isolation
    """
    test_db = str(tmp_path / "test_prefs.db")
    custom_db = type(preference_db)(db_path=test_db)
    await custom_db.init_db()

    user_a = "profile_user_alice"
    user_b = "profile_user_bob"

    # 1. Temporary constraints stripped from durable preferences
    raw_input = {
        "preferred_brands": ["Nike", "Patagonia"],
        "shoe_size": "9.5",
        "recipient": "uncle",
        "occasion": "wedding",
        "gift": True,
        "vegan": True
    }
    clean = separate_durable_from_temporary(raw_input)
    assert "recipient" not in clean
    assert "occasion" not in clean
    assert "gift" not in clean
    assert clean["shoe_size"] == "9.5"
    assert clean["vegan"] is True

    # 2. Rejection / wipe if consent not given
    res_no_consent = await custom_db.save_preferences(
        user_id=user_a,
        consent_given=False,
        preferred_brands=["Nike"]
    )
    assert res_no_consent["consent_given"] is False
    assert res_no_consent["preferences"] is None

    # 3. Save with affirmative consent
    res_save = await custom_db.save_preferences(
        user_id=user_a,
        consent_given=True,
        is_memory_enabled=True,
        preferred_categories=["footwear"],
        preferred_brands=["AlpineTrack"],
        shoe_size="9.5",
        durable_preferences={"vegan_only": True}
    )
    assert res_save["consent_given"] is True
    assert res_save["memory_status"] == "active"
    assert res_save["preferences"]["shoe_size"] == "9.5"
    assert res_save["preferences"]["vegan_only"] is True

    # 4. User profile isolation: Bob cannot access Alice's data
    bob_prefs = await custom_db.get_preferences(user_id=user_b)
    assert bob_prefs["consent_given"] is False
    assert bob_prefs["preferences"] is None

    # 5. Disable preference memory toggle
    toggled = await custom_db.toggle_memory(user_id=user_a, is_enabled=False)
    assert toggled["is_memory_enabled"] is False
    assert toggled["memory_status"] == "disabled"
    assert toggled["preferences"] is None

    # Re-enable
    re_enabled = await custom_db.toggle_memory(user_id=user_a, is_enabled=True)
    assert re_enabled["is_memory_enabled"] is True
    assert re_enabled["memory_status"] == "active"
    assert re_enabled["preferences"]["shoe_size"] == "9.5"

    # 6. Delete preferences (Right to be Forgotten)
    await custom_db.delete_preferences(user_id=user_a)
    wiped = await custom_db.get_preferences(user_id=user_a)
    assert wiped["consent_given"] is False
    assert wiped["preferences"] is None


# ==========================================
# Feature 3: Visual Comparison Dashboard Tests
# ==========================================

def test_visual_comparison_dashboard_rich_attributes():
    """
    Feature 3: Compares up to 3 products side-by-side with hard constraint satisfaction,
    soft preference matches, fit score breakdown, unknown attributes, freshness, and trade-offs.
    """
    intent = ExtractedIntent(
        category="footwear",
        budget_max=160.0,
        budget_currency="USD",
        hard_constraints={"waterproof": True},
        soft_preferences=["lightweight", "cushioned"]
    )
    session = SessionContext(session_id="sess_compare_rich", current_intent=intent)

    product_ids = ["prod_foot_001", "prod_foot_002", "prod_foot_003"]
    res = compare_products_side_by_side(product_ids, session=session)

    assert len(res.products) == 3
    for p in res.products:
        # Currency and normalized price
        assert p.price > 0.0
        assert p.currency in {"USD", "INR"}
        # Hard constraint satisfaction dict
        assert isinstance(p.hard_constraint_satisfaction, dict)
        assert "Within Budget" in p.hard_constraint_satisfaction
        # Soft preference matches
        assert isinstance(p.soft_preference_matches, list)
        # Fit score breakdown
        assert p.fit_score_breakdown is not None
        assert "category" in p.fit_score_breakdown
        assert "budget" in p.fit_score_breakdown
        # Unknown attributes tracking
        assert isinstance(p.unknown_attributes, list)
        # Freshness and store attribution
        assert len(p.data_source) > 0
        assert "Catalog" in p.freshness or "Live" in p.freshness
        # Trade-offs
        assert isinstance(p.trade_offs, list)

    # Attribute matrix
    assert len(res.attribute_matrix) > 0


# ==========================================
# Feature 4: Budget-Relaxation Diff View Tests
# ==========================================

def test_budget_relaxation_diff_view_and_approval():
    """
    Feature 4: When strict constraints yield zero results, computes explicit diff:
    original vs proposed budget, price delta, exact change made, remaining unmet requirements,
    and user approval requirement. Supports independent soft preference relaxation.
    """
    fallback_agent = ZeroResultFallbackAgent()

    # Case A: Budget relaxation (+25%)
    strict_budget_intent = ExtractedIntent(
        category="electronics",
        budget_max=600.0,  # Minimum laptop is $699.99
        budget_currency="USD",
        is_budget_strict=True,
        intended_use="programming laptop"
    )
    fallback = fallback_agent.generate_fallback(strict_budget_intent)

    assert fallback.fallback_needed is True
    assert fallback.original_budget == 600.0
    assert fallback.proposed_budget is not None
    assert fallback.proposed_budget > 600.0
    assert fallback.price_delta > 0.0
    assert len(fallback.exact_change_made) > 0
    assert fallback.requires_user_approval is True
    assert len(fallback.suggested_alternatives) > 0

    # Case B: Independent soft preference relaxation (preserves original budget)
    soft_pref_intent = ExtractedIntent(
        category="footwear",
        budget_max=160.0,
        budget_currency="USD",
        soft_preferences=["hyper_rare_unobtainable_colorway"],
        intended_use="trail running"
    )
    soft_fallback = fallback_agent.generate_fallback(soft_pref_intent)
    assert soft_fallback.fallback_needed is True
    assert soft_fallback.relaxation_type == "relax_soft_preference"
    assert soft_fallback.original_budget == 160.0
    assert soft_fallback.price_delta == 0.0
    assert len(soft_fallback.remaining_unmet_requirements) > 0


# ==========================================
# Feature 5: Context-Aware Follow-Up Suggestions Tests
# ==========================================

def test_context_aware_follow_up_suggestions():
    """
    Feature 5: Offers at most ONE relevant, non-pushy companion item.
    - Backpack -> Packing cubes
    - Running shoes -> Running socks
    - Verified demonstration provenance and utility explanation
    - Respects user budget and avoids aggressive upselling
    """
    # 1. Backpack pairing
    backpack = Product(
        product_id="test_backpack",
        product_name="Venture 40L Travel Backpack",
        brand="Venture",
        category="travel_accessories",
        price=120.0,
        currency="USD",
        normalized_price_usd=120.0,
        description="40-liter carry-on travel backpack.",
        tags=["backpack", "travel", "carry-on", "water-resistant"],
        source_store="DemoStore"
    )
    intent_travel = ExtractedIntent(category="travel_accessories", intended_use="2-week international trip")
    suggestion = find_complementary_suggestion(backpack, intent_travel)

    assert suggestion is not None
    assert suggestion.product.product_id == "acc_packing_cubes"
    assert "packing cubes" in suggestion.product.product_name.lower()
    assert len(suggestion.utility_explanation) > 10
    assert len(suggestion.why_relevant) > 5
    assert suggestion.is_pushy is False
    assert suggestion.data_provenance == "Verified Catalog Demonstration"

    # 2. Running shoe pairing
    shoe = Product(
        product_id="test_shoe",
        product_name="Alpine Trail Runner 2.0",
        brand="AlpineTrack",
        category="footwear",
        price=135.0,
        currency="USD",
        normalized_price_usd=135.0,
        description="High-traction trail running shoes.",
        tags=["running", "trail", "shoe"],
        source_store="DemoStore"
    )
    intent_running = ExtractedIntent(category="footwear", intended_use="trail marathon")
    shoe_suggestion = find_complementary_suggestion(shoe, intent_running)

    assert shoe_suggestion is not None
    assert shoe_suggestion.product.product_id == "acc_running_socks"
    assert "blister" in shoe_suggestion.utility_explanation.lower()

    # 3. Budget headroom respect: If user is on a strict razor-thin budget, do not push add-ons
    tight_intent = ExtractedIntent(
        category="travel_accessories",
        budget_max=121.0,
        is_budget_strict=True
    )
    # Primary item is $120 out of strict $121 max (>95%)
    tight_suggestion = find_complementary_suggestion(backpack, tight_intent)
    assert tight_suggestion is None  # Accurately suppressed to avoid over-budget upsell!


# ==========================================
# Feature 6: Confidence-Gated Autonomy Tests
# ==========================================

def test_confidence_gated_autonomy_scenarios():
    """
    Feature 6: Evaluates autonomy decisions based on:
    - Required-field completeness
    - Ambiguous phrases ('cheap', 'best' without bounds)
    - Conflicting constraints ('vegan' vs 'leather')
    - Catalog coverage
    - Risk of violating constraints
    Records decision_reason on all paths.
    """
    agent = AmbiguityClarificationAgent(confidence_threshold=0.55)

    # 1. Clear query: Should proceed autonomously
    clear_intent = ExtractedIntent(
        category="footwear",
        budget_max=150.0,
        budget_currency="USD",
        intended_use="trail running",
        size="10.5",
        colour="black"
    )
    dec_clear = agent.evaluate(clear_intent, raw_user_message="Black trail running shoes size 10.5 under $150")
    assert dec_clear.needs_clarification is False
    assert dec_clear.confidence_score >= 0.55
    assert "Proceeding autonomously" in dec_clear.decision_reason
    assert dec_clear.risk_assessment == "low"

    # 2. Underspecified query: Missing category & use case
    vague_intent = ExtractedIntent()
    dec_vague = agent.evaluate(vague_intent, raw_user_message="I want to buy something")
    assert dec_vague.needs_clarification is True
    assert "missing critical category" in dec_vague.decision_reason.lower()
    assert dec_vague.clarification_question is not None

    # 3. Ambiguous phrase without budget constraint: 'cheap'
    ambig_intent = ExtractedIntent(category="electronics", intended_use="cheap gear")
    dec_ambig = agent.evaluate(ambig_intent, raw_user_message="Find me the cheapest laptop")
    assert dec_ambig.needs_clarification is True
    assert any("cheap" in f for f in dec_ambig.ambiguity_factors)
    assert "ambiguous phrase" in dec_ambig.decision_reason.lower()

    # 4. Conflicting constraints: Vegan + Leather
    conflict_intent = ExtractedIntent(
        category="footwear",
        budget_max=120.0,
        hard_constraints={"material": "leather"},
        soft_preferences=["vegan", "eco-friendly"]
    )
    dec_conflict = agent.evaluate(conflict_intent, raw_user_message="Find vegan leather boots under $120")
    assert dec_conflict.needs_clarification is True
    assert dec_conflict.risk_assessment == "high"
    assert "conflicting constraints" in dec_conflict.decision_reason.lower()


# ==========================================
# End-to-End Multi-Feature Scenario Test
# ==========================================

@pytest.mark.asyncio
async def test_advanced_features_end_to_end_scenario(async_client: AsyncClient):
    """
    End-to-End Scenario integrating several features together:
    1. Consented user preferences saved in SQLite
    2. Specific shopping query runs through confidence-gated autonomy -> recommendation
    3. Context-aware follow-up accessory suggested alongside primary recommendations
    4. Why-Not mode invoked on an excluded alternative
    5. Side-by-side visual comparison dashboard invoked for top candidates
    6. Extreme refinement triggers budget-relaxation diff view with approval controls
    """
    user_id = "e2e_advanced_user_99"
    sess_id = "e2e_advanced_sess_99"

    # Step 1: Consented User Preferences
    pref_payload = {
        "user_id": user_id,
        "consent_given": True,
        "is_memory_enabled": True,
        "preferred_categories": ["footwear"],
        "shoe_size": "10",
        "durable_preferences": {"favorite_brand": "AlpineTrack"}
    }
    pref_res = await async_client.post("/api/preferences/", json=pref_payload)
    assert pref_res.status_code == 200
    assert pref_res.json()["memory_status"] == "active"

    # Step 2: Chat Query -> Recommendation + Context-Aware Follow-Up
    chat_payload = {
        "message": "Looking for trail running shoes under $150 size 10",
        "session_id": sess_id,
        "turn_id": 1
    }
    chat_res = await async_client.post("/api/chat/", json=chat_payload)
    assert chat_res.status_code == 200
    chat_data = chat_res.json()
    assert chat_data["action_taken"] == "recommend"
    assert len(chat_data["recommendations"]) >= 1

    # Verify context-aware follow-up suggestion was offered
    if chat_data.get("follow_up_suggestion"):
        follow_up = chat_data["follow_up_suggestion"]
        assert "socks" in follow_up["product"]["product_name"].lower()
        assert len(follow_up["utility_explanation"]) > 0

    # Step 3: Why-Not Analysis:
    # 3a. Candidate that is eligible but ranked lower (prod_foot_002)
    why_not_res = await async_client.post("/api/why-not/", json={
        "session_id": sess_id,
        "product_id": "prod_foot_002"
    })
    assert why_not_res.status_code == 200
    wn_data = why_not_res.json()
    assert wn_data["is_eligible"] is True
    assert wn_data["rejection_status"] == "ranked_lower"
    assert len(wn_data["better_alternatives"]) > 0

    # 3b. Candidate that was excluded due to category mismatch (prod_elec_001)
    why_not_excluded = await async_client.post("/api/why-not/", json={
        "session_id": sess_id,
        "product_id": "prod_elec_001"
    })
    assert why_not_excluded.status_code == 200
    wn_ex_data = why_not_excluded.json()
    assert wn_ex_data["is_eligible"] is False
    assert wn_ex_data["rejection_status"] in {"excluded", "not_retrieved"}
    assert len(wn_ex_data["what_needs_to_change"]) > 0

    # Step 4: Side-by-Side Visual Comparison
    comp_res = await async_client.post("/api/compare/", json={
        "product_ids": ["prod_foot_001", "prod_foot_003"],
        "session_id": sess_id
    })
    assert comp_res.status_code == 200
    comp_data = comp_res.json()
    assert len(comp_data["products"]) == 2
    for p in comp_data["products"]:
        assert "Within Budget" in p["hard_constraint_satisfaction"]
        assert p["fit_score_breakdown"] is not None

    # Step 5: Impossible Refinement -> Budget-Relaxation Diff View
    refine_res = await async_client.post("/api/chat/", json={
        "message": "Actually I need them under $20 strictly",
        "session_id": sess_id,
        "turn_id": 2
    })
    assert refine_res.status_code == 200
    refine_data = refine_res.json()
    assert refine_data["action_taken"] == "fallback"
    assert refine_data["fallback"] is not None
    assert refine_data["fallback"]["fallback_needed"] is True
    assert refine_data["fallback"]["price_delta"] is not None
    assert len(refine_data["fallback"]["exact_change_made"]) > 0
    assert refine_data["fallback"]["requires_user_approval"] is True
