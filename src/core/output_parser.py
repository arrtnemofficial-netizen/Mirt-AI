"""Robust JSON output parser with multiple fallback strategies.

Ensures 100% valid AgentResponse even when LLM returns malformed output.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.core.models import AgentResponse, Message, Metadata


logger = logging.getLogger(__name__)


class OutputParser:
    """Multi-strategy parser for LLM output with guaranteed AgentResponse."""

    def __init__(self, session_id: str = "", current_state: str = "STATE_0_INIT"):
        self.session_id = session_id
        self.current_state = current_state

    def parse(self, raw_output: Any) -> AgentResponse:
        """
        Parse LLM output to AgentResponse with multiple fallback strategies.

        Strategy order:
        1. Already AgentResponse object
        2. Valid JSON string
        3. JSON with markdown code blocks
        4. Partial JSON extraction
        5. Plain text fallback
        """
        # Strategy 1: Already parsed
        if isinstance(raw_output, AgentResponse):
            return raw_output

        # Strategy 2-4: String parsing
        if isinstance(raw_output, str):
            return self._parse_string(raw_output)

        # Strategy 5: Dict
        if isinstance(raw_output, dict):
            return self._parse_dict(raw_output)

        # Final fallback
        return self._text_fallback(str(raw_output))

    def _parse_string(self, text: str) -> AgentResponse:
        """Parse string with multiple strategies."""
        text = text.strip()

        # Strategy 2: Direct JSON
        try:
            data = json.loads(text)
            return self._parse_dict(data)
        except json.JSONDecodeError:
            pass

        # Strategy 3: Extract from markdown code blocks
        json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                return self._parse_dict(data)
            except json.JSONDecodeError:
                pass

        # Strategy 4: Find JSON object anywhere in text
        json_match = re.search(r'\{[^{}]*"event"[^{}]*\}', text, re.DOTALL)
        if json_match:
            try:
                # Try to find complete JSON object
                start = text.find("{")
                if start != -1:
                    # Find matching closing brace
                    depth = 0
                    for i, char in enumerate(text[start:], start):
                        if char == "{":
                            depth += 1
                        elif char == "}":
                            depth -= 1
                            if depth == 0:
                                try:
                                    data = json.loads(text[start : i + 1])
                                    return self._parse_dict(data)
                                except json.JSONDecodeError:
                                    break
            except Exception:
                pass

        # Strategy 5: Plain text fallback
        return self._text_fallback(text)

    def _parse_dict(self, data: dict) -> AgentResponse:
        """Parse dict to AgentResponse with validation."""
        try:
            # Validate and fill defaults
            validated = self._validate_and_fill(data)
            return AgentResponse.model_validate(validated)
        except Exception as e:
            logger.warning("Dict validation failed: %s", e)
            # Extract what we can
            text = self._extract_text_from_dict(data)
            return self._text_fallback(text)

    def _validate_and_fill(self, data: dict) -> dict:
        """Validate dict and fill missing fields with defaults."""
        # Ensure event
        if "event" not in data or data["event"] not in [
            "simple_answer",
            "product_showcase",
            "escalation",
            "clarification",
            "greeting",
            "farewell",
        ]:
            data["event"] = "simple_answer"

        # Ensure messages
        if "messages" not in data or not isinstance(data["messages"], list):
            data["messages"] = []

        # Validate each message
        valid_messages = []
        for msg in data["messages"]:
            if isinstance(msg, dict) and "content" in msg:
                valid_messages.append(
                    {"type": msg.get("type", "text"), "content": str(msg["content"])}
                )
            elif isinstance(msg, str):
                valid_messages.append({"type": "text", "content": msg})

        if not valid_messages:
            # Try to extract content from other fields
            if "text" in data:
                valid_messages.append({"type": "text", "content": str(data["text"])})
            elif "content" in data:
                valid_messages.append({"type": "text", "content": str(data["content"])})
            elif "response" in data:
                valid_messages.append({"type": "text", "content": str(data["response"])})

        data["messages"] = valid_messages

        # Ensure products
        if "products" not in data or not isinstance(data["products"], list):
            data["products"] = []

        # Validate products - must have id, name, price, photo_url
        valid_products = []
        for i, prod in enumerate(data["products"]):
            if isinstance(prod, dict) and "name" in prod:
                # Generate id if missing
                prod_id = prod.get("id") or prod.get("product_id") or (i + 1)
                try:
                    prod_id = int(prod_id)
                except (ValueError, TypeError):
                    prod_id = i + 1

                # Get price with fallback
                price = prod.get("price", 0)
                try:
                    price = float(price) if price else 1.0
                except (ValueError, TypeError):
                    price = 1.0

                # Get photo_url with fallback
                photo_url = (
                    prod.get("photo_url")
                    or prod.get("image_url")
                    or prod.get("url")
                    or "https://placeholder.com/image.jpg"
                )
                if not photo_url.startswith("https://"):
                    photo_url = "https://placeholder.com/image.jpg"

                valid_products.append(
                    {
                        "id": prod_id,
                        "name": str(prod["name"]),
                        "price": price,
                        "photo_url": photo_url,
                        "size": prod.get("size", ""),
                        "color": prod.get("color", ""),
                        "sku": prod.get("sku"),
                        "category": prod.get("category"),
                    }
                )
        data["products"] = valid_products

        # Ensure metadata
        if "metadata" not in data or not isinstance(data["metadata"], dict):
            data["metadata"] = {}

        meta = data["metadata"]
        meta["session_id"] = meta.get("session_id", self.session_id)
        meta["current_state"] = meta.get("current_state", self.current_state)
        meta["intent"] = meta.get("intent", "UNKNOWN_OR_EMPTY")
        meta["escalation_level"] = meta.get("escalation_level", "NONE")
        data["metadata"] = meta

        return data

    def _extract_text_from_dict(self, data: dict) -> str:
        """Extract readable text from malformed dict."""
        for key in ["content", "text", "message", "response", "answer"]:
            value = data.get(key)
            if value:
                return str(value)

        if "messages" in data and isinstance(data["messages"], list):
            texts = []
            for msg in data["messages"]:
                if isinstance(msg, dict) and "content" in msg:
                    texts.append(str(msg["content"]))
                elif isinstance(msg, str):
                    texts.append(msg)
            if texts:
                return "\n".join(texts)

        return str(data)

    def _text_fallback(self, text: str) -> AgentResponse:
        """Create AgentResponse from plain text."""
        # Clean up text
        text = text.strip()

        # Remove any JSON artifacts
        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        text = re.sub(r"^\s*\{.*?\}\s*$", "", text, flags=re.DOTALL)

        if not text or text == "{}":
            text = "Вибачте, сталася помилка. Спробуйте ще раз або напишіть менеджеру 🤍"

        logger.info("Using text fallback for output parsing")

        return AgentResponse(
            event="simple_answer",
            messages=[Message(type="text", content=text)],
            products=[],
            metadata=Metadata(
                session_id=self.session_id,
                current_state=self.current_state,
                intent="UNKNOWN_OR_EMPTY",
                escalation_level="NONE",
            ),
        )


def parse_llm_output(
    raw_output: Any,
    session_id: str = "",
    current_state: str = "STATE_0_INIT",
) -> AgentResponse:
    """Convenience function for parsing LLM output."""
    parser = OutputParser(session_id, current_state)
    return parser.parse(raw_output)
