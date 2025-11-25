from src.services.supabase_store import SupabaseSessionStore


class FakeResponse:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    def __init__(self, backing):
        self.backing = backing
        self._session_id = None
        self._payload = None

    def select(self, *_):
        return self

    def eq(self, field, value):
        assert field == "session_id"
        self._session_id = value
        return self

    def limit(self, *_):
        return self

    def upsert(self, payload):
        self._payload = payload
        self.backing[payload["session_id"]] = payload["state"]
        return self

    def execute(self):
        if self._payload:
            return FakeResponse([self._payload])
        if self._session_id in self.backing:
            return FakeResponse([{"state": self.backing[self._session_id]}])
        return FakeResponse([])


class FakeClient:
    def __init__(self):
        self.store = {}

    def table(self, *_):
        return FakeQuery(self.store)


def test_supabase_store_get_and_save_roundtrip():
    client = FakeClient()
    store = SupabaseSessionStore(client, table="agent_sessions")

    # Unknown session -> empty state
    empty = store.get("u1")
    assert empty["messages"] == []
    assert empty["current_state"] == "STATE0_INIT"

    # Persist and load
    empty["messages"].append({"role": "user", "content": "hello"})
    empty["current_state"] = "STATE1_DISCOVERY"
    store.save("u1", empty)

    restored = store.get("u1")
    assert restored["messages"][0]["content"] == "hello"
    assert restored["current_state"] == "STATE1_DISCOVERY"
