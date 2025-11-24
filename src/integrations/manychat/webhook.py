"""ManyChat webhook integration for Instagram DM flows."""
from __future__ import annotations

from typing import Any, Dict


from src.core.models import AgentResponse
from src.services.graph import app as graph_app
from src.services.renderer import render_agent_response_text
from src.services.session_store import InMemorySessionStore


class ManychatPayloadError(Exception):
    """Raised when payload does not contain required fields."""


class ManychatWebhook:
    """Processes ManyChat webhook payloads and returns response envelopes."""

    def __init__(self, store: InMemorySessionStore, runner=graph_app) -> None:
        self.store = store
        self.runner = runner

    async def handle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a ManyChat webhook body and produce a response envelope."""

        user_id, text = self._extract_user_and_text(payload)
        state = self.store.get(user_id)
        state["messages"].append({"role": "user", "content": text})
        state["metadata"].setdefault("session_id", user_id)

        result_state = await self.runner.ainvoke(state)
        self.store.save(user_id, result_state)

        agent_json = result_state["messages"][-1]["content"]
        agent_response = AgentResponse.model_validate_json(agent_json)
        return self._to_manychat_response(agent_response)

    @staticmethod
    def _extract_user_and_text(payload: Dict[str, Any]) -> tuple[str, str]:
        subscriber = payload.get("subscriber") or payload.get("user")
        message = payload.get("message") or payload.get("data", {}).get("message")
        text = None
        if isinstance(message, dict):
            text = message.get("text") or message.get("content")
        if not subscriber or not text:
            raise ManychatPayloadError("Missing subscriber or message text in payload")
        user_id = str(subscriber.get("id") or subscriber.get("user_id") or "unknown")
        return user_id, text

    @staticmethod
    def _to_manychat_response(agent_response: AgentResponse) -> Dict[str, Any]:
        """Map AgentResponse into ManyChat-compatible reply body."""

        text_chunks = render_agent_response_text(agent_response)
        messages = [{"type": "text", "text": chunk} for chunk in text_chunks]

        for product in agent_response.products:
            messages.append(
                {
                    "type": "image",
                    "url": product.photo_url,
                    "caption": product.name,
                }
            )

        return {
            "version": "v2",
            "messages": messages,
            "metadata": {
                "event": agent_response.event,
                "current_state": agent_response.metadata.current_state,
                "escalation": agent_response.escalation.model_dump() if agent_response.escalation else None,
            },
        }
