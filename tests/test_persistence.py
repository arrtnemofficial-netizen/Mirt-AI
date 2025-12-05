"""Tests for persistence layer factories.

Tests:
1. Session store factory returns correct type based on env vars
2. Checkpointer selection based on DATABASE_URL
3. Health check functionality
"""

import pytest
from unittest.mock import patch, MagicMock

from src.services.persistence import (
    PersistenceMode,
    get_database_url,
    can_use_persistent_checkpointer,
)


class TestDatabaseUrlHelper:
    """Tests for get_database_url function."""

    @patch("src.services.persistence.settings")
    def test_returns_database_url_when_explicitly_set(self, mock_settings):
        """When DATABASE_URL is set, return it directly."""
        # Arrange
        mock_settings.DATABASE_URL = "postgresql://user:pass@host:5432/db"
        mock_settings.SUPABASE_URL = None
        mock_settings.SUPABASE_API_KEY = None

        # Act
        result = get_database_url()

        # Assert
        assert result == "postgresql://user:pass@host:5432/db"

    @patch("src.services.persistence.settings")
    def test_returns_none_when_no_url_configured(self, mock_settings):
        """When no DATABASE_URL or Supabase configured, return None."""
        # Arrange
        mock_settings.DATABASE_URL = None
        mock_settings.SUPABASE_URL = None
        mock_settings.SUPABASE_API_KEY = None

        # Act
        result = get_database_url()

        # Assert
        assert result is None

    @patch("src.services.persistence.settings")
    def test_derives_url_from_supabase_when_database_url_not_set(self, mock_settings):
        """When DATABASE_URL not set but Supabase is, derive from Supabase."""
        # Arrange
        mock_settings.DATABASE_URL = None
        mock_settings.SUPABASE_URL = "https://myproject.supabase.co"
        mock_api_key = MagicMock()
        mock_api_key.get_secret_value.return_value = "my-secret-key"
        mock_settings.SUPABASE_API_KEY = mock_api_key

        # Act
        result = get_database_url()

        # Assert
        assert result is not None
        assert "myproject" in result
        assert "my-secret-key" in result
        assert "postgresql://" in result


class TestCanUsePersistentCheckpointer:
    """Tests for can_use_persistent_checkpointer function."""

    @patch("src.services.persistence.get_database_url")
    def test_returns_true_when_database_url_available(self, mock_get_url):
        """When DATABASE_URL is available, return True."""
        mock_get_url.return_value = "postgresql://..."

        assert can_use_persistent_checkpointer() is True

    @patch("src.services.persistence.get_database_url")
    def test_returns_false_when_database_url_not_available(self, mock_get_url):
        """When DATABASE_URL is not available, return False."""
        mock_get_url.return_value = None

        assert can_use_persistent_checkpointer() is False


class TestPersistenceModeEnum:
    """Tests for PersistenceMode enum."""

    def test_persistent_mode_value(self):
        assert PersistenceMode.PERSISTENT == "persistent"

    def test_in_memory_mode_value(self):
        assert PersistenceMode.IN_MEMORY == "in_memory"
