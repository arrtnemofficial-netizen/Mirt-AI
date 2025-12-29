"""Test that session store correctly serializes datetime objects from Pydantic models."""

import pytest
from datetime import UTC, datetime, date, time, timedelta
from decimal import Decimal
from uuid import uuid4

from src.services.storage.session_store import _serialize_for_json
from src.agents.pydantic.memory_models import UserProfile, Fact, FactType, FactCategory


def test_serialize_datetime_objects():
    """Test that datetime objects are converted to ISO format strings."""
    now = datetime.now(UTC)
    
    # Test direct datetime serialization
    result = _serialize_for_json(now)
    assert isinstance(result, str)
    assert result == now.isoformat()
    
    # Test date serialization
    today = date.today()
    result = _serialize_for_json(today)
    assert isinstance(result, str)
    assert result == today.isoformat()
    
    # Test time serialization
    current_time = time(12, 30, 45)
    result = _serialize_for_json(current_time)
    assert isinstance(result, str)
    assert result == current_time.isoformat()


def test_serialize_timedelta_objects():
    """Test that timedelta objects are converted to total seconds."""
    delta = timedelta(days=1, hours=2, minutes=30)
    result = _serialize_for_json(delta)
    assert isinstance(result, float)
    assert result == delta.total_seconds()


def test_serialize_userprofile_with_datetime():
    """Test that UserProfile (Pydantic model) with datetime fields serializes correctly."""
    now = datetime.now(UTC)
    
    profile = UserProfile(
        user_id="test_user",
        created_at=now,
        updated_at=now,
        last_seen_at=now,
    )
    
    # This should NOT raise "Object of type datetime is not JSON serializable"
    serialized = _serialize_for_json(profile)
    
    # Verify structure
    assert isinstance(serialized, dict)
    assert serialized["user_id"] == "test_user"
    assert isinstance(serialized["created_at"], str)  # Should be ISO string, not datetime
    assert serialized["created_at"] == now.isoformat()
    assert serialized["updated_at"] == now.isoformat()
    assert serialized["last_seen_at"] == now.isoformat()


def test_serialize_fact_with_datetime():
    """Test that Fact (Pydantic model) with datetime fields serializes correctly."""
    now = datetime.now(UTC)
    fact_id = uuid4()
    
    fact = Fact(
        id=fact_id,
        user_id="test_user",
        content="Test fact",
        fact_type="preference",  # FactType is Literal, not enum
        category="general",  # FactCategory is Literal, not enum
        created_at=now,
        last_accessed_at=now,
    )
    
    # This should NOT raise "Object of type datetime is not JSON serializable"
    serialized = _serialize_for_json(fact)
    
    # Verify structure
    assert isinstance(serialized, dict)
    assert serialized["user_id"] == "test_user"
    assert isinstance(serialized["id"], str)  # UUID should be string
    assert serialized["id"] == str(fact_id)
    assert isinstance(serialized["created_at"], str)  # Should be ISO string
    assert serialized["created_at"] == now.isoformat()
    assert serialized["last_accessed_at"] == now.isoformat()


def test_serialize_conversation_state_with_memory_profile():
    """Test that ConversationState with memory_profile (UserProfile) serializes correctly."""
    from src.agents.langgraph.state import create_initial_state
    
    now = datetime.now(UTC)
    profile = UserProfile(
        user_id="test_user",
        created_at=now,
        updated_at=now,
    )
    
    state = create_initial_state("test_session")
    state["memory_profile"] = profile
    
    # This should NOT raise "Object of type datetime is not JSON serializable"
    serialized = _serialize_for_json(dict(state))
    
    # Verify memory_profile is serialized
    assert "memory_profile" in serialized
    assert isinstance(serialized["memory_profile"], dict)
    assert isinstance(serialized["memory_profile"]["created_at"], str)


def test_serialize_uuid_objects():
    """Test that UUID objects are converted to strings."""
    fact_id = uuid4()
    
    result = _serialize_for_json(fact_id)
    assert isinstance(result, str)
    assert result == str(fact_id)


def test_serialize_decimal_objects():
    """Test that Decimal objects are converted to float."""
    price = Decimal("2150.50")
    
    result = _serialize_for_json(price)
    assert isinstance(result, float)
    assert result == 2150.50


def test_serialize_tuple_and_set():
    """Test that tuple and set are converted to list."""
    test_tuple = (1, 2, 3)
    test_set = {4, 5, 6}
    
    tuple_result = _serialize_for_json(test_tuple)
    set_result = _serialize_for_json(test_set)
    
    assert isinstance(tuple_result, list)
    assert isinstance(set_result, list)
    assert tuple_result == [1, 2, 3]
    assert set(set_result) == {4, 5, 6}  # Set order may vary


def test_serialize_nested_structure():
    """Test serialization of nested structures with datetime."""
    now = datetime.now(UTC)
    fact_id = uuid4()
    
    nested = {
        "profile": UserProfile(
            user_id="test_user",
            created_at=now,
        ),
        "facts": [
            Fact(
                id=fact_id,
                user_id="test_user",
                content="Test",
                fact_type="preference",  # FactType is Literal, not enum
                category="general",  # FactCategory is Literal, not enum
                created_at=now,
            )
        ],
        "metadata": {
            "timestamp": now,
            "trace_id": fact_id,
        },
    }
    
    serialized = _serialize_for_json(nested)
    
    assert isinstance(serialized["profile"], dict)
    assert isinstance(serialized["profile"]["created_at"], str)
    assert isinstance(serialized["facts"], list)
    assert isinstance(serialized["facts"][0]["created_at"], str)
    assert isinstance(serialized["metadata"]["timestamp"], str)
    assert isinstance(serialized["metadata"]["trace_id"], str)


@pytest.mark.asyncio
async def test_postgres_store_save_with_datetime_in_state():
    """Integration test: verify PostgresSessionStore can save state with datetime."""
    from src.services.storage.postgres_store import PostgresSessionStore
    from src.agents.langgraph.state import create_initial_state
    from src.agents.pydantic.memory_models import UserProfile
    from datetime import UTC, datetime
    
    # Create state with memory_profile containing datetime
    now = datetime.now(UTC)
    profile = UserProfile(
        user_id="test_user_123",
        created_at=now,
        updated_at=now,
    )
    
    state = create_initial_state("test_session_datetime")
    state["memory_profile"] = profile
    
    # Try to save - should NOT raise "Object of type datetime is not JSON serializable"
    store = PostgresSessionStore()
    
    try:
        store.save("test_session_datetime", state)
        # If we get here without exception, serialization worked
        # (Note: actual DB save may fail if DB not available, but serialization should work)
    except TypeError as e:
        if "not JSON serializable" in str(e):
            pytest.fail(f"Serialization failed: {e}")
        raise  # Re-raise if it's a different TypeError

