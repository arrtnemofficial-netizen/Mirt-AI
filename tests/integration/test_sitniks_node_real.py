"""Real integration tests for Sitniks status node (no mocks).

Tests the LangGraph node with real Sitniks service (if configured).
"""

import pytest

from src.agents.langgraph.nodes.sitniks_status import update_sitniks_status


class TestSitniksStatusNodeReal:
    """Real tests for Sitniks status node."""

    def test_update_status_no_stage_passes_through(self):
        """Test that node passes through when no stage is set."""
        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {},
            "step_number": 1,
        }

        result = update_sitniks_status(state)

        # Should increment step_number and pass through
        assert result["step_number"] == 2

    def test_update_status_no_user_id_passes_through(self):
        """Test that node passes through when no user_id is set."""
        state = {
            "session_id": "s1",
            "metadata": {"stage": "first_touch"},
            "step_number": 1,
        }

        result = update_sitniks_status(state)

        # Should not break, just pass through
        assert result["step_number"] == 2

    def test_update_status_first_touch_real(self):
        """Test first_touch with real Sitniks service."""
        state = {
            "session_id": "s1",
            "user_id": "test_user_123",
            "metadata": {
                "stage": "first_touch",
                "instagram_username": "test_user",
            },
            "step_number": 1,
        }

        # Should not raise even if Sitniks is not configured
        result = update_sitniks_status(state)

        assert result["step_number"] == 2

    def test_update_status_handles_service_disabled(self):
        """Test that node handles disabled service gracefully."""
        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {"stage": "first_touch"},
            "step_number": 1,
        }

        # Should not raise if service is disabled
        result = update_sitniks_status(state)

        assert result["step_number"] == 2

    def test_update_status_handles_errors_gracefully(self):
        """Test that errors don't break the graph."""
        state = {
            "session_id": "s1",
            "user_id": "user123",
            "metadata": {"stage": "invalid_stage"},
            "step_number": 1,
        }

        # Should not raise exception
        result = update_sitniks_status(state)

        assert result["step_number"] == 2

    def test_update_status_different_stages(self):
        """Test that different stages are handled."""
        stages = ["first_touch", "give_requisites", "escalation"]

        for stage in stages:
            state = {
                "session_id": "s1",
                "user_id": "user123",
                "metadata": {"stage": stage},
                "step_number": 1,
            }

            result = update_sitniks_status(state)
            assert result["step_number"] == 2

