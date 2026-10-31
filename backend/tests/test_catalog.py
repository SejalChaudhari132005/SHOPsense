"""
Unit tests for ShopSense AI — Product Catalog and Normalized Product Schema
Covers:
- Schema validation & invalid price rejection
- Missing optional fields & honest uncertainty tracking
- Multi-currency normalization (USD, INR, EUR, GBP) and cross-currency comparisons
- Catalog loading & count verification (>= 30 products across 7 categories)
- Synonym mapping & attribute normalization (sizes, weights, colours)
- Duplicate product detection
- Strict price ceiling & attribute filtering
- Provenance and source metadata auditing
"""

import json

import pytest
from pydantic import ValidationError

from app.models.product import (
    Product,
    AvailabilityStatus,
    DataSourceType,
    AttributeMatchStatus,
    ShippingInfo,
)
from app.services.currency_service import (
    get_exchange_rate,
    convert_currency,
    normalize_price_to_usd,
    format_price,
    format_price_in_inr,
    compare_prices,
)
from app.services.catalog_service import (
    load_and_validate_catalog,
    search_by_category_and_keywords,
    filter_by_price_and_attributes,
    match_synonyms,
    normalize_attribute_values,
    identify_duplicate_products,
    handle_missing_attributes,
    get_source_metadata,
    sort_and_paginate,
    canonicalize_category,
)


# ==========================================
# 1. Pydantic Schema Validation Tests
# ==========================================

def test_schema_validation_valid_product():
    """Verify that a complete product schema passes validation with expected defaults."""
    prod = Product(
        product_id="test_prod_001",
        product_name="Sample Running Sneaker",
        brand="RunnerPro",
        category="footwear",
        subcategory="road_running",
        description="A great test shoe for validation.",
        price=120.00,
        currency="USD",
        sizes=["9", "10", "11"],
        colours=["matte black", "pure white"],
        attributes={"waterproof": False, "cushioning": "High"},
        specifications={"weight_kg": 0.28},
        rating=4.5,
        review_count=120,
        availability=AvailabilityStatus.IN_STOCK,
        data_source_type=DataSourceType.LOCAL_DEMO
    )

    assert prod.product_id == "test_prod_001"
    assert prod.currency == "USD"
    assert prod.provenance.is_sample_data is True
    assert prod.provenance.data_source_type == DataSourceType.LOCAL_DEMO
    assert "shipping_information" in prod.provenance.missing_fields


def test_schema_validation_invalid_price():
    """Verify that zero or negative price raises a ValidationError."""
    with pytest.raises(ValidationError):
        Product(
            product_id="test_err_001",
            product_name="Zero Price Item",
            brand="BrandX",
            category="electronics",
            description="Testing zero price failure",
            price=0.0,
            currency="USD"
        )

    with pytest.raises(ValidationError):
        Product(
            product_id="test_err_002",
            product_name="Negative Price Item",
            brand="BrandX",
            category="electronics",
            description="Testing negative price failure",
            price=-49.99,
            currency="USD"
        )


def test_schema_missing_optional_fields():
    """Verify that omitting optional fields succeeds and records missing fields in provenance."""
    minimal_prod = Product(
        product_id="test_minimal_001",
        product_name="Minimal Product",
        brand="BareBones",
        category="bags_accessories",
        description="Product with bare minimum fields",
        price=35.00,
        currency="USD"
    )

    assert minimal_prod.sizes is None
    assert minimal_prod.colours is None
    assert minimal_prod.rating is None
    assert minimal_prod.review_count is None
    assert minimal_prod.shipping_information is None
    assert "sizes" in minimal_prod.provenance.missing_fields
    assert "rating" in minimal_prod.provenance.missing_fields
    assert "specifications" in minimal_prod.provenance.missing_fields


def test_product_defaults_to_inr():
    product = Product(
        product_id="test_inr_default",
        product_name="Default Currency Product",
        brand="ShopSense",
        category="electronics",
        description="Product uses the catalog currency default.",
        price=1200.0,
    )

    assert product.currency == "INR"


def test_catalog_loader_converts_imported_prices_to_inr(tmp_path):
    catalog_path = tmp_path / "foreign-price.json"
    catalog_path.write_text(
        json.dumps(
            [
                {
                    "product_id": "foreign_price",
                    "product_name": "Imported Product",
                    "brand": "ShopSense",
                    "category": "electronics",
                    "description": "Imported source price is normalized for catalog use.",
                    "price": 10.0,
                    "currency": "USD",
                }
            ]
        ),
        encoding="utf-8",
    )

    [product] = load_and_validate_catalog(str(catalog_path))

    assert product.price == 833.33
    assert product.currency == "INR"
    assert product.normalized_price_usd is None


