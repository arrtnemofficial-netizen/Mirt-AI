"""Tests for users table population in PostgresMessageStore."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from src.services.storage.postgres_message_store import PostgresMessageStore


class TestUsersTablePopulation:
    """Test that users table is populated correctly with all fields."""

    @patch("src.services.storage.postgres_message_store.psycopg")
    def test_users_table_populates_username_from_instagram(self, mock_psycopg):
        """Test that username is populated from instagram_username when available."""
        # Setup mock connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_psycopg.connect.return_value.__enter__.return_value = mock_conn
        
        store = PostgresMessageStore()
        
        # Metadata with instagram_username but no explicit username
        metadata = {
            "instagram_username": "test_instagram_user",
            "user_id": "test_user_123",
        }
        
        # Call _update_user_interaction
        store._update_user_interaction(mock_conn, "test_user_123", metadata=metadata)
        
        # Verify the SQL was called
        assert mock_cur.execute.called
        
        # Get the SQL call arguments
        call_args = mock_cur.execute.call_args
        sql = call_args[0][0]
        params = call_args[0][1]
        
        # Verify username is set from instagram_username
        assert params[3] == "test_instagram_user"  # username parameter
        assert params[1] == "test_instagram_user"  # instagram_username parameter

    @patch("src.services.storage.postgres_message_store.psycopg")
    def test_users_table_does_not_overwrite_telegram_username(self, mock_psycopg):
        """Test that telegram_username is not overwritten if not provided."""
        # Setup mock connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_psycopg.connect.return_value.__enter__.return_value = mock_conn
        
        store = PostgresMessageStore()
        
        # Metadata with instagram_username but no telegram_username
        metadata = {
            "instagram_username": "test_instagram_user",
            "user_id": "test_user_123",
        }
        
        # Call _update_user_interaction
        store._update_user_interaction(mock_conn, "test_user_123", metadata=metadata)
        
        # Verify the SQL was called
        assert mock_cur.execute.called
        
        # Get the SQL call arguments
        call_args = mock_cur.execute.call_args
        params = call_args[0][1]
        
        # Verify telegram_username is None (not provided)
        assert params[2] is None  # telegram_username parameter

    @patch("src.services.storage.postgres_message_store.psycopg")
    def test_users_table_updates_all_fields(self, mock_psycopg):
        """Test that all available fields are populated correctly."""
        # Setup mock connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_psycopg.connect.return_value.__enter__.return_value = mock_conn
        
        store = PostgresMessageStore()
        
        # Metadata with all fields
        metadata = {
            "instagram_username": "test_instagram",
            "telegram_username": "test_telegram",
            "username": "test_explicit_username",
            "user_id": "test_user_123",
        }
        
        # Call _update_user_interaction
        store._update_user_interaction(mock_conn, "test_user_123", metadata=metadata)
        
        # Verify the SQL was called
        assert mock_cur.execute.called
        
        # Get the SQL call arguments
        call_args = mock_cur.execute.call_args
        params = call_args[0][1]
        
        # Verify all fields are set correctly
        assert params[0] == "test_user_123"  # user_id
        assert params[1] == "test_instagram"  # instagram_username
        assert params[2] == "test_telegram"  # telegram_username
        assert params[3] == "test_explicit_username"  # username (explicit takes priority)

    @patch("src.services.storage.postgres_message_store.psycopg")
    def test_users_table_username_fallback_logic(self, mock_psycopg):
        """Test username fallback logic: explicit > instagram > telegram."""
        # Setup mock connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_psycopg.connect.return_value.__enter__.return_value = mock_conn
        
        store = PostgresMessageStore()
        
        # Test case 1: Only instagram_username
        metadata1 = {"instagram_username": "instagram_only"}
        store._update_user_interaction(mock_conn, "user1", metadata=metadata1)
        call_args1 = mock_cur.execute.call_args
        params1 = call_args1[0][1]
        assert params1[3] == "instagram_only"  # username should be instagram_username
        
        # Reset mock
        mock_cur.reset_mock()
        
        # Test case 2: Only telegram_username
        metadata2 = {"telegram_username": "telegram_only"}
        store._update_user_interaction(mock_conn, "user2", metadata=metadata2)
        call_args2 = mock_cur.execute.call_args
        params2 = call_args2[0][1]
        assert params2[3] == "telegram_only"  # username should be telegram_username
        
        # Reset mock
        mock_cur.reset_mock()
        
        # Test case 3: Both instagram and telegram (instagram takes priority)
        metadata3 = {
            "instagram_username": "instagram_user",
            "telegram_username": "telegram_user",
        }
        store._update_user_interaction(mock_conn, "user3", metadata=metadata3)
        call_args3 = mock_cur.execute.call_args
        params3 = call_args3[0][1]
        assert params3[3] == "instagram_user"  # instagram takes priority

    @patch("src.services.storage.postgres_message_store.psycopg")
    def test_users_table_handles_empty_metadata(self, mock_psycopg):
        """Test that empty metadata doesn't cause errors."""
        # Setup mock connection
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_psycopg.connect.return_value.__enter__.return_value = mock_conn
        
        store = PostgresMessageStore()
        
        # Call with None metadata
        store._update_user_interaction(mock_conn, "test_user", metadata=None)
        
        # Should not raise exception
        assert mock_cur.execute.called
        
        # Get the SQL call arguments
        call_args = mock_cur.execute.call_args
        params = call_args[0][1]
        
        # All username fields should be None
        assert params[1] is None  # instagram_username
        assert params[2] is None  # telegram_username
        assert params[3] is None  # username

