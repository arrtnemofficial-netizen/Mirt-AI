"""Tests for Sitniks status update endpoint and idempotency.

These tests verify:
1. POST /api/v1/sitniks/update-status endpoint behavior
2. Authentication handling
3. Stage-based status updates (first_touch, invoice, escalation)
4. Idempotency for ManyChat create-order endpoint
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_settings():
    """Mock settings with test values."""
    with patch("src.server.main.settings") as mock:
        mock.MANYCHAT_VERIFY_TOKEN = "test-token"
        mock.TELEGRAM_BOT_TOKEN = MagicMock()
        mock.TELEGRAM_BOT_TOKEN.get_secret_value.return_value = ""
        mock.PUBLIC_BASE_URL = "http://localhost:8000"
        mock.TELEGRAM_WEBHOOK_PATH = "/webhooks/telegram"
        mock.SENTRY_DSN = ""
        mock.CELERY_ENABLED = False
        mock.LLM_PROVIDER = "openai"
        mock.active_llm_model = "gpt-4"
        mock.SUPABASE_TABLE = "test_sessions"
        yield mock


@pytest.fixture
def mock_sitniks_service():
    """Mock SitniksChatService."""
    with patch("src.integrations.crm.sitniks_chat_service.get_sitniks_chat_service") as mock_get:
        service = MagicMock()
        service.enabled = True
        service.handle_first_touch = AsyncMock(return_value={
            "success": True,
            "chat_id": "chat_123",
            "status_set": True,
            "manager_assigned": True,
            "error": None,
        })
        service.handle_invoice_sent = AsyncMock(return_value=True)
        service.handle_escalation = AsyncMock(return_value={
            "success": True,
            "chat_id": "chat_123",
            "status_set": True,
            "manager_assigned": True,
        })
        mock_get.return_value = service
        yield service


@pytest.fixture
def client(mock_settings):
    """Create test client with mocked settings."""
    with patch("src.server.main.get_bot"), \
         patch("src.server.main.setup_middleware"), \
         patch("src.services.supabase_client.get_supabase_client", return_value=None):
        from src.server.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client


class TestSitniksUpdateStatusEndpoint:
    """Tests for /api/v1/sitniks/update-status endpoint."""

    def test_auth_required(self, client, mock_settings):
        """Test that authentication is required."""
        mock_settings.MANYCHAT_VERIFY_TOKEN = "secret-token"
        
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "first_touch",
                "user_id": "12345",
            },
            headers={"X-API-Key": "wrong-token"},
        )
        
        assert response.status_code == 401

    def test_auth_with_bearer_token(self, client, mock_settings, mock_sitniks_service):
        """Test authentication with Bearer token."""
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "first_touch",
                "user_id": "12345",
                "instagram_username": "testuser",
            },
            headers={"Authorization": "Bearer test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_first_touch_stage(self, client, mock_settings, mock_sitniks_service):
        """Test first_touch stage calls handle_first_touch."""
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "first_touch",
                "user_id": "12345",
                "instagram_username": "testuser",
            },
            headers={"X-API-Key": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["stage"] == "first_touch"
        assert data["chat_id"] == "chat_123"
        assert data["status_set"] is True
        assert data["manager_assigned"] is True
        
        mock_sitniks_service.handle_first_touch.assert_called_once_with(
            user_id="12345",
            instagram_username="testuser",
            telegram_username=None,
        )

    def test_give_requisites_stage(self, client, mock_settings, mock_sitniks_service):
        """Test give_requisites stage calls handle_invoice_sent."""
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "give_requisites",
                "user_id": "12345",
            },
            headers={"X-API-Key": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["stage"] == "give_requisites"
        
        mock_sitniks_service.handle_invoice_sent.assert_called_once_with("12345")

    def test_invoice_alias(self, client, mock_settings, mock_sitniks_service):
        """Test 'invoice' as alias for give_requisites."""
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "invoice",
                "user_id": "12345",
            },
            headers={"X-API-Key": "test-token"},
        )
        
        assert response.status_code == 200
        mock_sitniks_service.handle_invoice_sent.assert_called_once()

    def test_escalation_stage(self, client, mock_settings, mock_sitniks_service):
        """Test escalation stage calls handle_escalation."""
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "escalation",
                "user_id": "12345",
            },
            headers={"X-API-Key": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["stage"] == "escalation"
        assert data["manager_assigned"] is True
        
        mock_sitniks_service.handle_escalation.assert_called_once_with("12345")

    def test_unknown_stage(self, client, mock_settings, mock_sitniks_service):
        """Test unknown stage returns error."""
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "unknown_stage",
                "user_id": "12345",
            },
            headers={"X-API-Key": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "Unknown stage" in data["error"]

    def test_service_not_enabled(self, client, mock_settings, mock_sitniks_service):
        """Test response when Sitniks service is not enabled."""
        mock_sitniks_service.enabled = False
        
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "first_touch",
                "user_id": "12345",
            },
            headers={"X-API-Key": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "not configured" in data["error"]

    def test_field_aliases(self, client, mock_settings, mock_sitniks_service):
        """Test that field aliases work (userId, sessionId, etc.)."""
        response = client.post(
            "/api/v1/sitniks/update-status",
            json={
                "stage": "first_touch",
                "userId": "12345",  # camelCase alias
                "instagramUsername": "testuser",  # camelCase alias
            },
            headers={"X-API-Key": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestCreateOrderIdempotency:
    """Tests for idempotency in /webhooks/manychat/create-order."""

    @pytest.fixture
    def mock_crm(self):
        """Mock Snitkix CRM client.
        
        SENIOR TIP: Patch where the function is IMPORTED, not where it's DEFINED.
        Since main.py does `from src.integrations.crm.snitkix import get_snitkix_client`
        inside the endpoint function, we need to patch the source module.
        """
        with patch("src.integrations.crm.snitkix.get_snitkix_client") as mock_get:
            crm = MagicMock()
            crm.create_order = AsyncMock(return_value=MagicMock(
                success=True,
                order_id="crm_order_456",
                error=None,
            ))
            mock_get.return_value = crm
            yield crm

    @pytest.fixture
    def mock_supabase(self):
        """Mock Supabase client for idempotency checks."""
        with patch("src.services.supabase_client.get_supabase_client") as mock_get:
            client = MagicMock()
            # Default: no existing order
            client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])
            mock_get.return_value = client
            yield client

    @pytest.fixture
    def mock_validation(self):
        """Mock order validation - patch at source module."""
        with patch("src.services.order_model.validate_order_data") as mock:
            mock.return_value = MagicMock(
                can_submit_to_crm=True,
                missing_fields=[],
            )
            yield mock

    def test_new_order_created(self, client, mock_settings, mock_crm, mock_supabase, mock_validation):
        """Test that new order is created when no duplicate exists."""
        response = client.post(
            "/webhooks/manychat/create-order",
            json={
                "subscriber": {"id": "12345"},
                "custom_fields": {
                    "client_name": "Тест Тестович",
                    "client_phone": "+380501234567",
                    "client_city": "Київ",
                    "client_nova_poshta": "25",
                    "last_product": "Сукня Анна",
                    "order_sum": "1200",
                },
            },
            headers={"X-Manychat-Token": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["order_id"] == "crm_order_456"
        assert "duplicate" not in data or data["duplicate"] is False
        
        # Verify CRM was called
        mock_crm.create_order.assert_called_once()

    def test_duplicate_order_detected(self, client, mock_settings, mock_crm, mock_supabase, mock_validation):
        """Test that duplicate order returns existing order."""
        # Setup: existing order in DB
        mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "existing_id",
                "crm_order_id": "existing_crm_123",
                "status": "created",
            }]
        )
        
        response = client.post(
            "/webhooks/manychat/create-order",
            json={
                "subscriber": {"id": "12345"},
                "custom_fields": {
                    "client_name": "Тест Тестович",
                    "client_phone": "+380501234567",
                    "client_city": "Київ",
                    "client_nova_poshta": "25",
                    "last_product": "Сукня Анна",
                    "order_sum": "1200",
                },
            },
            headers={"X-Manychat-Token": "test-token"},
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["duplicate"] is True
        assert data["order_id"] == "existing_crm_123"
        
        # Verify CRM was NOT called (duplicate detected)
        mock_crm.create_order.assert_not_called()

    def test_idempotency_key_deterministic(self, client, mock_settings, mock_crm, mock_supabase, mock_validation):
        """Test that same input produces same idempotency key."""
        import hashlib
        
        user_id = "12345"
        product_name = "Сукня Анна"
        price = 1200.0
        
        # Calculate expected key
        idempotency_data = f"{user_id}|{product_name.lower().strip()}|{int(price * 100)}"
        idempotency_hash = hashlib.sha256(idempotency_data.encode()).hexdigest()[:16]
        expected_external_id = f"mc_{user_id}_{idempotency_hash}"
        
        response = client.post(
            "/webhooks/manychat/create-order",
            json={
                "subscriber": {"id": user_id},
                "custom_fields": {
                    "client_name": "Тест",
                    "client_phone": "+380501234567",
                    "client_city": "Київ",
                    "client_nova_poshta": "25",
                    "last_product": product_name,
                    "order_sum": str(price),
                },
            },
            headers={"X-Manychat-Token": "test-token"},
        )
        
        assert response.status_code == 200
        
        # Verify the external_id was checked correctly
        call_args = mock_supabase.table.return_value.select.return_value.eq.call_args
        assert call_args[0][1] == expected_external_id

    def test_different_product_different_key(self, mock_settings):
        """Test that different product produces different idempotency key."""
        import hashlib
        
        user_id = "12345"
        price = 1200.0
        
        # Key for product A
        data_a = f"{user_id}|сукня анна|{int(price * 100)}"
        key_a = hashlib.sha256(data_a.encode()).hexdigest()[:16]
        
        # Key for product B
        data_b = f"{user_id}|сукня марія|{int(price * 100)}"
        key_b = hashlib.sha256(data_b.encode()).hexdigest()[:16]
        
        assert key_a != key_b


class TestSitniksChatServiceMapping:
    """Tests for SitniksChatService upsert behavior."""

    @pytest.fixture
    def mock_supabase_for_service(self):
        """Mock Supabase for service tests."""
        with patch("src.integrations.crm.sitniks_chat_service.get_supabase_client") as mock_get:
            client = MagicMock()
            client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])
            mock_get.return_value = client
            yield client

    @pytest.mark.asyncio
    async def test_save_mapping_uses_user_id_conflict(self, mock_supabase_for_service):
        """Test that _save_chat_mapping uses user_id for conflict resolution."""
        with patch("src.integrations.crm.sitniks_chat_service.settings") as mock_settings:
            mock_settings.SNITKIX_API_URL = "https://api.test.com"
            mock_settings.SNITKIX_API_KEY = MagicMock()
            mock_settings.SNITKIX_API_KEY.get_secret_value.return_value = "test-key"
            
            from src.integrations.crm.sitniks_chat_service import SitniksChatService
            
            service = SitniksChatService()
            service.supabase = mock_supabase_for_service
            
            await service._save_chat_mapping(
                user_id="user_123",
                chat_id="chat_456",
                instagram_username="testuser",
                telegram_username=None,
            )
            
            # Verify upsert was called with on_conflict="user_id"
            upsert_call = mock_supabase_for_service.table.return_value.upsert.call_args
            assert upsert_call[1]["on_conflict"] == "user_id"
