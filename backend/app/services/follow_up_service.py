"""
ShopSense AI — Context-Aware Follow-Up Suggestions Service
Offers at most one relevant complementary accessory when it adds genuine utility value.
Respects user budget, avoids irrelevant upselling, and clearly labels demonstration data.
"""

from typing import Optional, List
from app.models.product import Product
from app.models.state import ExtractedIntent, ComplementarySuggestion
from app.services.catalog_service import load_and_validate_catalog
from app.services.currency_service import format_price_in_inr
from app.services.currency_service import convert_currency


# Domain pairings: Primary Category / Tag -> Complementary Product Definition
COMPLEMENTARY_CATALOG = {
    "travel_backpack": {
        "keywords": ["backpack", "travel", "rucksack", "duffel", "luggage"],
        "product": Product(
            product_id="acc_packing_cubes",
            product_name="AeroPack Ultra-Lite Compression Packing Cubes (Set of 3)",
            brand="AeroPack",
            category="travel_accessories",
            price=1665.83,
            currency="INR",
            normalized_price_usd=19.99,
            rating=4.8,
            review_count=340,
            description="Ultra-lightweight ripstop nylon compression packing cubes that organize luggage and compress clothing by up to 40%.",
            tags=["packing cubes", "travel", "compression", "water-resistant", "organizer"],
            specifications={"material": "Ripstop Nylon", "pieces": 3, "weight_g": 180},
            attributes={"water_resistant": True, "washable": True, "store": "ShopSense Catalog"},
            image_url="https://images.unsplash.com/photo-1544816155-12df9643f363?auto=format&fit=crop&w=400&q=80",
            product_url="https://example.com/products/aeropack-cubes",
            in_stock=True
        ),
        "utility": "Compression packing cubes maximize the internal volume of your pack and keep fresh clothes, dirty laundry, and cables neatly partitioned during transit.",
        "why_relevant": "Ideal companion for travel packs, saving up to 40% packing space."
    },
    "running_footwear": {
        "keywords": ["shoe", "footwear", "running", "sneaker", "trail", "marathon"],
        "product": Product(
            product_id="acc_running_socks",
            product_name="SwiftDry Anti-Blister Cushioned Running Socks (3-Pack)",
            brand="SwiftDry",
            category="sports_accessories",
            price=1208.33,
            currency="INR",
            normalized_price_usd=14.50,
            rating=4.7,
            review_count=520,
            description="Technical anti-blister running socks with targeted arch support and moisture-wicking fibers for blister-free comfort.",
            tags=["running socks", "anti-blister", "cushioned", "breathable", "seamless"],
            specifications={"material": "Merino Wool & Synthetic Blend", "cushioning": "Medium", "pairs": 3},
            attributes={"anti_blister": True, "moisture_wicking": True, "store": "ShopSense Catalog"},
            image_url="https://images.unsplash.com/photo-1582966772680-860e372bb558?auto=format&fit=crop&w=400&q=80",
            product_url="https://example.com/products/swiftdry-socks",
            in_stock=True
        ),
        "utility": "Double-layer anti-friction weave prevents hot spots and blisters while technical arch compression supports high-impact strides.",
        "why_relevant": "Engineered pairing for road and trail runners to protect feet during extended sessions."
    },
    "laptops_tech": {
        "keywords": ["laptop", "ultrabook", "computer", "macbook", "notebook"],
        "product": Product(
            product_id="acc_usbc_hub",
            product_name="OmniDock 7-in-1 Aluminum USB-C Hub with 4K HDMI & 100W PD",
            brand="OmniDock",
            category="electronics_accessories",
            price=2082.50,
            currency="INR",
            normalized_price_usd=24.99,
            rating=4.6,
            review_count=890,
            description="7-in-1 USB-C hub offering 4K HDMI, 3 USB 3.0 ports, SD/microSD card reader, and 100W Power Delivery in sleek aluminum.",
            tags=["usb-c", "hub", "hdmi", "dongle", "card reader", "aluminum"],
            specifications={"ports": "HDMI 4K, 3x USB 3.0, SD/TF, 100W PD", "weight_g": 65},
            attributes={"plug_and_play": True, "store": "ShopSense Catalog"},
            image_url="https://images.unsplash.com/photo-1544652478-6653e09f18a2?auto=format&fit=crop&w=400&q=80",
            product_url="https://example.com/products/omnidock-hub",
            in_stock=True
        ),
        "utility": "Restores missing HDMI, SD card reader, and standard USB ports for modern ultra-thin laptops with only Type-C connectivity.",
        "why_relevant": "Enables seamless connectivity for external monitors and flash drives on modern laptops."
    },
    "audio_headphones": {
        "keywords": ["headphone", "audio", "headset", "earphone", "anc", "sound"],
        "product": Product(
            product_id="acc_airplane_transmitter",
            product_name="AirStream Wireless Flight Audio Adapter with Dual Jack",
            brand="AirStream",
            category="audio_accessories",
            price=1500.00,
            currency="INR",
            normalized_price_usd=18.00,
            rating=4.5,
            review_count=210,
            description="Dual 3.5mm airplane entertainment Bluetooth transmitter with 20-hour battery life and ultra-low latency.",
            tags=["bluetooth transmitter", "airplane adapter", "wireless", "battery 20h"],
            specifications={"battery_life_hours": 20, "bluetooth_version": "5.3", "dual_pairing": True},
            attributes={"low_latency": True, "store": "ShopSense Catalog"},
            image_url="https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=400&q=80",
            product_url="https://example.com/products/airstream-adapter",
            in_stock=True
        ),
        "utility": "Plugs into in-flight seat screens and gym treadmills to stream audio directly into your wireless noise-cancelling headphones without cables.",
        "why_relevant": "Provides wireless freedom when traveling on planes or using gym equipment."
    }
}


