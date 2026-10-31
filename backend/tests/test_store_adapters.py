"""Tests for the single-source local mock catalog adapter."""

import pytest
from app.adapters.local_catalog_adapter import LocalCatalogAdapter
from app.adapters.base import StoreStatusEnum


@pytest.mark.asyncio
async def test_local_catalog_adapter_status_and_search():
    adapter = LocalCatalogAdapter()
    status = adapter.get_status()

    assert status.store_id == "local_catalog"
    assert status.status == StoreStatusEnum.MOCKED_DEMONSTRATION
    assert status.is_configured is True
    assert status.is_mocked is True
    assert adapter.is_mocked is True

    # Search running shoes
    result = await adapter.search(query="trail running", category="footwear", limit=5)
    assert result.status == StoreStatusEnum.MOCKED_DEMONSTRATION
    assert result.total_found > 0
    assert len(result.products) > 0

    first = result.products[0]
    assert first.category == "footwear"
    assert first.price > 0.0
    assert first.normalized_price_usd is not None
    assert first.normalized_price_usd > 0.0
    assert first.provenance.data_source_type.value == "local_demo"


@pytest.mark.asyncio
async def test_adapter_record_normalization_robustness():
    adapter = LocalCatalogAdapter()
    
    # Test normalization of malformed record (missing price)
    bad_record = {"product_id": "test_bad", "product_name": "Test Item"}
    norm = adapter.normalize_record(bad_record)
    assert norm is None  # Fails gracefully without throwing unhandled exception
