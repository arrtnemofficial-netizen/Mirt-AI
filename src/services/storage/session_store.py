"""Session store primitives for chat platforms."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from langchain_core.messages import BaseMessage

from src.core.constants import AgentState as StateEnum

logger = logging.getLogger(__name__)


if TYPE_CHECKING:
    from src.core.models import BaseConversationState as ConversationState


def _serialize_for_json(value: Any) -> Any:
    """
    Recursively serialize values for JSON compatibility.
    
    Handles:
    - LangChain Message objects → dict
    - datetime/date/time → ISO format strings
    - UUID → string
    - Decimal → float (with precision loss warning in logs)
    - timedelta → total_seconds (float)
    - Pydantic models → dict via model_dump()
    - dict/list/tuple/set → recursive serialization
    
    This is critical for PostgreSQL JSON storage where datetime objects
    from Pydantic models (UserProfile, Fact) must be converted to strings.
    
    Order matters: datetime handling must come BEFORE Pydantic model handling,
    because model_dump() returns dicts with datetime objects that need recursive processing.
    """
    # Handle LangChain Message objects
    if isinstance(value, BaseMessage):
        return {
            "type": value.type,
            "content": value.content,
            "additional_kwargs": getattr(value, "additional_kwargs", {}),
        }
    
    # Handle datetime objects (datetime, date, time)
    # CRITICAL: Pydantic models (UserProfile, Fact) contain datetime fields
    # that must be converted to ISO format strings for JSON serialization
    # This MUST come before Pydantic model handling
    elif isinstance(value, datetime):
        return value.isoformat()
    elif isinstance(value, date):
        return value.isoformat()
    elif isinstance(value, time):
        return value.isoformat()
    elif isinstance(value, timedelta):
        # Convert timedelta to total seconds (float)
        return value.total_seconds()
    
    # Handle UUID objects (may appear in Fact.id, trace_id, etc.)
    elif isinstance(value, UUID):
        return str(value)
    
    # Handle Decimal (may appear in prices, amounts)
    elif isinstance(value, Decimal):
        # WARNING: Decimal to float may lose precision, but JSON doesn't support Decimal
        # For production, consider storing as string if precision is critical
        return float(value)
    
    # Handle Pydantic BaseModel objects (e.g., UserProfile, Fact)
    # These are the MAIN source of datetime objects in ConversationState
    elif hasattr(value, "model_dump"):
        # Pydantic V2: model_dump() returns dict, but datetime fields remain as datetime
        # So we need to recursively serialize the result
        return _serialize_for_json(value.model_dump())
    elif hasattr(value, "dict"):
        # Pydantic V1 fallback
        return _serialize_for_json(value.dict())
    
    # Handle collections (recursive serialization)
    elif isinstance(value, dict):
        return {k: _serialize_for_json(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_serialize_for_json(item) for item in value]
    elif isinstance(value, tuple):
        # Convert tuple to list for JSON compatibility
        return [_serialize_for_json(item) for item in value]
    elif isinstance(value, set):
        # Convert set to list for JSON compatibility
        return [_serialize_for_json(item) for item in value]
    
    # Handle None, primitives (str, int, float, bool) - pass through
    elif value is None or isinstance(value, (str, int, float, bool)):
        return value
    
    # Fallback for unknown types: try to convert to string
    # This is a safety net, but should be logged if hit
    else:
        # Log warning for debugging, but don't fail
        logger.warning(
            "_serialize_for_json: unknown type %s, converting to string. "
            "This may indicate a missing type handler.",
            type(value).__name__
        )
        try:
            return str(value)
        except Exception:
            return None


class SessionStore(Protocol):
    """Contract for session storage implementations."""

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""

    def delete(self, session_id: str) -> bool:
        """Delete session state. Returns True if session existed."""


class InMemorySessionStore:
    """Lightweight, process-local session storage.

    Suitable for demos and single-process deployments. Replace with Redis/DB for scale.
    """

    def __init__(self) -> None:
        self._store: dict[str, ConversationState] = {}

    def get(self, session_id: str) -> ConversationState:
        """Return stored state or a fresh empty state."""

        existing = self._store.get(session_id)
        if existing:
            return deepcopy(existing)
        from src.core.models import BaseConversationState as ConversationState

        return ConversationState(messages=[], metadata={}, current_state=StateEnum.default())

    def save(self, session_id: str, state: ConversationState) -> None:
        """Persist the current state for the session."""

        # Serialize state to handle LangChain Message objects and Pydantic models
        serialized_state = _serialize_for_json(dict(state))
        self._store[session_id] = deepcopy(serialized_state)

    def delete(self, session_id: str) -> bool:
        """Delete session state. Returns True if session existed."""
        if session_id in self._store:
            del self._store[session_id]
            return True
        return False


def state_from_text(text: str, session_id: str) -> ConversationState:
    """Helper to bootstrap state from a single user message."""

    from src.core.models import BaseConversationState as ConversationState

    return ConversationState(
        messages=[{"role": "user", "content": text}],
        metadata={"session_id": session_id},
        current_state=StateEnum.default(),
    )