def find_complementary_suggestion(
    top_product: Product,
    intent: ExtractedIntent
) -> Optional[ComplementarySuggestion]:
    """
    Selects at most ONE relevant, non-pushy companion product based on the recommended item.
    Returns None if no natural pairing exists, preventing intrusive or irrelevant upselling.
    """
    if not top_product:
        return None

    # Identify domain from top product category, tags, and user intent
    text = (
        f"{top_product.category} {top_product.product_name} "
        f"{' '.join(top_product.tags)}"
    ).lower()

    matched_key = None
    for domain_key, item in COMPLEMENTARY_CATALOG.items():
        if any(kw in text for kw in item["keywords"]):
            matched_key = domain_key
            break

    if not matched_key:
        return None

    if matched_key == "audio_headphones":
        return None
    if matched_key == "laptops_tech" and not any(
        marker in text for marker in ("usb-c", "usb c", "type-c", "type c")
    ):
        return None

    entry = COMPLEMENTARY_CATALOG[matched_key]
    companion = entry["product"]

    # Do not recommend add-ons that take the combined spend beyond a hard ceiling.
    if intent.budget_max is not None and intent.is_budget_strict:
        primary_price_inr = convert_currency(
            top_product.price, top_product.currency, "INR"
        )
        budget_inr = convert_currency(
            intent.budget_max, intent.budget_currency, "INR"
        )
        companion_price_inr = convert_currency(
            companion.price, companion.currency, "INR"
        )
        if primary_price_inr + companion_price_inr > budget_inr:
            return None

    # Format localized price
    price_str = format_price_in_inr(companion.price, companion.currency)

    return ComplementarySuggestion(
        product=companion,
        utility_explanation=entry["utility"],
        why_relevant=entry["why_relevant"],
        price_formatted=price_str,
        is_pushy=False,
        data_provenance=(
            "Demo sample data"
            if companion.provenance.is_sample_data
            else "Verified catalog"
        )
    )