def test_schema_empty_string_rejection():
    """Verify that empty strings for required text fields are rejected."""
    with pytest.raises(ValidationError):
        Product(
            product_id="test_err_003",
            product_name="   ",  # whitespace only
            brand="BrandX",
            category="footwear",
            description="Empty name should fail",
            price=50.0,
            currency="USD"
        )


# ==========================================
# 2. Currency Handling & Normalization Tests
# ==========================================

def test_currency_conversion_rates():
    """Verify exchange rate calculation and conversions."""
    # Identity
    assert get_exchange_rate("USD", "USD") == 1.0

    # INR conversion
    inr_rate = get_exchange_rate("INR", "USD")
    assert inr_rate == pytest.approx(0.012, rel=1e-2)

    # 5000 INR to USD
    usd_val = convert_currency(5000.0, "INR", "USD")
    assert usd_val == 60.0

    # Unsupported currency
    with pytest.raises(ValueError):
        get_exchange_rate("XYZ", "USD")


def test_currency_cross_comparison_not_equal():
    """
    CRITICAL REQUIREMENT:
    Ensure 4999 INR ($59.99) is NOT treated as numerically greater than $100 USD.
    """
    price_inr = 4999.00
    price_usd = 100.00

    # In naive comparison: 4999 > 100 (which would be catastrophically wrong)
    # Using normalized comparison: 4999 INR (~$59.99 USD) < 100 USD
    comparison = compare_prices(price_inr, "INR", price_usd, "USD")
    assert comparison == -1, "4,999 INR must be recognized as lower cost than $100 USD"

    comparison_equal = compare_prices(100.0, "USD", 100.0, "USD")
    assert comparison_equal == 0

    comparison_higher = compare_prices(24999.0, "INR", 100.0, "USD")  # ~300 USD vs 100 USD
    assert comparison_higher == 1


def test_currency_formatting():
    """Verify proper localized currency symbols."""
    assert format_price(119.99, "USD") == "$119.99"
    assert format_price(4999.00, "INR") == "₹4,999.00"
    assert format_price(85.50, "EUR") == "€85.50"
    assert format_price_in_inr(119.99, "USD") == "₹9,999.17"


# ==========================================
# 3. Demonstration Catalog Loading & Content
# ==========================================

def test_catalog_loader_and_counts():
    """
    Verify loading demo_products.json:
    - Must load the curated products and DummyJSON snapshot.
    - Must represent all supported catalog categories.
    - All items must pass Pydantic validation.
    """
    products = load_and_validate_catalog()
    assert len(products) >= 234, f"Expected at least 234 products, got {len(products)}"

    categories = {p.category for p in products}
    expected_categories = {
        "footwear",
        "clothing",
        "electronics",
        "travel_accessories",
        "fitness_outdoor",
        "home_kitchen",
        "bags_accessories",
        "beauty_personal_care",
        "fashion_accessories",
        "groceries",
        "automotive",
    }
    assert expected_categories.issubset(categories), f"Missing categories: {expected_categories - categories}"
    assert {product.currency for product in products} == {"INR"}
    dummyjson_products = [product for product in products if product.source_store == "DummyJSON"]
    assert len(dummyjson_products) == 194
    assert all(
        product.product_id.startswith("dummyjson_")
        and product.image_url
        and product.image_url.startswith("https://cdn.dummyjson.com/")
        and product.normalized_price_usd is not None
        for product in dummyjson_products
    )
    laptop_matches = search_by_category_and_keywords(
        products, category="electronics", keywords=["laptop"]
    )
    assert any(
        product.source_store == "DummyJSON" and product.image_url
        for product in laptop_matches
    )
    assert all(
        product.shipping_information is None
        or product.shipping_information.currency == "INR"
        for product in products
    )

    # Verify all items have positive normalized_price_usd
    for p in products:
        assert p.normalized_price_usd is not None
        assert p.normalized_price_usd > 0.0
        assert p.provenance.is_sample_data is True


# ==========================================
# 4. Synonym Mapping & Category Aliases
# ==========================================

