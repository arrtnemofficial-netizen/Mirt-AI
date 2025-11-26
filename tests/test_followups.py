from datetime import datetime, timedelta, timezone

from src.services.followups import FOLLOWUP_TAG_PREFIX, next_followup_due_at, run_followups
from src.services.message_store import InMemoryMessageStore, StoredMessage


def test_next_followup_due_when_no_messages():
    assert next_followup_due_at([], schedule_hours=[24]) is None


def test_followups_created_using_custom_schedule():
    store = InMemoryMessageStore()
    base_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    first_user = StoredMessage(session_id="s1", role="user", content="hi", created_at=base_time)
    store.append(first_user)

    # after 1 hour follow-up should trigger
    followup = run_followups(
        "s1", store, now=base_time + timedelta(hours=1, minutes=5), schedule_hours=[1, 2]
    )
    assert followup is not None
    assert followup.tags == [f"{FOLLOWUP_TAG_PREFIX}1"]
    assert store.list("s1")[-1].content == followup.content

    # second follow-up only after 2 more hours from last activity (follow-up message)
    followup2 = run_followups(
        "s1", store, now=base_time + timedelta(hours=2, minutes=5), schedule_hours=[1, 2]
    )
    assert followup2 is None

    followup3 = run_followups(
        "s1", store, now=base_time + timedelta(hours=3, minutes=5), schedule_hours=[1, 2]
    )
    assert followup3 is not None
    assert followup3.tags == [f"{FOLLOWUP_TAG_PREFIX}2"]
