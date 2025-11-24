from src.services.session_store import InMemorySessionStore


def test_session_store_roundtrip():
    store = InMemorySessionStore()
    first = store.get("u1")
    assert first["messages"] == []

    first["messages"].append({"role": "user", "content": "hi"})
    store.save("u1", first)

    second = store.get("u1")
    assert second["messages"][0]["content"] == "hi"
    assert second is not first
