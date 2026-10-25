"""
ShopSense AI — Integration Tests for Multi-Store Product Discovery & Comparison
Validates unified candidate pool creation, cross-store deduplication, price comparisons,
timeout resilience, multi-currency budget enforcement, and store status API.
"""

import pytest
import asyncio
from typing import Optional, Dict, Any, List
from fastapi.testclient import TestClient

from app.main import app
from app.adapters.base import BaseStoreAdapter, StoreStatus, StoreStatusEnum, StoreSearchResult
from app.adapters.registry import StoreAdapterRegistry, adapter_registry
from app.adapters.local_catalog_adapter import LocalCatalogAdapter
from app.adapters.amazon_adapter import AmazonIndiaAdapter
from app.adapters.flipkart_adapter import FlipkartAdapter
from app.agents.candidate_retrieval import CandidateRetrievalAgent
from app.agents.ranking_fit import RankingFitScoringAgent
from app.models.state import ExtractedIntent, AttributeMappingResult
from app.models.product import Product


client = TestClient(app)


# Mock slow adapter to test timeout resilience
class SlowMockAdapter(BaseStoreAdapter):
    @property
    def store_id(self) -> str:
        return "slow_store"

    @property
    def store_name(self) -> str:
        return "Slow Store Inc"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def is_mocked(self) -> bool:
        return True

    def get_status(self) -> StoreStatus:
        return StoreStatus(
            store_id=self.store_id,
            store_name=self.store_name,
            status=StoreStatusEnum.LIVE_VERIFIED,
            is_configured=True,
            is_mocked=True
        )

    async def search(self, query: str, **kwargs) -> StoreSearchResult:
        # Sleep longer than timeout to trigger timeout handling
        await asyncio.sleep(2.0)
        return StoreSearchResult(
            store_id=self.store_id,
            store_name=self.store_name,
            status=StoreStatusEnum.LIVE_VERIFIED,
            products=[]
        )

    async def get_product_details(self, product_id: str) -> Optional[Product]:
        return None

    def normalize_record(self, raw_record: Dict[str, Any]) -> Optional[Product]:
        return None


# Mock failing adapter to test error resilience
class FailingMockAdapter(BaseStoreAdapter):
    @property
    def store_id(self) -> str:
        return "failing_store"

    @property
    def store_name(self) -> str:
        return "Failing Store"

    @property
    def is_configured(self) -> bool:
        return True

    @property
    def is_mocked(self) -> bool:
        return True

    def get_status(self) -> StoreStatus:
        return StoreStatus(
            store_id=self.store_id,
            store_name=self.store_name,
            status=StoreStatusEnum.ERROR,
            is_configured=True,
            is_mocked=True
        )

    async def search(self, query: str, **kwargs) -> StoreSearchResult:
        raise ConnectionResetError("Remote server forcibly closed connection")

    async def get_product_details(self, product_id: str) -> Optional[Product]:
        return None

    def normalize_record(self, raw_record: Dict[str, Any]) -> Optional[Product]:
        return None


def test_store_status_api_endpoint():
    """Tests GET /api/stores/status returns the truthful integration status table."""
    response = client.get("/api/stores/status")
    assert response.status_code == 200
    data = response.json()

    assert "stores" in data
    assert data["total_stores"] >= 3
    store_ids = [s["store_id"] for s in data["stores"]]
    assert "local_catalog" in store_ids
    assert "amazon_in" in store_ids
    assert "flipkart" in store_ids

    # Local catalog must be live_verified
    local_status = next(s for s in data["stores"] if s["store_id"] == "local_catalog")
    assert local_status["status"] == "live_verified"
    assert local_status["is_mocked"] is False

    # Unconfigured Amazon & Flipkart must be mocked_demonstration with honest notes
    amz_status = next(s for s in data["stores"] if s["store_id"] == "amazon_in")
    assert amz_status["status"] == "mocked_demonstration"
    assert amz_status["is_mocked"] is True


@pytest.mark.asyncio
async def test_multi_store_search_api():
    """Tests POST /api/stores/search returns combined candidates from multiple sources."""
    response = client.post("/api/stores/search", json={
        "query": "Sony headphones",
        "category": "electronics",
        "limit_per_store": 5
    })
    assert response.status_code == 200
    data = response.json()

    assert data["total_found"] > 0
    assert len(data["products"]) > 0
    # Must consult multiple sources
    assert len(data["sources_consulted"]) >= 2

    # Check store attribution
    stores_present = {p["source_store"] for p in data["products"]}
    assert "Amazon India" in stores_present or "Flipkart" in stores_present


