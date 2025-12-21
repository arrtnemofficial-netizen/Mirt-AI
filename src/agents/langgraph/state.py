"""
Conversation state definition (compat re-export).
"""

from src.core.conversation_state import (
    ConversationState,
    add_messages_capped,
    append_list,
    create_initial_state,
    get_state_snapshot,
    merge_dict,
    replace_value,
    validate_state,
)

__all__ = [
    "ConversationState",
    "create_initial_state",
    "get_state_snapshot",
    "validate_state",
    "replace_value",
    "merge_dict",
    "append_list",
    "add_messages_capped",
]
