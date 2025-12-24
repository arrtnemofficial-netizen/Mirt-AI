"""Enhanced followup tests for new features.

Tests:
- 4h and 23h followup messages
- Night mode (23:00-07:00 UTC)
- 24h escalation after 23h followup
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.constants import MessageTag
from src.services.domain.engagement.followups import build_followup_message, next_followup_due_at
from src.services.infra.message_store import InMemoryMessageStore, StoredMessage
from src.workers.tasks.followups import (
    handle_24h_followup_escalation,
    send_followup,
)


class TestFollowupMessages:
    """Tests for specific followup messages (4h, 23h)."""

    @patch("src.services.domain.engagement.followups.get_snippet_by_header")
    def test_build_followup_4h(self, mock_snippet):
        """Test 4h followup message."""
        mock_snippet.return_value = ["Підкажіть, будь ласка, все виходить у вас з оплатою?"]

        message = build_followup_message("session1", index=1)

        assert message.session_id == "session1"
        assert message.role == "assistant"
        assert "оплатою" in message.content
        assert MessageTag.followup_tag(1) in message.tags
        mock_snippet.assert_called_with("FOLLOWUP_4H")

    @patch("src.services.domain.engagement.followups.get_snippet_by_header")
    def test_build_followup_23h(self, mock_snippet):
        """Test 23h followup message."""
        mock_snippet.return_value = ["Чи потрібна вам ще допомога з замовленням?"]

        message = build_followup_message("session1", index=2)

        assert message.session_id == "session1"
        assert "допомога" in message.content
        assert MessageTag.followup_tag(2) in message.tags
        mock_snippet.assert_called_with("FOLLOWUP_23H")

    @patch("src.services.domain.engagement.followups.get_snippet_by_header")
    def test_build_followup_other_index(self, mock_snippet):
        """Test followup with other index uses generic snippet."""
        mock_snippet.return_value = ["Generic followup"]

        message = build_followup_message("session1", index=3)

        assert message.content == "Generic followup"
        mock_snippet.assert_called_with("FOLLOWUP_3")


class TestFollowupSchedule:
    """Tests for followup schedule (4h, 23h)."""

    def test_next_followup_4h_schedule(self):
        """Test that followup schedule uses 4h and 23h."""
        base_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        messages = [
            StoredMessage(
                session_id="s1", role="user", content="hi", created_at=base_time
            )
        ]

        # After 4 hours, first followup should be due
        due_at = next_followup_due_at(messages, schedule_hours=[4, 23])
        assert due_at == base_time + timedelta(hours=4)

        # After 23 hours from first followup, second should be due
        followup1 = StoredMessage(
            session_id="s1",
            role="assistant",
            content="followup1",
            created_at=base_time + timedelta(hours=4),
            tags=[MessageTag.followup_tag(1)],
        )
        messages.append(followup1)

        due_at2 = next_followup_due_at(messages, schedule_hours=[4, 23])
        assert due_at2 == (base_time + timedelta(hours=4)) + timedelta(hours=23)


class TestNightMode:
    """Tests for night mode (23:00-07:00 UTC)."""

    @patch("src.workers.tasks.followups.run_followups")
    @patch("src.core.prompt_registry.get_snippet_by_header")
    @patch("src.workers.tasks.followups._send_telegram_followup")
    @patch("src.workers.tasks.followups.datetime")
    def test_send_followup_night_mode(
        self, mock_datetime, mock_send, mock_snippet, mock_run_followups
    ):
        """Test that night mode message is used during night hours."""
        # Create followup for night time (02:00 UTC)
        night_time = datetime(2024, 1, 1, 2, 0, tzinfo=UTC)
        mock_datetime.now.return_value = night_time
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
        mock_snippet.return_value = ["Спеціаліст зв'яжеться з вами вранці 🤍"]

        followup = StoredMessage(
            session_id="s1",
            role="assistant",
            content="Original followup",
            created_at=night_time,
            tags=[MessageTag.followup_tag(1)],
        )
        mock_run_followups.return_value = followup

        # Call task directly (not as Celery task)
        from src.workers.tasks.followups import send_followup
        result = send_followup(
            session_id="s1", channel="telegram", chat_id="123"
        )

        assert result["status"] == "sent"
        # Verify night message was used
        mock_snippet.assert_called_with("FOLLOWUP_NIGHT")
        mock_send.assert_called_once()

    @patch("src.workers.tasks.followups.run_followups")
    @patch("src.workers.tasks.followups._send_telegram_followup")
    @patch("src.workers.tasks.followups.datetime")
    def test_send_followup_day_mode(self, mock_datetime, mock_send, mock_run_followups):
        """Test that normal followup is used during day hours."""
        # Create followup for day time (14:00 UTC)
        day_time = datetime(2024, 1, 1, 14, 0, tzinfo=UTC)
        mock_datetime.now.return_value = day_time
        mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

        followup = StoredMessage(
            session_id="s1",
            role="assistant",
            content="Day followup",
            created_at=day_time,
            tags=[MessageTag.followup_tag(1)],
        )
        mock_run_followups.return_value = followup

        # Call task directly
        from src.workers.tasks.followups import send_followup
        result = send_followup(
            session_id="s1", channel="telegram", chat_id="123"
        )

        assert result["status"] == "sent"
        # Verify normal message was sent (not night mode)
        mock_send.assert_called_with("123", "Day followup")


class Test24hEscalation:
    """Tests for 24h escalation after 23h followup."""

    @patch("src.workers.tasks.followups.get_supabase_client")
    @patch("src.integrations.manychat.api_client.get_manychat_client")
    @patch("src.integrations.crm.sitniks_chat_service.get_sitniks_chat_service")
    def test_handle_24h_escalation(
        self, mock_sitniks, mock_manychat, mock_supabase
    ):
        """Test 24h escalation task."""
        # Setup mocks
        supabase = MagicMock()
        session_response = MagicMock()
        session_response.data = {"user_id": "user123"}
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            session_response
        )
        mock_supabase.return_value = supabase

        manychat_client = MagicMock()
        manychat_client.is_configured = True
        manychat_client.add_tag = AsyncMock(return_value=True)
        mock_manychat.return_value = manychat_client

        sitniks_service = MagicMock()
        sitniks_service.enabled = True
        sitniks_service.handle_escalation = AsyncMock(
            return_value={"success": True, "status_set": True}
        )
        mock_sitniks.return_value = sitniks_service

        # Call task directly
        from src.workers.tasks.followups import handle_24h_followup_escalation
        result = handle_24h_followup_escalation(
            session_id="s1", channel="manychat", chat_id="subscriber123"
        )

        assert result["status"] == "escalated"
        assert result["user_id"] == "user123"
        # Verify ManyChat tag was added
        manychat_client.add_tag.assert_called_once_with("subscriber123", "humanNeeded-wd")
        # Verify Sitniks escalation was called
        sitniks_service.handle_escalation.assert_called_once_with("user123")

    @patch("src.workers.tasks.followups.get_supabase_client")
    def test_handle_24h_escalation_no_user_id(self, mock_supabase):
        """Test escalation when user_id is not found."""
        supabase = MagicMock()
        session_response = MagicMock()
        session_response.data = None
        supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = (
            session_response
        )
        mock_supabase.return_value = supabase

        # Call task directly
        from src.workers.tasks.followups import handle_24h_followup_escalation
        result = handle_24h_followup_escalation(session_id="s1", channel="telegram", chat_id="123")

        assert result["status"] == "skipped"
        assert result["reason"] == "no_user_id"

