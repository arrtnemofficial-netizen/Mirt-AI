"""
SMOKE: Test external service connections.

These tests verify we can reach external services.
They use real credentials from .env file.
"""

import os

import pytest


@pytest.mark.smoke
@pytest.mark.integration
class TestDatabaseConnection:
    """Test PostgreSQL database connectivity."""

    @pytest.mark.asyncio
    async def test_postgres_client_connects(self):
        """PostgreSQL client can connect."""
        import psycopg

        url = os.getenv("DATABASE_URL")

        if not url or "test" in url.lower():
            pytest.skip("No real PostgreSQL credentials")

        with psycopg.connect(url) as conn:
            assert conn is not None

    @pytest.mark.asyncio
    async def test_postgres_can_query(self):
        """PostgreSQL can execute a simple query."""
        import psycopg

        url = os.getenv("DATABASE_URL")

        if not url or "test" in url.lower():
            pytest.skip("No real PostgreSQL credentials")

        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
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
        if not api_key or api_key.startswith("test"):
            pytest.skip("No real OpenAI credentials")

        client = openai.OpenAI(api_key=api_key)
        assert client is not None

    @pytest.mark.asyncio
    async def test_openai_can_complete(self):
        """OpenAI can complete a simple request."""
        import openai

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key.startswith("test"):
            pytest.skip("No real OpenAI credentials")

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
