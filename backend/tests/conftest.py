import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

from app.core.config import settings

@pytest.fixture(autouse=True)
def mock_llm_for_tests():
    old = settings.MOCK_LLM_FOR_TESTS
    settings.MOCK_LLM_FOR_TESTS = True
    yield
    settings.MOCK_LLM_FOR_TESTS = old

@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
