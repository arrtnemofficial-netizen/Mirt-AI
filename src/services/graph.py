"""LangGraph orchestrator that wraps the Pydantic AI agent."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from src.core.models import AgentResponse, DebugInfo, Escalation, Message, Metadata
from src.services.agent import run_agent
from src.services.metadata import apply_metadata_defaults
from src.services.moderation import ModerationResult, moderate_user_message


class AgentState(TypedDict):
    messages: List[Dict[str, Any]]
    current_state: str
    metadata: Dict[str, Any]


async def agent_node(state: AgentState, runner=run_agent) -> AgentState:
    """Single LangGraph node that calls the agent and updates state."""

    state.setdefault("metadata", {})
    state.setdefault("messages", [])
    state.setdefault("current_state", "STATE0_INIT")

    state["metadata"]["current_state"] = state.get("current_state", "STATE0_INIT")

    user_content = _latest_user_content(state["messages"]) or ""
    moderation_result = moderate_user_message(user_content) if user_content else ModerationResult(
        allowed=True, redacted_text=user_content, flags=[], reason=None
    )

    if moderation_result.redacted_text != user_content:
        _apply_redaction(state["messages"], moderation_result.redacted_text)

    state["metadata"]["moderation_flags"] = moderation_result.flags
    prepared_metadata = apply_metadata_defaults(state.get("metadata"), state.get("current_state", "STATE0_INIT"))

    if not moderation_result.allowed:
        response = _build_moderation_response(prepared_metadata, state["current_state"], moderation_result)
    else:
        response = await runner(state["messages"], prepared_metadata)

    state["current_state"] = response.metadata.current_state
    state["metadata"] = response.metadata.model_dump()
    state["messages"].append({"role": "assistant", "content": response.model_dump_json()})
    return state


def build_graph(runner=run_agent) -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("agent", lambda state: agent_node(state, runner))
    graph.set_entry_point("agent")
    graph.add_edge("agent", END)
    return graph.compile()


app = build_graph()


def _latest_user_content(messages: List[Dict[str, Any]]) -> Optional[str]:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content")
    return None


def _apply_redaction(messages: List[Dict[str, Any]], redacted_text: str) -> None:
    for idx in range(len(messages) - 1, -1, -1):
        if messages[idx].get("role") == "user":
            messages[idx]["content"] = redacted_text
            break


def _build_moderation_response(
    metadata: Dict[str, Any], current_state: str, result: ModerationResult
) -> AgentResponse:
    updated_metadata = metadata.copy()
    updated_metadata.update({
        "current_state": current_state,
        "event_trigger": "moderation_block",
        "moderation_flags": result.flags,
    })

    return AgentResponse(
        event="escalation",
        messages=[
            Message(
                content=(
                    "Вибачте, я передаю запит колезі для перевірки, щоб переконатися"
                    " у безпеці та конфіденційності."
                )
            )
        ],
        products=[],
        metadata=Metadata(**updated_metadata),
        escalation=Escalation(
            level="L1",
            reason=result.reason or "Модерація заблокувала повідомлення.",
            target="human_operator",
        ),
        debug=DebugInfo(state=current_state, intent="moderation_blocked"),
    )