def test_synonym_matching():
    """Verify synonym expansion across technical terms and categories."""
    anc_syns = match_synonyms("anc")
    assert "noise_cancelling" in anc_syns
    assert "active noise cancellation" in anc_syns

    light_syns = match_synonyms("lightweight")
    assert "ultralight" in light_syns
    assert "portable" in light_syns

    waterproof_syns = match_synonyms("waterproof")
    assert "gore-tex" in waterproof_syns
    assert "weatherproof" in waterproof_syns


def test_canonicalize_category():
    """Verify casual query terms resolve to canonical category keys."""
    assert canonicalize_category("shoes") == "footwear"
    assert canonicalize_category("sneakers") == "footwear"
    assert canonicalize_category("mens-shoes") == "footwear"
    assert canonicalize_category("laptop") == "electronics"
    assert canonicalize_category("womens-dresses") == "clothing"
    assert canonicalize_category("skin-care") == "beauty_personal_care"
    assert canonicalize_category("womens-jewellery") == "fashion_accessories"
    assert canonicalize_category("luggage") == "travel_accessories"
    assert canonicalize_category("gym") == "fitness_outdoor"
    assert canonicalize_category("cookware") == "home_kitchen"
    assert canonicalize_category("backpack") == "bags_accessories"


# ==========================================
# 5. Attribute Value Normalization
# ==========================================

def test_attribute_value_normalization():
    """Verify normalization of sizes, colours, and weights."""
    # Sizes
    assert normalize_attribute_values("size", "US 10.5") == "10.5"
    assert normalize_attribute_values("size", "Extra Large") == "XL"
    assert normalize_attribute_values("size", "Medium") == "M"

    # Colours
    assert normalize_attribute_values("colour", "Forest Olive") == "green"
    assert normalize_attribute_values("colour", "Midnight Black") == "black"
    assert normalize_attribute_values("colour", "Cobalt Blue") == "blue"
    assert normalize_attribute_values("colour", "Pure White") == "white"

    # Weights
    assert normalize_attribute_values("weight_kg", "250g") == 0.25
    assert normalize_attribute_values("weight_kg", "1.25 kg") == 1.25
    assert normalize_attribute_values("weight_kg", "2.2 lbs") == pytest.approx(0.998, rel=1e-2)


# ==========================================
# 6. Keyword & Category Search
# ==========================================

def test_search_by_category_and_keywords():
    """Verify searching for products by category and expanded keywords."""
    catalog = load_and_validate_catalog()

    # Search trail footwear
    trail_shoes = search_by_category_and_keywords(
        catalog,
        category="shoes",  # tests alias mapping to footwear
        keywords=["trail", "mud"]
    )
    assert len(trail_shoes) >= 1
    assert any("TerraStride" in p.product_name for p in trail_shoes)

    # Search with noise cancelling (anc) synonym
    anc_headphones = search_by_category_and_keywords(
        catalog,
        category="electronics",
        keywords=["anc"]
    )
    assert len(anc_headphones) >= 1
    assert any("QuietPulse" in p.product_name for p in anc_headphones)


# ==========================================
# 7. Price & Attribute Filtering
# ==========================================

def test_filter_strict_price_ceiling():
    """
    CRITICAL RULE #11:
    Never silently relax hard constraints like a strict budget ceiling.
    """
    catalog = load_and_validate_catalog()

    # Filter laptops under $600 USD
    budget_laptops = filter_by_price_and_attributes(
        [p for p in catalog if p.category == "electronics" and p.subcategory == "laptops"],
        max_price=600.0,
        target_currency="USD"
    )
    # AeroBook Air 13 ($549.99) should pass, ZenBook ($899.99) and DevBook ($1499) must NOT
    assert len(budget_laptops) == 1
    assert budget_laptops[0].product_id == "prod_elec_003"
    assert budget_laptops[0].normalized_price_usd <= 600.0


def test_filter_by_size_and_colour():
    """Verify filtering products by specific size and normalized colour."""
    catalog = load_and_validate_catalog()
    footwear = [p for p in catalog if p.category == "footwear"]

    # Filter size 10 in black
    filtered = filter_by_price_and_attributes(
        footwear,
        size="10",
        colour="black"
    )
    assert len(filtered) >= 1
    for p in filtered:
        assert p.sizes is not None
        assert "10" in p.sizes


# ==========================================
# 8. Duplicate Product Detection
# ==========================================

