import pytest

from src.agents.langgraph.state import create_initial_state, map_canonical_image_fields
from src.core.state_schema import StateSchema
from src.services.session.manager import SessionManager
from src.services.storage import InMemorySessionStore


@pytest.mark.asyncio
async def test_session_manager_maps_text_and_photo_to_canonical_fields() -> None:
    store = InMemorySessionStore()
    manager = SessionManager(store)

    state = await manager.load_session(
        session_id="u-text-photo",
        extra_metadata={"channel": "manychat", "has_image": True, "image_url": " https://cdn/img.jpg "},
    )

    assert state["has_image"] is True
    assert state["image_url"] == "https://cdn/img.jpg"
    assert "has_image" not in state["metadata"]
    assert "image_url" not in state["metadata"]


@pytest.mark.asyncio
async def test_session_manager_maps_photo_only_message() -> None:
    store = InMemorySessionStore()
    manager = SessionManager(store)

    state = await manager.load_session(
        session_id="u-photo-only",
        extra_metadata={"has_image": False, "image_url": "https://cdn/only-photo.jpg"},
    )

    assert state["has_image"] is True
    assert state["image_url"] == "https://cdn/only-photo.jpg"


@pytest.mark.asyncio
async def test_restart_state_keeps_canonical_defaults_without_metadata_shadowing() -> None:
    restart_state = create_initial_state(
        session_id="restart-user",
        metadata={"channel": "manychat", "vision_greeted": False},
    )

    assert restart_state["has_image"] is False
    assert restart_state["image_url"] is None
    assert "has_image" not in restart_state["metadata"]
    assert "image_url" not in restart_state["metadata"]


def test_state_schema_rejects_metadata_conflict_with_canonical_fields() -> None:
    with pytest.raises(ValueError, match="metadata.has_image conflicts"):
        StateSchema(
            session_id="conflict",
            messages=[],
            metadata={"session_id": "conflict", "has_image": False},
            has_image=True,
        )


def test_map_canonical_image_fields_removes_metadata_aliases() -> None:
    metadata, has_image, image_url = map_canonical_image_fields(
        metadata={"session_id": "s1", "has_image": True, "image_url": "https://img"}
    )

    assert metadata == {"session_id": "s1"}
    assert has_image is True
    assert image_url == "https://img"