def test_cross_store_deduplication_and_comparison():
    """
    Tests that identical products (Sony WH-1000XM5) across Amazon India (₹29,990)
    and Flipkart (₹28,990) are deduplicated, grouped, and compared with savings deltas.
    """
    registry = StoreAdapterRegistry()
    agent = CandidateRetrievalAgent(registry=registry)

    intent = ExtractedIntent(
        category="electronics",
        intended_use="music",
        soft_preferences=["noise cancelling", "wireless"]
    )
    mapping = AttributeMappingResult(normalized_category="electronics")

    result = agent.retrieve(intent, mapping)
    assert result.total_found > 0

    # Locate Sony WH-1000XM5 in deduplicated candidates
    sony_candidate = next(
        (p for p in result.candidates if "1000xm5" in p.product_name.lower()),
        None
    )
    assert sony_candidate is not None

    # Check that cross-store offers are preserved
    cross_offers = sony_candidate.attributes.get("cross_store_offers")
    assert cross_offers is not None
    assert len(cross_offers) >= 2

    offer_stores = {o["store_name"] for o in cross_offers}
    assert "Amazon India" in offer_stores
    assert "Flipkart" in offer_stores

    # Verify lowest price was selected as primary (Flipkart at ₹28,990 is lower than Amazon at ₹29,990)
    assert sony_candidate.source_store == "Flipkart"
    assert sony_candidate.price == 28990.0

    # Verify savings summary exists
    summary = sony_candidate.attributes.get("cross_store_savings_summary")
    assert summary is not None
    assert "saving" in summary.lower()


@pytest.mark.asyncio
async def test_timeout_resilience():
    """
    Verifies that if one store times out, other stores succeed and partial results
    are returned with clear store status reporting.
    """
    registry = StoreAdapterRegistry()
    # Add a slow adapter
    registry.register(SlowMockAdapter())

    # Search with a 0.2s timeout
    result = await registry.search_all(
        query="running shoes",
        timeout_seconds=0.2,
        enabled_stores=["local_catalog", "slow_store"]
    )

    # Local catalog should succeed, slow store should time out
    assert result.partial_results is True
    assert "Slow Store Inc" in result.timed_out_stores
    assert result.total_found > 0
    assert result.store_results["slow_store"].status == StoreStatusEnum.TIMED_OUT
    assert result.store_results["local_catalog"].status == StoreStatusEnum.LIVE_VERIFIED


@pytest.mark.asyncio
async def test_error_resilience():
    """
    Verifies that if an adapter encounters an unhandled network error,
    it is isolated and does not crash the multi-store search.
    """
    registry = StoreAdapterRegistry()
    registry.register(FailingMockAdapter())

    result = await registry.search_all(
        query="backpack",
        enabled_stores=["local_catalog", "failing_store"]
    )

    assert result.partial_results is True
    assert "Failing Store" in result.error_stores
    assert result.store_results["failing_store"].status == StoreStatusEnum.ERROR
    assert result.total_found > 0


def test_cross_store_ranking_and_strict_budget():
    """
    Verifies that candidate retrieval and ranking fairly compares USD and INR items
    and strictly enforces budget limits without ranking out-of-budget items as matches.
    """
    registry = StoreAdapterRegistry()
    retrieval_agent = CandidateRetrievalAgent(registry=registry)
    ranking_agent = RankingFitScoringAgent()

    # User has strict budget of $200 USD for running shoes
    intent = ExtractedIntent(
        category="footwear",
        intended_use="road running",
        budget_max=200.0,
        budget_currency="USD",
        is_budget_strict=True
    )
    mapping = AttributeMappingResult(normalized_category="footwear")

    retrieval = retrieval_agent.retrieve(intent, mapping)
    assert retrieval.total_found > 0

    # All candidates in retrieval must have normalized_price_usd <= $200
    for p in retrieval.candidates:
        assert p.normalized_price_usd <= 200.0

    # Rank candidates
    ranked = ranking_agent.rank(retrieval.candidates, intent)
    assert len(ranked) > 0

    # Top recommendation must be strictly eligible and have valid composite fit score
    top_prod, top_fit = ranked[0]
    assert top_fit.is_eligible is True
    assert top_fit.total_score > 50.0
    assert top_fit.budget_score > 0.0
