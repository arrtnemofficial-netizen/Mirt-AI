"""
Streaming Support - Real-time responses.
========================================
Don't make users stare at blank screens.
Stream tokens as they're generated.

This is UX 101 for AI products:
- User sees activity immediately
- Perceived latency drops dramatically
- Engagement increases

5 seconds of waiting = user leaves
5 seconds of streaming text = user stays
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from enum import Enum
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from langgraph.graph.graph import CompiledGraph

logger = logging.getLogger(__name__)


class StreamEventType(str, Enum):
    """Types of streaming events."""
    NODE_START = "node_start"
    NODE_END = "node_end"
    LLM_TOKEN = "llm_token"
    STATE_UPDATE = "state_update"
    ERROR = "error"
    INTERRUPT = "interrupt"


async def stream_events(
    graph: CompiledGraph,
    state: dict[str, Any],
    session_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """
    Stream all graph events for real-time UI updates.

    Yields events as they happen:
    - node_start: Node begins processing
    - node_end: Node completes with output
    - llm_token: Individual tokens from LLM
    - state_update: State changes
    - interrupt: Human-in-the-loop pause
    - error: Something went wrong

    Usage:
        async for event in stream_events(graph, state, session_id):
            if event["type"] == StreamEventType.LLM_TOKEN:
                await websocket.send(event["token"])
            elif event["type"] == StreamEventType.INTERRUPT:
                await show_approval_dialog(event["data"])

    Args:
        graph: Compiled LangGraph
        state: Initial state
        session_id: Session identifier

    Yields:
        Event dictionaries with type and data
    """
    config = {"configurable": {"thread_id": session_id}}

    try:
        async for event in graph.astream_events(state, config=config, version="v2"):
            event_type = event.get("event", "")

            # Node lifecycle events
            if event_type == "on_chain_start":
                yield {
                    "type": StreamEventType.NODE_START,
                    "node": event.get("name", "unknown"),
                    "session_id": session_id,
                    "timestamp": event.get("timestamp"),
                }

            elif event_type == "on_chain_end":
                output = event.get("data", {}).get("output")
                yield {
                    "type": StreamEventType.NODE_END,
                    "node": event.get("name", "unknown"),
                    "output": output,
                    "session_id": session_id,
                }

            # LLM token streaming
            elif event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk")
                if chunk:
                    content = getattr(chunk, "content", None)
                    if content:
                        yield {
                            "type": StreamEventType.LLM_TOKEN,
                            "token": content,
                            "session_id": session_id,
                        }

            # State updates
            elif event_type == "on_chain_stream":
                yield {
                    "type": StreamEventType.STATE_UPDATE,
                    "data": event.get("data"),
                    "session_id": session_id,
                }

    except Exception as e:
        logger.error("Streaming error for session %s: %s", session_id, e)
        yield {
            "type": StreamEventType.ERROR,
            "error": str(e),
            "session_id": session_id,
        }


async def stream_tokens(
    graph: CompiledGraph,
    state: dict[str, Any],
    session_id: str,
) -> AsyncIterator[str]:
    """
    Simplified token streaming - yields only LLM output tokens.

    Perfect for chat UIs that just want the typing effect.

    Usage:
        response = ""
        async for token in stream_tokens(graph, state, session_id):
            response += token
            await update_ui(response)

    Args:
        graph: Compiled LangGraph
        state: Initial state
        session_id: Session identifier

    Yields:
        Individual tokens as strings
    """
    config = {"configurable": {"thread_id": session_id}}

    async for event in graph.astream_events(state, config=config, version="v2"):
        if event.get("event") == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk:
                content = getattr(chunk, "content", None)
                if content:
                    yield content


async def stream_with_status(
    graph: CompiledGraph,
    state: dict[str, Any],
    session_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """
    Stream with human-readable status messages.

    Yields status updates that can be shown to users:
    - "Перевіряю безпеку повідомлення..."
    - "Аналізую фото..."
    - "Готую відповідь..."

    Usage:
        async for update in stream_with_status(graph, state, session_id):
            if update["type"] == "status":
                show_status(update["message"])
            elif update["type"] == "token":
                append_to_response(update["token"])
    """
    node_status_messages = {
        "moderation": "Перевіряю безпеку повідомлення...",
        "intent": "Аналізую запит...",
        "vision": "Аналізую фото...",
        "agent": "Готую відповідь...",
        "offer": "Формую пропозицію...",
        "payment": "Обробляю оплату...",
        "validation": "Перевіряю відповідь...",
    }

    config = {"configurable": {"thread_id": session_id}}

    async for event in graph.astream_events(state, config=config, version="v2"):
        event_type = event.get("event", "")

        if event_type == "on_chain_start":
            node_name = event.get("name", "")
            if node_name in node_status_messages:
                yield {
                    "type": "status",
                    "message": node_status_messages[node_name],
                    "node": node_name,
                }

        elif event_type == "on_chat_model_stream":
            chunk = event.get("data", {}).get("chunk")
            if chunk:
                content = getattr(chunk, "content", None)
                if content:
                    yield {
                        "type": "token",
                        "token": content,
                    }

        elif event_type == "on_chain_end":
            node_name = event.get("name", "")
            if node_name == "end":
                yield {
                    "type": "complete",
                    "message": "Готово!",
                }
