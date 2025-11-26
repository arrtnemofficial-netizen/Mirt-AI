"""ManyChat webhook integration for Instagram DM flows."""
from __future__ import annotations

import logging
from typing import Any, Dict

from src.agents.graph import app as graph_app
from src.core.models import AgentResponse
from src.services.conversation import ConversationHandler, create_conversation_handler
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text
from src.services.session_store import SessionStore

logger = logging.getLogger(__name__)


class ManychatPayloadError(Exception):
    """Raised when payload does not contain required fields."""


class ManychatWebhook:
    """Processes ManyChat webhook payloads and returns response envelopes."""

    def __init__(
        self,
        store: SessionStore,
        runner=graph_app,
        message_store: MessageStore | None = None,
    ) -> None:
        self.store = store
        self.runner = runner
        self.message_store = message_store or create_message_store()
        self._handler = create_conversation_handler(
            session_store=store,
            message_store=self.message_store,
            runner=runner,
        )

    async def handle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a ManyChat webhook body and produce a response envelope."""
        user_id, text = self._extract_user_and_text(payload)

        # Use centralized handler with error handling
        result = await self._handler.process_message(user_id, text)

        if result.is_fallback:
            logger.warning(
                "Fallback response for ManyChat user %s: %s",
                user_id,
                result.error,
            )

        return self._to_manychat_response(result.response)

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
