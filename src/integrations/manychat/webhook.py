"""ManyChat webhook integration for Instagram DM flows.

This module handles ManyChat External Request webhooks and returns responses
in ManyChat v2 format with support for:
- Text messages and images
- Custom Field values (set_field_values)
- Tags (add/remove)
- Quick Replies
- Actions for flow automation
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from src.agents import get_active_graph  # Fixed: was graph_v2
from src.conf.config import settings
from src.services.client_data_parser import ClientData, parse_client_data
from src.services.conversation import create_conversation_handler
from src.services.infra.debouncer import MessageDebouncer
from src.services.infra.media_utils import normalize_image_url
from src.services.infra.message_store import MessageStore, create_message_store
from src.core.prompt_registry import get_snippet_by_header, load_yaml_from_registry
from src.core.registry_keys import SystemKeys

from .constants import (  # noqa: F401
    FIELD_AI_INTENT,
    FIELD_AI_STATE,
    FIELD_LAST_PRODUCT,
    TAG_AI_RESPONDED,
    TAG_NEEDS_HUMAN,
)
from .pipeline import process_manychat_pipeline
from .response_builder import (
    build_manychat_quick_replies,
    build_manychat_v2_response,
)


if TYPE_CHECKING:
    from src.core.models import AgentResponse
    from src.services.infra.session_store import SessionStore


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_manychat_config() -> dict[str, Any]:
    data = load_yaml_from_registry(SystemKeys.MANYCHAT.value)
    return data if isinstance(data, dict) else {}


def _get_manychat_value(key: str, default: Any) -> Any:
    config = _get_manychat_config()
    value = config.get(key, default)
    return value if value is not None else default


# ---------------------------------------------------------------------------
# ManyChat Custom Field Names (must match your ManyChat config)
# ---------------------------------------------------------------------------
FIELD_AI_STATE = "ai_state"  # Current AI state (STATE_1_DISCOVERY, etc.)
FIELD_AI_INTENT = "ai_intent"  # Intent of the last message
FIELD_LAST_PRODUCT = "last_product"  # Last product name
FIELD_ORDER_SUM = "order_sum"  # Order total
FIELD_CLIENT_NAME = "client_name"  # Customer full name
FIELD_CLIENT_PHONE = "client_phone"  # Customer phone
FIELD_CLIENT_CITY = "client_city"  # Customer city
FIELD_CLIENT_NP = "client_nova_poshta"  # Nova Poshta branch

# ---------------------------------------------------------------------------
# ManyChat Tags
# ---------------------------------------------------------------------------
TAG_AI_RESPONDED = "ai_responded"  # AI responded
TAG_NEEDS_HUMAN = "needs_human"  # Human manager needed
TAG_ORDER_STARTED = "order_started"  # Order started
TAG_ORDER_PAID = "order_paid"  # Paid


class ManychatPayloadError(Exception):
    """Raised when payload does not contain required fields."""


class ManychatWebhook:
    """Processes ManyChat webhook payloads and returns response envelopes."""

    def __init__(
        self,
        store: SessionStore,
        runner=None,
        message_store: MessageStore | None = None,
    ) -> None:
        self.store = store
        self.runner = runner or get_active_graph()
        self.message_store = message_store or create_message_store()
        self.debouncer = MessageDebouncer(
            delay=float(getattr(settings, "MANYCHAT_DEBOUNCE_SECONDS", 0.0))
        )
        self._handler = create_conversation_handler(
            session_store=store,
            message_store=self.message_store,
            runner=self.runner,
        )

    async def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Process a ManyChat webhook body and produce a response envelope."""
        user_id, text = self._extract_user_and_text(payload)
        image_url = self._extract_image_url(payload)

        # Parse client data from message text (name, phone, city, NP)
        client_data = parse_client_data(text)

        pipeline_result = await process_manychat_pipeline(
            handler=self._handler,
            debouncer=self.debouncer,
            user_id=user_id,
            text=text,
            image_url=image_url,
            extra_metadata=None,
        )
        if pipeline_result is None:
            return {
                "version": "v2",
                "content": {"messages": [], "actions": [], "quick_replies": []},
            }

        result = pipeline_result.result

        if result.is_fallback:
            logger.warning(
                "Fallback response for ManyChat user %s: %s",
                user_id,
                result.error,
            )

        return self._to_manychat_response(result.response, client_data)

    @staticmethod
    def _extract_user_and_text(payload: dict[str, Any]) -> tuple[str, str]:
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
    def _extract_image_url(payload: dict[str, Any]) -> str | None:
        message = payload.get("message") or payload.get("data", {}).get("message") or {}
        if isinstance(message, dict):
            attachment = message.get("attachment") or {}
            url = (
                attachment.get("url")
                or attachment.get("image_url")
                or message.get("image_url")
            )
            return normalize_image_url(url) if url else None
        return None

    def _to_manychat_response(
        self,
        agent_response: AgentResponse,
        client_data: ClientData | None = None,
    ) -> dict[str, Any]:
        """Map AgentResponse into ManyChat v2 compatible reply body.

        Returns a response with:
        - messages: Text and image content
        - set_field_values: Custom Fields to update
        - tags: Tags to add/remove
        - quick_replies: Quick reply buttons (optional)
        """
        # Build messages
        text_chunks = render_agent_response_text(agent_response)
        messages: list[dict[str, Any]] = [{"type": "text", "text": chunk} for chunk in text_chunks]

        # Add product images
        for product in agent_response.products:
            if product.photo_url:
                messages.append(
                    {
                        "type": "image",
                        "url": product.photo_url,
                        "caption": f"{product.name} - {product.price} \u0433\u0440\u043d",
                    }
                )

        # Build Custom Field values (including parsed client data)
        field_values = self._build_field_values(agent_response, client_data)

        # Build tags
        tags_to_add, tags_to_remove = self._build_tags(agent_response)

        # Build quick replies based on state
        quick_replies = self._build_quick_replies(agent_response)

        response: dict[str, Any] = {
            "version": "v2",
            "content": {
                "messages": messages,
                "actions": [],
                "quick_replies": quick_replies,
            },
            "set_field_values": field_values,
            "add_tag": tags_to_add,
            "remove_tag": tags_to_remove,
        }

        # Add metadata for debugging
        response["_debug"] = {
            "event": agent_response.event,
            "current_state": agent_response.metadata.current_state,
            "intent": agent_response.metadata.intent,
            "escalation": agent_response.escalation.model_dump()
            if agent_response.escalation
            else None,
        }

        return response

    @staticmethod
    def _build_field_values(
        agent_response: AgentResponse,
        client_data: ClientData | None = None,
    ) -> list[dict[str, str]]:
        """Build Custom Field values from AgentResponse and parsed client data."""
        fields = [
            {"field_name": FIELD_AI_STATE, "field_value": agent_response.metadata.current_state},
            {"field_name": FIELD_AI_INTENT, "field_value": agent_response.metadata.intent},
        ]

        # Add last product info if available
        if agent_response.products:
            last_product = agent_response.products[-1]
            fields.append({"field_name": FIELD_LAST_PRODUCT, "field_value": last_product.name})
            if last_product.price:
                fields.append(
                    {"field_name": FIELD_ORDER_SUM, "field_value": str(last_product.price)}
                )

        # Add parsed client data (\u041f\u0406\u0411, \u0442\u0435\u043b\u0435\u0444\u043e\u043d, \u043c\u0456\u0441\u0442\u043e, \u041d\u041f)
        if client_data:
            if client_data.full_name:
                fields.append(
                    {"field_name": FIELD_CLIENT_NAME, "field_value": client_data.full_name}
                )
            if client_data.phone:
                fields.append({"field_name": FIELD_CLIENT_PHONE, "field_value": client_data.phone})
            if client_data.city:
                fields.append({"field_name": FIELD_CLIENT_CITY, "field_value": client_data.city})
            if client_data.nova_poshta:
                fields.append(
                    {"field_name": FIELD_CLIENT_NP, "field_value": client_data.nova_poshta}
                )

        return fields

    @staticmethod
    def _build_tags(agent_response: AgentResponse) -> tuple[list[str], list[str]]:
        """Build tags to add/remove based on AgentResponse."""
        add_tags = [TAG_AI_RESPONDED]
        remove_tags: list[str] = []

        # Add escalation tag if needed
        if agent_response.metadata.escalation_level != "NONE":
            add_tags.append(TAG_NEEDS_HUMAN)
        else:
            remove_tags.append(TAG_NEEDS_HUMAN)

        # Add order tags based on state
        current_state = agent_response.metadata.current_state
        if current_state in ("STATE_5_PAYMENT_DELIVERY", "STATE_6_UPSELL"):
            add_tags.append(TAG_ORDER_STARTED)

        if current_state == "STATE_7_END" and agent_response.event == "escalation":
            # Order completed with payment confirmation
            if agent_response.escalation and "ORDER_CONFIRMED" in (
                agent_response.escalation.reason or ""
            ):
                add_tags.append(TAG_ORDER_PAID)

        return add_tags, remove_tags

    @staticmethod
        @staticmethod
    def _build_quick_replies(agent_response: AgentResponse) -> list[dict[str, str]]:
        """Build Quick Reply buttons based on current state."""
        current_state = agent_response.metadata.current_state
        replies: list[dict[str, str]] = []
        config = _get_manychat_config()
        quick = config.get("quick_replies", {}) if isinstance(config, dict) else {}

        if current_state in ("STATE_0_INIT", "STATE_1_DISCOVERY"):
            captions = quick.get("state_0_1", [])
            replies = [{"type": "text", "caption": c} for c in captions]
        elif current_state == "STATE_3_SIZE_COLOR":
            captions = quick.get("state_3", [])
            replies = [{"type": "text", "caption": c} for c in captions]
        elif current_state == "STATE_4_OFFER":
            captions = quick.get("state_4", [])
            replies = [{"type": "text", "caption": c} for c in captions]
        elif current_state == "STATE_5_PAYMENT_DELIVERY":
            captions = quick.get("state_5", [])
            replies = [{"type": "text", "caption": c} for c in captions]

        if agent_response.metadata.escalation_level != "NONE":
            captions = quick.get("escalation", [])
            replies = [{"type": "text", "caption": c} for c in captions]

        return replies
