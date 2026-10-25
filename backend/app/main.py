"""
ShopSense AI — FastAPI Main Application
Exposes REST endpoints for Chat, Search, Compare, Why-Not, Refine, Session, and Consented Preferences.
Includes CORS, request size limit middleware, safe exception handling, and OpenAPI documentation.
"""

import logging
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.api.routes.catalog import router as catalog_router
from app.api.routes.chat import router as chat_router
from app.api.routes.search import router as search_router
from app.api.routes.compare import router as compare_router
from app.api.routes.why_not import router as why_not_router
from app.api.routes.refine import router as refine_router
from app.api.routes.session import router as session_router
from app.api.routes.preferences import router as preferences_router
from app.api.routes.stores import router as stores_router

# Configure structured logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("shopsense.api")


# Middleware: Protect against oversized request payloads (1MB limit)
class ContentSizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_content_size: int = 1_048_576):  # 1MB limit
        super().__init__(app)
        self.max_content_size = max_content_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > self.max_content_size:
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": True,
                    "message": "Request payload exceeds maximum allowed size limit (1MB).",
                    "status_code": 413
                }
            )
        return await call_next(request)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Conversational Shopping Assistant Backend powered by LangGraph and 10 specialized agents.",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Request Size Limit Middleware
app.add_middleware(ContentSizeLimitMiddleware)

# CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handler (Never leaks internal stack traces to clients)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled error processing {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": True,
            "message": "An internal error occurred while processing your shopping request. Please try again.",
            "status_code": 500
        }
    )


# Register API Routers
app.include_router(chat_router)
app.include_router(search_router)
app.include_router(compare_router)
app.include_router(why_not_router)
app.include_router(refine_router)
app.include_router(session_router)
app.include_router(preferences_router)
app.include_router(catalog_router)
app.include_router(stores_router)


# Health Check Endpoints
@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
async def health_check():
    """Service health and agent diagnostic check."""
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "activeAgents": 10,
        "groq_configured": bool(settings.GROQ_API_KEY and not settings.MOCK_LLM_FOR_TESTS),
        "environment": "development" if settings.DEBUG else "production"
    }


@app.get("/", tags=["Root"])
async def root():
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
        "docs_url": "/docs"
    }
