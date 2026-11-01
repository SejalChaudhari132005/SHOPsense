# ShopSense AI — Demonstration Catalog

This directory contains demonstration product data used by the ShopSense AI agent swarm.

## Catalog Integrity Principles

1. **Truthful Demo Data**: All specifications, dimensions, materials, and prices reflect realistic e-commerce products.
2. **Explicit Unknowns**: If an attribute (e.g. noise cancellation level, waterproof rating) is not explicitly documented for a product, agents must treat it as *unknown*, never as an assumed match or hallucinated spec.
3. **Multi-Store Representation**: Products feature multiple store listings with real price variations, shipping estimates, and stock indicators to test cross-store discovery.
4. **Hard Constraint Grounding**: Prices and categories are strictly validated by the deterministic ranking and retrieval agents before being presented to users.

## Product Schema Reference

- `id` (string): Unique identifier (e.g. `prod_lap_001`).
- `name` (string): Full product name.
- `category` (string): Canonical category (`footwear`, `clothing`, `electronics`, `travel_accessories`, `fitness_outdoor`, `home_kitchen`, `bags_accessories`, `beauty_personal_care`, `fashion_accessories`, `groceries`, `automotive`).
- `brand` (string): Manufacturer brand.
- `price` (float): Product price in Indian rupees.
- `currency` (string): Standard ISO 4217 code (`INR`).
- `normalized_price_usd` (legacy field): ignored for filtering, ranking, and client responses; all comparisons use INR.
- `rating` (float): 1.0 to 5.0 customer review rating.
- `review_count` (int): Number of customer ratings.
- `specs` (dict): Domain-specific technical specifications.
- `features` (list[str]): Key selling points and standout capabilities.
- `tags` (list[str]): Semantic labels for synonym mapping and candidate retrieval.
- `purpose` (list[str]): Target user personas and application scenarios.
- `stores` (list[dict]): Associated retail stores offering the product.

## Combined Demo Catalog

The catalog retains its curated ShopSense demonstration products and includes a
static snapshot of 194 products from [DummyJSON](https://dummyjson.com/products?limit=0).
Imported records use IDs prefixed with `dummyjson_`, retain their own thumbnail
URLs, and identify `DummyJSON` as their source. DummyJSON does not specify a
currency in each product record; its prices are treated as USD and converted to
INR using ShopSense's fixed exchange-rate benchmark. These are sample products,
not verified retailer listings. The snapshot can be refreshed by re-importing
the source API data. Existing curated seed products retain their original
`demo.shopsense.local` image URLs because DummyJSON does not contain exact
images for those fictional products; unrelated product photos are not assigned
to them.
