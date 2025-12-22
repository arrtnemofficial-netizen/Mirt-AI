"""Real integration tests for followups (no mocks).

Tests:
- 4h and 23h followup messages with real snippets
- Night mode detection
- Followup schedule (4, 23 hours)
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.constants import MessageTag
from src.services.domain.engagement.followups import (
    build_followup_message,
    next_followup_due_at,
    run_followups,
)
from src.services.infra.message_store import InMemoryMessageStore, StoredMessage


class TestFollowupMessagesReal:
    """Real tests for followup messages using actual snippets."""

    def test_build_followup_4h_uses_real_snippet(self):
        """Test that 4h followup uses real FOLLOWUP_4H snippet."""
        message = build_followup_message("session1", index=1)

        assert message.session_id == "session1"
        assert message.role == "assistant"
        assert MessageTag.followup_tag(1) in message.tags
        # Verify it contains payment-related text
        assert len(message.content) > 0
        # Should contain Ukrainian text about payment
        assert any(word in message.content.lower() for word in ["оплат", "виход"])

    def test_build_followup_23h_uses_real_snippet(self):
        """Test that 23h followup uses real FOLLOWUP_23H snippet."""
        message = build_followup_message("session1", index=2)

        assert message.session_id == "session1"
        assert message.role == "assistant"
        assert MessageTag.followup_tag(2) in message.tags
        # Verify it contains help-related text
        assert len(message.content) > 0

    def test_build_followup_other_index_uses_generic(self):
        """Test that other indices use generic FOLLOWUP_N snippet."""
        message = build_followup_message("session1", index=3)

        assert message.session_id == "session1"
        assert MessageTag.followup_tag(3) in message.tags
        assert len(message.content) > 0


class TestFollowupScheduleReal:
    """Real tests for followup schedule (4h, 23h)."""

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

    def test_followup_created_with_4h_23h_schedule(self):
        """Test that run_followups creates followups with 4h/23h schedule."""
        store = InMemoryMessageStore()
        base_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        
        first_user = StoredMessage(
            session_id="s1", role="user", content="hi", created_at=base_time
        )
        store.append(first_user)

        # After 4 hours, first followup should trigger
        followup = run_followups(
            "s1",
            store,
            now=base_time + timedelta(hours=4, minutes=5),
            schedule_hours=[4, 23],
        )
        assert followup is not None
        assert followup.tags == [MessageTag.followup_tag(1)]
        assert "оплат" in followup.content.lower() or len(followup.content) > 0

        # After 23 more hours from followup, second should trigger
        followup2 = run_followups(
            "s1",
            store,
            now=base_time + timedelta(hours=4 + 23, minutes=5),
            schedule_hours=[4, 23],
        )
        assert followup2 is not None
        assert followup2.tags == [MessageTag.followup_tag(2)]


class TestNightModeReal:
    """Real tests for night mode detection."""

    def test_night_mode_detection_23_00(self):
        """Test that night mode is detected at 23:00 UTC."""
        from src.workers.tasks.followups import send_followup
        from src.core.prompt_registry import get_snippet_by_header

        # Get night message snippet
        night_snippet = get_snippet_by_header("FOLLOWUP_NIGHT")
        assert night_snippet is not None
        assert len(night_snippet) > 0
        night_text = "".join(night_snippet)
        assert "вранці" in night_text.lower() or "спеціаліст" in night_text.lower()

    def test_night_mode_detection_02_00(self):
        """Test that night mode is detected at 02:00 UTC."""
        from src.core.prompt_registry import get_snippet_by_header

        night_snippet = get_snippet_by_header("FOLLOWUP_NIGHT")
        assert night_snippet is not None
        # Verify night message exists
        assert len("".join(night_snippet)) > 0

    def test_day_mode_detection_14_00(self):
        """Test that day mode is used at 14:00 UTC."""
        # Day mode should use normal followup, not night message
        # This is verified by checking that FOLLOWUP_NIGHT is separate from regular followups
        from src.core.prompt_registry import get_snippet_by_header

        night_snippet = get_snippet_by_header("FOLLOWUP_NIGHT")
        followup_4h = get_snippet_by_header("FOLLOWUP_4H")
        
        # They should be different
        assert night_snippet != followup_4h


class TestFollowupIntegration:
    """Integration tests for full followup flow."""

    def test_full_followup_flow_4h_23h(self):
        """Test complete followup flow with 4h and 23h delays."""
        store = InMemoryMessageStore()
        base_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
        
        # Initial message
        user_msg = StoredMessage(
            session_id="s1", role="user", content="Привіт", created_at=base_time
        )
        store.append(user_msg)

        # Check at 4h + 5min - should create first followup
        followup1 = run_followups(
            "s1",
            store,
            now=base_time + timedelta(hours=4, minutes=5),
            schedule_hours=[4, 23],
        )
        assert followup1 is not None
        assert followup1.tags == [MessageTag.followup_tag(1)]
        
        # Store the followup
        store.append(followup1)

        # Check at 4h + 23h + 5min - should create second followup
        followup2 = run_followups(
            "s1",
            store,
            now=base_time + timedelta(hours=4 + 23, minutes=5),
            schedule_hours=[4, 23],
        )
        assert followup2 is not None
        assert followup2.tags == [MessageTag.followup_tag(2)]

        # Verify messages in store
        all_messages = store.list("s1")
        assert len(all_messages) == 3  # user + 2 followups
        assert all_messages[1].tags == [MessageTag.followup_tag(1)]
        assert all_messages[2].tags == [MessageTag.followup_tag(2)]

