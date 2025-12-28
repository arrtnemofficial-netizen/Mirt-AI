import pytest


@pytest.mark.asyncio
async def test_escalation_does_not_inject_night_message(monkeypatch: pytest.MonkeyPatch):
    """
    Requirement: managers can be notified at any time, and we should NOT add
    'morning message' to the client anymore.
    """
    from src.agents.langgraph.nodes.escalation import escalation_node

    state = {
        "session_id": "s1",
        "current_state": "STATE_0_INIT",
        "trace_id": "t1",
        "messages": [{"role": "user", "content": "help"}],
        "retry_count": 0,
        "max_retries": 3,
        "metadata": {},
    }

    # Avoid real notification call
    class _Notifier:
        async def send_escalation_alert(self, *_args, **_kwargs):
            return None

    import src.services.notifications as notif_mod

    monkeypatch.setattr(notif_mod, "NotificationService", lambda: _Notifier())

    # Avoid Sitniks call
    import src.integrations.crm.sitniks_chat_service as sit_mod

    class _Svc:
        enabled = False

    monkeypatch.setattr(sit_mod, "get_sitniks_chat_service", lambda: _Svc())

    out = await escalation_node(state)
    assert "messages" in out
    # The message inserted by escalation node should be human escalation text,
    # but must NOT be the old night-message
    assistant_json = out["messages"][0]["content"]
    assert "Спеціаліст зв'яжеться з вами вранці" not in assistant_json


