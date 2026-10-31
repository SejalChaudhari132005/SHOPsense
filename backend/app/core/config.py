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
    HYBRID_EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    HYBRID_INDEX_CACHE_DIR: str = str(BACKEND_DIR / "data" / "hybrid_index")
    HYBRID_RRF_K: int = Field(default=60, ge=1)
    HYBRID_RETRIEVAL_LIMIT: int = Field(default=20, ge=1)
    HYBRID_MIN_COSINE_SIMILARITY: float = Field(default=0.15, ge=-1.0, le=1.0)
    HYBRID_COSINE_FLOOR: float = Field(default=0.25, ge=-1.0, le=1.0)
    HYBRID_COSINE_CEIL: float = Field(default=0.60, ge=-1.0, le=1.0)
    MIN_RELEVANCE: float = Field(default=0.30, ge=0.0, le=1.0)

    # Testing & Mocking (automatically mock during pytest to preserve API quotas and avoid 429 rate limits)
    MOCK_LLM_FOR_TESTS: bool = ("pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ)

    # Local mock catalog is the only default product source.
    STORE_ADAPTER_TIMEOUT_SECONDS: float = 3.0
    ENABLED_STORE_ADAPTERS: List[str] = ["local_catalog"]

    model_config = SettingsConfigDict(
        env_file=(
            str(PROJECT_ROOT / ".env"),
            str(BACKEND_DIR / ".env"),
            ".env",
        ),
        extra="ignore"
    )

settings = Settings()
