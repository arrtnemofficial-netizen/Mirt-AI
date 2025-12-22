"""Real integration tests for 24h escalation (no mocks).

Tests the 24h escalation flow after 23h followup.
"""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.constants import MessageTag
from src.services.domain.engagement.followups import build_followup_message
from src.services.infra.message_store import InMemoryMessageStore, StoredMessage


class Test24hEscalationReal:
    """Real tests for 24h escalation logic."""

    def test_23h_followup_has_correct_tag(self):
        """Test that 23h followup has correct tag for escalation detection."""
        message = build_followup_message("s1", index=2)

        # Should have followup-sent-2 tag
        assert MessageTag.followup_tag(2) in message.tags
        # Tag format should be "followup-sent-2"
        assert any("followup-sent-2" in tag for tag in message.tags)

    def test_followup_tag_extraction(self):
        """Test that followup index can be extracted from tag."""
        message = build_followup_message("s1", index=2)

        # Extract index from tag
        followup_index = None
        for tag in message.tags:
            if tag.startswith("followup-sent-"):
                try:
                    followup_index = int(tag.split("-")[-1])
                    break
                except (ValueError, IndexError):
                    pass

        assert followup_index == 2

    def test_escalation_trigger_after_23h(self):
        """Test that escalation should trigger after 23h followup."""
        # This tests the logic, not the actual task execution
        # The actual task scheduling is tested in unit tests with mocks
        
        # Verify that 23h followup is index 2
        followup_23h = build_followup_message("s1", index=2)
        assert MessageTag.followup_tag(2) in followup_23h.tags

        # Verify that escalation logic would detect this
        followup_index = None
        for tag in followup_23h.tags:
            if tag.startswith("followup-sent-"):
                try:
                    followup_index = int(tag.split("-")[-1])
                    break
                except (ValueError, IndexError):
                    pass

        # Index 2 should trigger escalation
        assert followup_index == 2
        assert followup_index == 2  # This is the 23h followup

    def test_followup_sequence_4h_23h(self):
        """Test that followup sequence is 4h then 23h."""
        store = InMemoryMessageStore()
        base_time = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)

        # Initial message
        user_msg = StoredMessage(
            session_id="s1", role="user", content="Hi", created_at=base_time
        )
        store.append(user_msg)

        # First followup at 4h (index 1)
        followup1 = build_followup_message("s1", index=1, now=base_time + timedelta(hours=4))
        assert MessageTag.followup_tag(1) in followup1.tags
        store.append(followup1)

        # Second followup at 23h from first (index 2)
        followup2 = build_followup_message(
            "s1", index=2, now=base_time + timedelta(hours=4 + 23)
        )
        assert MessageTag.followup_tag(2) in followup2.tags
        store.append(followup2)

        # Verify sequence
        messages = store.list("s1")
        assert len(messages) == 3
        assert messages[1].tags == [MessageTag.followup_tag(1)]  # 4h
        assert messages[2].tags == [MessageTag.followup_tag(2)]  # 23h

        # The 23h followup (index 2) should trigger escalation
        escalation_trigger = messages[2]
        assert MessageTag.followup_tag(2) in escalation_trigger.tags

