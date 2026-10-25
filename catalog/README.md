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
- `category` (string): Canonical category (`laptops`, `audio`, `shoes`, `backpacks`).
- `brand` (string): Manufacturer brand.
- `price` (float): Base USD price.
- `currency` (string): Standard ISO 4217 code (`USD`).
- `rating` (float): 1.0 to 5.0 customer review rating.
- `review_count` (int): Number of customer ratings.
- `specs` (dict): Domain-specific technical specifications.
- `features` (list[str]): Key selling points and standout capabilities.
- `tags` (list[str]): Semantic labels for synonym mapping and candidate retrieval.
- `purpose` (list[str]): Target user personas and application scenarios.
- `stores` (list[dict]): Associated retail stores offering the product.
