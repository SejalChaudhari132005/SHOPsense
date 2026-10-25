"""
ShopSense AI — Unit Tests for Multi-Store Product Adapters
Tests individual store adapters (Local Catalog, Amazon India, Flipkart) for
status reporting, search, normalization, multi-currency handling, and honest provenance.
"""

import pytest
from app.adapters.local_catalog_adapter import LocalCatalogAdapter
from app.adapters.amazon_adapter import AmazonIndiaAdapter
from app.adapters.flipkart_adapter import FlipkartAdapter
from app.adapters.base import StoreStatusEnum


@pytest.mark.asyncio
async def test_local_catalog_adapter_status_and_search():
    adapter = LocalCatalogAdapter()
    status = adapter.get_status()

    assert status.store_id == "local_catalog"
    assert status.status == StoreStatusEnum.LIVE_VERIFIED
    assert status.is_configured is True
    assert status.is_mocked is False

    # Search running shoes
    result = await adapter.search(query="trail running", category="footwear", limit=5)
    assert result.status == StoreStatusEnum.LIVE_VERIFIED
    assert result.total_found > 0
    assert len(result.products) > 0

    first = result.products[0]
    assert first.category == "footwear"
    assert first.price > 0.0
    assert first.normalized_price_usd is not None
    assert first.normalized_price_usd > 0.0
    assert first.provenance.data_source_type.value == "local_demo"


@pytest.mark.asyncio
async def test_amazon_adapter_mock_demonstration():
    # Without credentials, adapter must truthfully report mocked_demonstration
    adapter = AmazonIndiaAdapter(api_key="", api_secret="", associate_tag="", enable_mock_fallback=True)
    status = adapter.get_status()

    assert status.store_id == "amazon_in"
    assert status.status == StoreStatusEnum.MOCKED_DEMONSTRATION
    assert status.is_configured is False
    assert status.is_mocked is True
    assert "mocked demonstration" in status.notes.lower()

    # Search headphones
    result = await adapter.search(query="Sony noise cancelling headphones", category="electronics", limit=5)
    assert result.status == StoreStatusEnum.MOCKED_DEMONSTRATION
    assert result.is_mocked is True
    assert result.total_found >= 1

    sony = next((p for p in result.products if "sony" in p.product_name.lower()), None)
    assert sony is not None
    assert sony.currency == "INR"
    assert sony.price == 29990.0
    # Price normalized to USD benchmark (29990 * 0.012 = ~$359.88)
    assert sony.normalized_price_usd is not None
    assert 300.0 < sony.normalized_price_usd < 400.0
    assert "amazon.in" in sony.product_url
    assert sony.provenance.is_sample_data is True
    assert sony.provenance.verified is False


@pytest.mark.asyncio
async def test_amazon_adapter_disabled_mock():
    # When credentials are missing and mock fallback is explicitly disabled
    adapter = AmazonIndiaAdapter(api_key="", api_secret="", associate_tag="", enable_mock_fallback=False)
    status = adapter.get_status()

    assert status.status == StoreStatusEnum.NOT_CONFIGURED
    assert status.is_configured is False

    result = await adapter.search(query="laptop")
    assert result.status == StoreStatusEnum.NOT_CONFIGURED
    assert result.total_found == 0
    assert len(result.products) == 0


@pytest.mark.asyncio
async def test_flipkart_adapter_mock_demonstration():
    adapter = FlipkartAdapter(affiliate_id="", affiliate_token="", enable_mock_fallback=True)
    status = adapter.get_status()

    assert status.store_id == "flipkart"
    assert status.status == StoreStatusEnum.MOCKED_DEMONSTRATION
    assert status.is_configured is False
    assert status.is_mocked is True
    assert "mocked demonstration" in status.notes.lower()

    result = await adapter.search(query="headphones", category="electronics", limit=5)
    assert result.status == StoreStatusEnum.MOCKED_DEMONSTRATION
    assert result.is_mocked is True
    assert result.total_found >= 1

    # Find AirPods Max or Sony
    airpods = next((p for p in result.products if "airpods" in p.product_name.lower()), None)
    assert airpods is not None
    assert airpods.currency == "INR"
    assert airpods.price == 59900.0
    assert airpods.normalized_price_usd is not None
    assert airpods.normalized_price_usd > 700.0
    assert "flipkart.com" in airpods.product_url
    assert airpods.provenance.is_sample_data is True


@pytest.mark.asyncio
async def test_adapter_record_normalization_robustness():
    adapter = AmazonIndiaAdapter()
    
    # Test normalization of malformed record (missing price)
    bad_record = {"product_id": "test_bad", "product_name": "Test Item"}
    norm = adapter.normalize_record(bad_record)
    assert norm is None  # Fails gracefully without throwing unhandled exception