def test_identify_duplicate_products():
    """Verify duplicate detection by SKU / source_product_id or title similarity."""
    catalog = load_and_validate_catalog()
    duplicates = identify_duplicate_products(catalog)

    assert len(duplicates) >= 1
    # Check that CitySlicker original and partner listing were flagged
    found_cityslicker_dup = False
    for p1, p2, score in duplicates:
        if (p1.product_id == "prod_bag_002" and p2.product_id == "prod_bag_005") or \
           (p1.product_id == "prod_bag_005" and p2.product_id == "prod_bag_002"):
            found_cityslicker_dup = True
            assert score >= 0.85

    assert found_cityslicker_dup, "Expected prod_bag_002 and prod_bag_005 duplicate to be detected"


# ==========================================
# 9. Missing Attribute & Uncertainty Handling
# ==========================================

def test_handle_missing_attributes_honesty():
    """
    CRITICAL RULE #10:
    Treat unknown product attributes as UNKNOWN, never as confirmed matches.
    """
    prod = Product(
        product_id="test_missing_001",
        product_name="Basic Bag",
        brand="SimpleGear",
        category="bags_accessories",
        description="A bag with unspecified waterproof status",
        price=40.0,
        currency="USD",
        attributes={"pockets": 3},
        specifications={"weight_kg": 0.5}
    )

    statuses = handle_missing_attributes(prod, ["waterproof", "weight_kg", "battery_hours"])

    assert statuses["weight_kg"] == AttributeMatchStatus.MATCH
    # waterproof and battery_hours are not mentioned, must be UNKNOWN, NOT match or mismatch
    assert statuses["waterproof"] == AttributeMatchStatus.UNKNOWN
    assert statuses["battery_hours"] == AttributeMatchStatus.UNKNOWN


# ==========================================
# 10. Sorting & Pagination
# ==========================================

def test_sort_and_paginate():
    """Verify sorting and pagination metadata."""
    catalog = load_and_validate_catalog()

    # Sort by price ascending
    res_asc = sort_and_paginate(catalog, sort_by="price", ascending=True, page=1, page_size=5)
    assert res_asc["total_count"] == len(catalog)
    assert len(res_asc["items"]) == 5
    assert res_asc["page"] == 1
    assert res_asc["total_pages"] == (len(catalog) + 4) // 5

    # Lowest price should be first (e.g. BharatYatra Luggage Straps at ~$11.99 USD or ShieldRFID at $18.99)
    first_item = res_asc["items"][0]
    second_item = res_asc["items"][1]
    assert first_item.normalized_price_usd <= second_item.normalized_price_usd


# ==========================================
# 11. Source Metadata & Provenance Audit
# ==========================================

def test_provenance_metadata_audit():
    """Verify provenance metadata distinguishes sample demonstration data."""
    catalog = load_and_validate_catalog()
    for p in catalog:
        meta = get_source_metadata(p)
        assert meta.is_sample_data is True
        assert meta.data_source_type == DataSourceType.LOCAL_DEMO
        assert meta.confidence_score > 0.0


# ==========================================
# 12. FastAPI HTTP Catalog Endpoints Tests
# ==========================================

@pytest.mark.asyncio
async def test_api_list_categories(async_client):
    """Verify GET /api/catalog/categories endpoint."""
    res = await async_client.get("/api/catalog/categories")
    assert res.status_code == 200
    data = res.json()
    assert "categories" in data
    assert "footwear" in data["categories"]
    assert "electronics" in data["categories"]
    assert "beauty_personal_care" in data["categories"]


@pytest.mark.asyncio
async def test_api_search_products(async_client):
    """Verify GET /api/catalog/products with facet filters."""
    res = await async_client.get("/api/catalog/products?category=footwear&max_price=125.0&currency=USD")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    assert "total_count" in data
    assert data["total_count"] >= 1
    # Check that all returned items respect the ceiling
    for item in data["items"]:
        assert item["currency"] == "INR"
        assert "normalized_price_usd" not in item
        assert item["price"] <= 125.0 / 0.012


@pytest.mark.asyncio
async def test_api_get_single_product(async_client):
    """Verify GET /api/catalog/products/{id} and 404 behavior."""
    # Existing
    res = await async_client.get("/api/catalog/products/prod_foot_001")
    assert res.status_code == 200
    data = res.json()
    assert data["product_id"] == "prod_foot_001"
    assert data["brand"] == "AlpineTrack"

    # Non-existent
    res_404 = await async_client.get("/api/catalog/products/prod_non_existent")
    assert res_404.status_code == 404
