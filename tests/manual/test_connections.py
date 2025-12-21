"""
SMOKE: Test external service connections.

These tests verify we can reach external services.
They use real credentials from .env file.
"""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv


load_dotenv(Path(__file__).parent.parent / ".env")


@pytest.mark.smoke
@pytest.mark.integration
class TestDatabaseConnection:
    """Test Supabase database connectivity."""

    @pytest.mark.asyncio
    async def test_supabase_client_creates(self):
        """Supabase client can be created."""
        from supabase import create_client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_API_KEY")

        if not url or not key:
            pytest.fail("SUPABASE_URL or SUPABASE_API_KEY is not set for live tests.")
        if "test" in url.lower():
            pytest.fail("SUPABASE_URL points to a test environment; use real prod URL.")

        client = create_client(url, key)
        assert client is not None

    @pytest.mark.asyncio
    async def test_supabase_can_query(self):
        """Supabase can execute a simple query."""
        from supabase import create_client

        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_API_KEY")

        if not url or not key:
            pytest.fail("SUPABASE_URL or SUPABASE_API_KEY is not set for live tests.")
        if "test" in url.lower():
            pytest.fail("SUPABASE_URL points to a test environment; use real prod URL.")

        client = create_client(url, key)
        # Try to query products table (should exist)
        result = client.table("products").select("id").limit(1).execute()
        assert result is not None


@pytest.mark.smoke
@pytest.mark.integration
class TestLLMConnection:
    """Test LLM API connectivity."""

    @pytest.mark.asyncio
    async def test_openai_client_creates(self):
        """OpenAI client can be created."""
        import openai

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            pytest.fail("OPENAI_API_KEY is not set for live tests.")
        if api_key.startswith("test"):
            pytest.fail("OPENAI_API_KEY looks like a test key; use real key.")

        client = openai.OpenAI(api_key=api_key)
        assert client is not None

    @pytest.mark.asyncio
    async def test_openai_can_complete(self):
        """OpenAI can complete a simple request."""
        import openai

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            pytest.fail("OPENAI_API_KEY is not set for live tests.")
        if api_key.startswith("test"):
            pytest.fail("OPENAI_API_KEY looks like a test key; use real key.")

        client = openai.OpenAI(api_key=api_key)

        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Use cheap model for smoke test
            messages=[{"role": "user", "content": "Say 'OK'"}],
            max_tokens=5,
        )

        assert response.choices[0].message.content is not None


@pytest.mark.smoke
@pytest.mark.integration
class TestCRMConnection:
    """Test Sitniks CRM connectivity."""

    @pytest.mark.asyncio
    async def test_crm_service_creates(self):
        """CRM service can be instantiated."""
        from src.integrations.crm.sitniks_chat_service import SitniksChatService

        service = SitniksChatService()
        assert service is not None

    @pytest.mark.asyncio
    async def test_crm_enabled_check(self):
        """CRM enabled check works."""
        from src.integrations.crm.sitniks_chat_service import SitniksChatService

        service = SitniksChatService()
        # Should return bool without error
        enabled = service.enabled
        assert isinstance(enabled, bool)
