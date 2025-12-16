from __future__ import annotations

import time
from threading import Lock


class InMemoryDedupeCache:
    def __init__(self, *, max_keys: int = 10000) -> None:
        self._items: dict[str, float] = {}
        self._lock = Lock()
        self._max_keys = max_keys

    def check_and_mark(self, key: str, *, ttl_seconds: int) -> bool:
        now = time.monotonic()
        expiry = now + ttl_seconds

        with self._lock:
            existing_expiry = self._items.get(key)
            if existing_expiry is not None and existing_expiry >= now:
                return True

            self._items[key] = expiry
            self._prune(now)
            return False

    def _prune(self, now: float) -> None:
        if not self._items:
            return

        expired = [k for k, exp in self._items.items() if exp < now]
        for k in expired:
            self._items.pop(k, None)

        if len(self._items) <= self._max_keys:
            return

        overflow = len(self._items) - self._max_keys
        for k in list(self._items.keys())[:overflow]:
            self._items.pop(k, None)
