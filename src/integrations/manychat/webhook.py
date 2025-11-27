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

import logging
import re
from typing import Any, Dict, List, Optional

from src.agents.graph_v2 import get_active_graph
from src.core.models import AgentResponse
from src.services.client_data_parser import parse_client_data, ClientData
from src.services.conversation import ConversationHandler, create_conversation_handler
from src.services.message_store import MessageStore, create_message_store
from src.services.renderer import render_agent_response_text
from src.services.session_store import SessionStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ManyChat Custom Field Names (повинні співпадати з твоїм ManyChat)
# ---------------------------------------------------------------------------
FIELD_AI_STATE = "ai_state"           # Поточний стан AI (STATE_1_DISCOVERY, etc.)
FIELD_AI_INTENT = "ai_intent"         # Intent останнього повідомлення
FIELD_LAST_PRODUCT = "last_product"   # Назва останнього товару
FIELD_ORDER_SUM = "order_sum"         # Сума замовлення
FIELD_CLIENT_NAME = "client_name"     # ПІБ клієнта
FIELD_CLIENT_PHONE = "client_phone"   # Телефон клієнта
FIELD_CLIENT_CITY = "client_city"     # Місто клієнта
FIELD_CLIENT_NP = "client_nova_poshta"  # Відділення НП

# ---------------------------------------------------------------------------
# ManyChat Tags
# ---------------------------------------------------------------------------
TAG_AI_RESPONDED = "ai_responded"     # AI відповів
TAG_NEEDS_HUMAN = "needs_human"       # Потрібен живий менеджер
TAG_ORDER_STARTED = "order_started"   # Почав оформлення
TAG_ORDER_PAID = "order_paid"         # Оплатив


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
        # Use active graph based on USE_GRAPH_V2 feature flag
        self.runner = runner or get_active_graph()
        self.message_store = message_store or create_message_store()
        self._handler = create_conversation_handler(
            session_store=store,
            message_store=self.message_store,
            runner=self.runner,
        )

    async def handle(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process a ManyChat webhook body and produce a response envelope."""
        user_id, text = self._extract_user_and_text(payload)

        # Parse client data from message text (ПІБ, телефон, місто, НП)
        client_data = parse_client_data(text)

        # Use centralized handler with error handling
        result = await self._handler.process_message(user_id, text)

        if result.is_fallback:
            logger.warning(
                "Fallback response for ManyChat user %s: %s",
                user_id,
                result.error,
            )

        return self._to_manychat_response(result.response, client_data)

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

    def _to_manychat_response(
        self, 
        agent_response: AgentResponse, 
        client_data: Optional[ClientData] = None,
    ) -> Dict[str, Any]:
        """Map AgentResponse into ManyChat v2 compatible reply body.
        
        Returns a response with:
        - messages: Text and image content
        - set_field_values: Custom Fields to update
        - tags: Tags to add/remove
        - quick_replies: Quick reply buttons (optional)
        """
        # Build messages
        text_chunks = render_agent_response_text(agent_response)
        messages: List[Dict[str, Any]] = [{"type": "text", "text": chunk} for chunk in text_chunks]

        # Add product images
        for product in agent_response.products:
            if product.photo_url:
                messages.append({
                    "type": "image",
                    "url": product.photo_url,
                    "caption": f"{product.name} - {product.price} грн",
                })

        # Build Custom Field values (including parsed client data)
        field_values = self._build_field_values(agent_response, client_data)
        
        # Build tags
        tags_to_add, tags_to_remove = self._build_tags(agent_response)
        
        # Build quick replies based on state
        quick_replies = self._build_quick_replies(agent_response)

        response: Dict[str, Any] = {
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
            "escalation": agent_response.escalation.model_dump() if agent_response.escalation else None,
        }

        return response

    @staticmethod
    def _build_field_values(
        agent_response: AgentResponse,
        client_data: Optional[ClientData] = None,
    ) -> List[Dict[str, str]]:
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
                fields.append({"field_name": FIELD_ORDER_SUM, "field_value": str(last_product.price)})
        
        # Add parsed client data (ПІБ, телефон, місто, НП)
        if client_data:
            if client_data.full_name:
                fields.append({"field_name": FIELD_CLIENT_NAME, "field_value": client_data.full_name})
            if client_data.phone:
                fields.append({"field_name": FIELD_CLIENT_PHONE, "field_value": client_data.phone})
            if client_data.city:
                fields.append({"field_name": FIELD_CLIENT_CITY, "field_value": client_data.city})
            if client_data.nova_poshta:
                fields.append({"field_name": FIELD_CLIENT_NP, "field_value": client_data.nova_poshta})
        
        return fields

    @staticmethod
    def _build_tags(agent_response: AgentResponse) -> tuple[List[str], List[str]]:
        """Build tags to add/remove based on AgentResponse."""
        add_tags = [TAG_AI_RESPONDED]
        remove_tags: List[str] = []
        
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
            if agent_response.escalation and "ORDER_CONFIRMED" in (agent_response.escalation.reason or ""):
                add_tags.append(TAG_ORDER_PAID)
        
        return add_tags, remove_tags

    @staticmethod
    def _build_quick_replies(agent_response: AgentResponse) -> List[Dict[str, str]]:
        """Build Quick Reply buttons based on current state."""
        current_state = agent_response.metadata.current_state
        replies: List[Dict[str, str]] = []
        
        # State-specific quick replies
        if current_state in ("STATE_0_INIT", "STATE_1_DISCOVERY"):
            replies = [
                {"type": "text", "caption": "👗 Сукні"},
                {"type": "text", "caption": "👔 Костюми"},
                {"type": "text", "caption": "🧥 Тренчі"},
            ]
        elif current_state == "STATE_3_SIZE_COLOR":
            replies = [
                {"type": "text", "caption": "📏 Розмірна сітка"},
                {"type": "text", "caption": "🎨 Інші кольори"},
            ]
        elif current_state == "STATE_4_OFFER":
            replies = [
                {"type": "text", "caption": "✅ Беру!"},
                {"type": "text", "caption": "🎨 Інший колір"},
                {"type": "text", "caption": "📏 Інший розмір"},
            ]
        elif current_state == "STATE_5_PAYMENT_DELIVERY":
            replies = [
                {"type": "text", "caption": "💳 Повна оплата"},
                {"type": "text", "caption": "💵 Передплата 200 грн"},
            ]
        
        # Always add manager button for complex cases
        if agent_response.metadata.escalation_level != "NONE":
            replies = [{"type": "text", "caption": "👩 Зв'язок з менеджером"}]
        
        return replies
