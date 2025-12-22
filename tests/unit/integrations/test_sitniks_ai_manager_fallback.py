"""Tests for Sitniks AI manager fallback to Павло.

Tests that handle_first_touch uses fallback to "Павло" when AI manager is not found.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integrations.crm.sitniks_chat_service import SitniksChatService


class TestAIManagerFallback:
    """Tests for AI manager fallback logic."""

    @pytest.fixture
    def service(self):
        """Create SitniksChatService instance."""
        with patch("src.integrations.crm.sitniks_chat_service.get_supabase_client"):
            service = SitniksChatService()
            return service

    @patch("src.integrations.crm.sitniks_chat_service.settings")
    async def test_fallback_to_pavlo_when_ai_manager_not_found(self, mock_settings, service):
        """Test that Павло is used as fallback when AI manager is not found."""
        mock_settings.SITNIKS_AI_MANAGER_NAME = "AI Manager"

        # Mock find_chat_by_username
        service.find_chat_by_username = AsyncMock(return_value="chat123")

        # Mock get_manager_id_by_name - AI manager not found, but Павло found
        service.get_manager_id_by_name = AsyncMock(side_effect=lambda name: {
            "AI Manager": None,
            "Павло": 42,
        }.get(name, None))

        # Mock other methods
        service._save_chat_mapping = AsyncMock()
        service.update_chat_status = AsyncMock(return_value=True)
        service.assign_manager = AsyncMock(return_value=True)

        result = await service.handle_first_touch(
            user_id="user123",
            instagram_username="test_user",
        )

        # Verify Павло was used
        assert result["success"] is True
        assert result["manager_assigned"] is True
        # Verify get_manager_id_by_name was called for both AI Manager and Павло
        assert service.get_manager_id_by_name.call_count >= 2
        # Verify assign_manager was called with Павло's ID
        service.assign_manager.assert_called_once_with("chat123", 42)

    @patch("src.integrations.crm.sitniks_chat_service.settings")
    async def test_use_ai_manager_when_found(self, mock_settings, service):
        """Test that AI manager is used when found."""
        mock_settings.SITNIKS_AI_MANAGER_NAME = "AI Manager"

        service.find_chat_by_username = AsyncMock(return_value="chat123")
        service.get_manager_id_by_name = AsyncMock(return_value=10)  # AI Manager ID
        service._save_chat_mapping = AsyncMock()
        service.update_chat_status = AsyncMock(return_value=True)
        service.assign_manager = AsyncMock(return_value=True)

        result = await service.handle_first_touch(
            user_id="user123",
            instagram_username="test_user",
        )

        assert result["success"] is True
        # Verify AI manager was used (not Павло)
        service.assign_manager.assert_called_once_with("chat123", 10)

    @patch("src.integrations.crm.sitniks_chat_service.settings")
    async def test_fallback_alternative_spellings(self, mock_settings, service):
        """Test that alternative spellings of Павло are tried."""
        mock_settings.SITNIKS_AI_MANAGER_NAME = "AI Manager"

        service.find_chat_by_username = AsyncMock(return_value="chat123")
        
        # Mock get_manager_id_by_name - try different spellings
        call_count = {"count": 0}
        def mock_get_manager(name):
            call_count["count"] += 1
            if name == "AI Manager":
                return None
            elif name == "Павло":
                return None
            elif name == "Pavlo":
                return 42
            return None
        
        service.get_manager_id_by_name = AsyncMock(side_effect=mock_get_manager)
        service._save_chat_mapping = AsyncMock()
        service.update_chat_status = AsyncMock(return_value=True)
        service.assign_manager = AsyncMock(return_value=True)

        result = await service.handle_first_touch(
            user_id="user123",
            instagram_username="test_user",
        )

        assert result["success"] is True
        # Verify alternative spelling was tried
        assert call_count["count"] >= 2
        service.assign_manager.assert_called_once_with("chat123", 42)

