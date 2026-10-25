import sys
import os
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from pathlib import Path

# Base paths
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

class Settings(BaseSettings):
    PROJECT_NAME: str = "ShopSense AI Backend"
    VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Server
    BACKEND_HOST: str = "127.0.0.1"
    BACKEND_PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Groq API Configuration (Backend-only)
    GROQ_API_KEY: str = Field(default="", description="Secret key for Groq API")
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # CORS
    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "chrome-extension://*"
    ]

    # Storage & Catalog
    SQLITE_DB_PATH: str = str(BACKEND_DIR / "data" / "shopsense_preferences.db")
    CATALOG_PATH: str = str(PROJECT_ROOT / "catalog" / "demo_products.json")

    # Testing & Mocking (automatically mock during pytest to preserve API quotas and avoid 429 rate limits)
    MOCK_LLM_FOR_TESTS: bool = ("pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ)

    # Multi-Store Adapter Integrations
    # Amazon India (Product Advertising API 5.0)
    AMAZON_PA_API_KEY: str = Field(default="", description="Amazon PA-API Access Key ID")
    AMAZON_PA_API_SECRET: str = Field(default="", description="Amazon PA-API Secret Key")
    AMAZON_ASSOCIATE_TAG: str = Field(default="", description="Amazon India Associates Tracking Tag (e.g. yourtag-21)")
    AMAZON_REGION: str = "eu-west-1"
    AMAZON_HOST: str = "webservices.amazon.in"
    AMAZON_ENABLE_MOCK_FALLBACK: bool = True

    # Flipkart Affiliate API
    FLIPKART_AFFILIATE_ID: str = Field(default="", description="Flipkart Affiliate Tracking ID")
    FLIPKART_AFFILIATE_TOKEN: str = Field(default="", description="Flipkart Affiliate API Token")
    FLIPKART_ENABLE_MOCK_FALLBACK: bool = True

    # Multi-Store Orchestration Settings
    STORE_ADAPTER_TIMEOUT_SECONDS: float = 3.0
    ENABLED_STORE_ADAPTERS: List[str] = ["local_catalog", "amazon_in", "flipkart"]

    model_config = SettingsConfigDict(
        env_file=(
            str(PROJECT_ROOT / ".env"),
            str(BACKEND_DIR / ".env"),
            ".env",
        ),
        extra="ignore"
    )

settings = Settings()
