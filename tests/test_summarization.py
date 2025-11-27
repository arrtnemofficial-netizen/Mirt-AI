from datetime import datetime, timedelta, timezone

from src.services.message_store import InMemoryMessageStore, StoredMessage
from src.services.summarization import run_retention


def test_run_retention_summarises_and_prunes(monkeypatch):
    # Mock update_user_summary to avoid real Supabase calls
    monkeypatch.setattr("src.services.summarization.update_user_summary", lambda *args, **kwargs: None)
    
    store = InMemoryMessageStore()
    now = datetime(2024, 1, 10, tzinfo=timezone.utc)
    old_time = now - timedelta(days=5)
    store.append(StoredMessage(session_id="s1", role="user", content="hi", created_at=old_time))
    store.append(
        StoredMessage(
            session_id="s1",
            role="assistant",
            content="payload",
            created_at=old_time,
            tags=["humanNeeded-wd"],
        )
    )

    summary = run_retention("s1", store, now=now)

    assert "hi" in summary
    # humanNeeded-wd tag should be removed
    assert "humanNeeded-wd" not in summary
    assert store.list("s1") == []
