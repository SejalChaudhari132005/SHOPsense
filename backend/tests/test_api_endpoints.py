"""
FastAPI Endpoints Integration Test Suite
Verifies all required REST endpoints:
- GET /health and GET /api/health
- POST /api/chat
- POST /api/search
- POST /api/compare
- POST /api/why-not
- POST /api/refine
- GET /api/session/{session_id} (and 404 behavior)
- GET /api/preferences, POST /api/preferences, DELETE /api/preferences
- Malformed requests & 422 validations
- Request size limit enforcement
- Mocked LLM timeout resilience
"""

import pytest
from httpx import AsyncClient
from unittest.mock import patch


# ==========================================
# 1. Health Check Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_health(async_client: AsyncClient):
    # Test GET /health
    res = await async_client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["activeAgents"] == 10
    assert "groq_configured" in data

    # Test GET /api/health
    res_api = await async_client.get("/api/health")
    assert res_api.status_code == 200


# ==========================================
# 2. Chat Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_chat_recommendation_flow(async_client: AsyncClient):
    payload = {
        "message": "I need running shoes under $150 size 10",
        "session_id": "api_chat_sess_01",
        "turn_id": 1
    }
    res = await async_client.post("/api/chat/", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["action_taken"] == "recommend"
    assert len(data["recommendations"]) >= 1
    assert "top_three_comparison" in data
    assert data["recommendations"][0]["fit_score"]["total_score"] > 50


@pytest.mark.asyncio
async def test_endpoint_chat_clarification_flow(async_client: AsyncClient):
    payload = {
        "message": "Find shoes",
        "session_id": "api_chat_sess_clarify",
        "turn_id": 1
    }
    res = await async_client.post("/api/chat/", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["action_taken"] == "clarify"
    assert data["clarification"] is not None
    assert data["clarification"]["needs_clarification"] is True


# ==========================================
# 3. Search Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_search_with_filters(async_client: AsyncClient):
    payload = {
        "category": "footwear",
        "query": "trail",
        "max_price": 130.0,
        "currency": "USD",
        "sort_by": "price",
        "page": 1,
        "page_size": 5
    }
    res = await async_client.post("/api/search/", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total_count" in data
    assert data["total_count"] >= 1
    assert all(
        item["currency"] == "INR"
        and "normalized_price_usd" not in item
        and item["price"] <= 130.0 / 0.012
        for item in data["items"]
    )


@pytest.mark.asyncio
async def test_endpoint_search_empty_results(async_client: AsyncClient):
    payload = {
        "category": "electronics",
        "min_price": 50000.0  # No electronics in catalog over $50,000
    }
    res = await async_client.post("/api/search/", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["total_count"] == 0
    assert len(data["items"]) == 0


# ==========================================
# 4. Compare Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_compare_products_success(async_client: AsyncClient):
    payload = {
        "product_ids": ["prod_foot_001", "prod_foot_002"]
    }
    res = await async_client.post("/api/compare/", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert len(data["products"]) == 2
    assert "attribute_matrix" in data
    assert "price_comparison" in data
    assert "recommendation_summary" in data


@pytest.mark.asyncio
async def test_endpoint_compare_invalid_counts(async_client: AsyncClient):
    # Only 1 product (minimum is 2)
    res_one = await async_client.post("/api/compare/", json={"product_ids": ["prod_foot_001"]})
    assert res_one.status_code == 422

    # 5 products (maximum is 4)
    res_five = await async_client.post("/api/compare/", json={
        "product_ids": ["prod_foot_001", "prod_foot_002", "prod_foot_003", "prod_foot_004", "prod_foot_005"]
    })
    assert res_five.status_code == 422


# ==========================================
# 5. 'Why Not' Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_why_not_analysis(async_client: AsyncClient):
    sess_id = "api_whynot_sess_01"
    # First establish session constraints (budget under $1000)
    await async_client.post("/api/chat/", json={
        "message": "Find programming laptop under $1000",
        "session_id": sess_id,
        "turn_id": 1
    })

    # Ask why DevBook Pro 16 ($1499) was not recommended
    why_not_payload = {
        "session_id": sess_id,
        "product_id": "prod_elec_002"  # $1499.00
    }
    res = await async_client.post("/api/why-not/", json=why_not_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["target_product_id"] == "prod_elec_002"
    assert data["is_eligible"] is False
    assert len(data["violated_hard_constraints"]) > 0
    assert "exceeds" in data["explanation"].lower() or "price" in data["explanation"].lower()


@pytest.mark.asyncio
async def test_endpoint_why_not_nonexistent_product(async_client: AsyncClient):
    res = await async_client.post("/api/why-not/", json={
        "session_id": "any_sess",
        "product_id": "invalid_prod_999"
    })
    assert res.status_code == 404


# ==========================================
# 6. Refine Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_refine_constraints(async_client: AsyncClient):
    sess_id = "api_refine_sess_01"
    # Turn 1: Broad laptop search under $1600
    await async_client.post("/api/chat/", json={
        "message": "Laptop for programming under $1600",
        "session_id": sess_id,
        "turn_id": 1
    })

    # Turn 2: Refine via /api/refine endpoint
    refine_payload = {
        "session_id": sess_id,
        "new_budget_max": 900.0,
        "message": "Lower my budget to $900"
    }
    res = await async_client.post("/api/refine/", json=refine_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["action_taken"] == "recommend"
    # Foreign-currency budgets are converted to INR and are not exposed as USD.
    for rec in data["recommendations"]:
        assert "normalized_price_usd" not in rec["product"]
        assert rec["product"]["price"] <= 900.0 / 0.012
        assert rec["product"]["currency"] == "INR"


# ==========================================
# 7. Session State Endpoint Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_get_session_state(async_client: AsyncClient):
    sess_id = "api_state_inspect_sess"
    # Create session with a query
    await async_client.post("/api/chat/", json={
        "message": "Find trail running shoes under $140 size 10",
        "session_id": sess_id,
        "turn_id": 1
    })

    # Inspect state safely
    res = await async_client.get(f"/api/session/{sess_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["session_id"] == sess_id
    assert data["turn_count"] >= 1
    assert "confirmed_constraints" in data
    assert data["confirmed_constraints"]["category"] == "footwear"
    # Verify no internal prompt or secret is leaked
    assert "groq_api_key" not in data
    assert "system_prompt" not in data


@pytest.mark.asyncio
async def test_endpoint_get_session_missing(async_client: AsyncClient):
    res = await async_client.get("/api/session/non_existent_session_id_404")
    assert res.status_code == 404


# ==========================================
# 8. Preferences Persistence Tests
# ==========================================

@pytest.mark.asyncio
async def test_endpoint_preferences_crud_flow(async_client: AsyncClient):
    user_id = "test_user_consent_01"

    # Step 1: Save with affirmative consent
    save_payload = {
        "user_id": user_id,
        "consent_given": True,
        "preferred_categories": ["footwear", "fitness_outdoor"],
        "preferred_brands": ["AlpineTrack"],
        "shoe_size": "10.5",
        "budget_tier": "mid_range"
    }
    save_res = await async_client.post("/api/preferences/", json=save_payload)
    assert save_res.status_code == 200
    saved_data = save_res.json()
    assert saved_data["consent_given"] is True
    assert saved_data["preferences"]["shoe_size"] == "10.5"

    # Step 2: Retrieve preferences
    get_res = await async_client.get(f"/api/preferences/?user_id={user_id}")
    assert get_res.status_code == 200
    get_data = get_res.json()
    assert get_data["consent_given"] is True
    assert "AlpineTrack" in get_data["preferences"]["preferred_brands"]

    # Step 3: Delete preferences (Right to be Forgotten)
    del_res = await async_client.delete(f"/api/preferences/?user_id={user_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Step 4: Verify wiped state
    get_after_del = await async_client.get(f"/api/preferences/?user_id={user_id}")
    assert get_after_del.status_code == 200
    assert get_after_del.json()["consent_given"] is False
    assert get_after_del.json()["preferences"] is None


@pytest.mark.asyncio
async def test_endpoint_preferences_rejected_without_consent(async_client: AsyncClient):
    user_id = "test_user_no_consent"
    save_payload = {
        "user_id": user_id,
        "consent_given": False,  # Explicitly declined
        "preferred_categories": ["electronics"]
    }
    res = await async_client.post("/api/preferences/", json=save_payload)
    assert res.status_code == 200
    assert res.json()["consent_given"] is False
    assert res.json()["preferences"] is None


# ==========================================
# 9. Request Size Limit & Resilience Tests
# ==========================================

@pytest.mark.asyncio
async def test_middleware_request_size_limit(async_client: AsyncClient):
    """Payloads exceeding 1MB must be rejected with HTTP 413."""
    oversized_message = "A" * (1_048_576 + 50)  # slightly over 1MB
    payload = {"message": oversized_message, "session_id": "oversize_test"}
    headers = {"content-length": str(len(oversized_message) + 100)}
    res = await async_client.post("/api/chat/", json=payload, headers=headers)
    assert res.status_code == 413
    assert res.json()["error"] is True


@pytest.mark.asyncio
async def test_endpoint_mock_llm_failure_resilience(async_client: AsyncClient):
    """Simulated Groq API failure must gracefully degrade to deterministic extraction."""
    with patch("app.agents.intent_extraction.extract_intent_with_llm", side_effect=TimeoutError("Groq timeout")):
        payload = {
            "message": "Find waterproof trail running shoes under $120",
            "session_id": "api_fail_mock_sess"
        }
        res = await async_client.post("/api/chat/", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["action_taken"] == "recommend"
        assert len(data["recommendations"]) >= 1
