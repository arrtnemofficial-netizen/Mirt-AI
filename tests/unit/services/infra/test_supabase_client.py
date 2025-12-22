"""Unit tests for Supabase client factory."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.services.infra.supabase_client import get_supabase_client


class TestSupabaseClient:
    """Tests for get_supabase_client function."""

    def test_returns_none_when_url_missing(self, monkeypatch):
        """Test that None is returned when SUPABASE_URL is not set."""
        monkeypatch.setattr("src.services.infra.supabase_client.settings.SUPABASE_URL", "")
        get_supabase_client.cache_clear()
        result = get_supabase_client()
        assert result is None

    @patch("src.services.infra.supabase_client.create_client")
    def test_handles_initialization_error(self, mock_create_client, monkeypatch):
        """Test that initialization errors are handled gracefully."""
        from src.conf.config import SecretStr
        monkeypatch.setattr("src.services.infra.supabase_client.settings.SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setattr("src.services.infra.supabase_client.settings.SUPABASE_API_KEY", SecretStr("test_key"))
        mock_create_client.side_effect = Exception("Connection failed")
        get_supabase_client.cache_clear()
        result = get_supabase_client()
        assert result is None
        mock_create_client.assert_called_once()
