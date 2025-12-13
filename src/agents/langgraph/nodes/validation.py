"""
Validation Node - Self-correction loops.
=========================================
THIS IS CRITICAL FOR PRODUCTION.

Without this:
- API fails -> customer sees error
- LLM hallucinates -> wrong products shown
- Tool returns garbage -> garbage sent to user

With this:
- API fails -> retry automatically
- Validation fails -> send back to agent with feedback
- Max retries hit -> escalate to human

This is the "quality gate" that makes robots fix their own mistakes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from src.core.product_adapter import ProductAdapter
from src.services.observability import log_trace, log_validation_result, track_metric


logger = logging.getLogger(__name__)


# Validation rules
MAX_PRODUCTS_PER_RESPONSE = 5
MIN_PRICE = 100  # grn
MAX_PRICE = 50000  # grn


async def validation_node(state: dict[str, Any]) -> dict[str, Any]:
    """
    Validate agent output before sending to user.

    Checks:
    1. Products have valid price (> 0, reasonable range)
    2. Products have valid photo_url (https://)
    3. Session ID is preserved
    4. No hallucinated products (if tool results available)
    5. Response is valid JSON

    Returns:
        State update with validation_errors list
        If errors found, retry_count is incremented
    """
    session_id = state.get("session_id", state.get("metadata", {}).get("session_id", ""))
    trace_id = state.get("trace_id", "")
    errors: list[str] = []

    # Get latest assistant response
    messages = state.get("messages", [])
    assistant_response = _get_latest_assistant_response(messages)

    if not assistant_response:
        # No response to validate - might be first step
        return {
            "validation_errors": [],
            "step_number": state.get("step_number", 0) + 1,
        }

    # 1. Validate products
    products = assistant_response.get("products", [])
    if products:
        product_errors = _validate_products(products)
        errors.extend(product_errors)

        # Check for hallucination
        tool_results = state.get("tool_plan_result", {}).get("tool_results", [])
        hallucination_errors = _check_for_hallucination(products, tool_results)
        errors.extend(hallucination_errors)

    # 2. Validate session ID preserved
    output_session = assistant_response.get("metadata", {}).get("session_id", "")
    if session_id and output_session and output_session != session_id:
        errors.append(f"Session ID mismatch: expected {session_id}, got {output_session}")

    # 3. Validate response structure
    structure_errors = _validate_response_structure(assistant_response)
    errors.extend(structure_errors)

    # Log validation result
    passed = len(errors) == 0
    log_validation_result(
        session_id=session_id,
        passed=passed,
        errors=errors,
    )

    # Update retry count if validation failed
    retry_count = state.get("retry_count", 0)

    # Trace Logging
    if not passed:
        retry_count += 1

        # Categorize error
        error_category = "BUSINESS"
        if any("structure" in e or "Missing" in e for e in errors):
            error_category = "SCHEMA"
        elif any("hallucination" in e for e in errors):
            error_category = "SAFETY"

        await log_trace(
            session_id=session_id,
            trace_id=trace_id,
            node_name="validation_node",
            status="ERROR",
            error_category=error_category,
            error_message="; ".join(errors),
            output_snapshot={"errors": errors},
        )

        logger.warning(
            "Validation failed for session %s (attempt %d): %s",
            session_id,
            retry_count,
            errors[:3],  # Log first 3 errors
        )
        track_metric("validation_failed", 1, {"session_id": session_id})
    else:
        await log_trace(
            session_id=session_id,
            trace_id=trace_id,
            node_name="validation_node",
            status="SUCCESS",
        )
        track_metric("validation_passed", 1, {"session_id": session_id})

    return {
        "validation_errors": errors,
        "retry_count": retry_count,
        "last_error": errors[0] if errors else None,
        "step_number": state.get("step_number", 0) + 1,
    }


def _get_latest_assistant_response(messages: list[Any]) -> dict[str, Any] | None:
    """Extract latest assistant response as dict.

    Handles both dict format and LangChain Message objects.
    """
    from .utils import extract_assistant_message

    content = extract_assistant_message(messages)
    if content:
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _validate_products(products: list[dict[str, Any]]) -> list[str]:
    """Validate product data."""
    errors = []

    if len(products) > MAX_PRODUCTS_PER_RESPONSE:
        errors.append(f"Too many products: {len(products)} > {MAX_PRODUCTS_PER_RESPONSE}")

    # Use ProductAdapter for detailed validation
    _valid, product_errors = ProductAdapter.batch_validate(products)
    for err in product_errors:
        errors.append(f"{err.field}: {err.message}")

    # Additional price validation
    for i, p in enumerate(products):
        price = p.get("price", 0)
        if price and (price < MIN_PRICE or price > MAX_PRICE):
            errors.append(
                f"Product {i}: price {price} outside valid range ({MIN_PRICE}-{MAX_PRICE})"
            )

        # Check photo URL
        photo_url = p.get("photo_url") or p.get("image_url")
        if photo_url and not photo_url.startswith("https://"):
            errors.append(f"Product {i}: invalid photo_url (must be https)")

    return errors


def _check_for_hallucination(
    products: list[dict[str, Any]],
    tool_results: list[dict[str, Any]],
) -> list[str]:
    """Check if products match tool results (no hallucination)."""
    errors = []

    if not tool_results:
        # No tool results to compare against
        return errors

    # Build set of valid product IDs from tools
    valid_ids = set()
    for tr in tool_results:
        for item in tr.get("result") or []:
            pid = item.get("id") or item.get("product_id")
            if pid:
                valid_ids.add(int(pid))

    # Check each product
    for p in products:
        pid = p.get("id") or p.get("product_id")
        if pid and valid_ids and int(pid) not in valid_ids:
            errors.append(f"Product {pid} not in tool results (possible hallucination)")

    return errors


# Russian-specific characters (not shared with Ukrainian)
# ы, э, ъ are ONLY in Russian, not Ukrainian
RUSSIAN_ONLY_CHARS = set("ыэъЫЭЪёЁ")

# Russian words that should NEVER appear in Ukrainian response
RUSSIAN_MARKERS = [
    r"\bщас\b",      # сейчас (рос) vs зараз (укр)
    r"\bсейчас\b",   # сейчас (рос)
    r"\bтолько\b",   # только (рос) vs тільки (укр)
    r"\bхорошо\b",   # хорошо (рос) vs добре (укр)
    r"\bконечно\b",  # конечно (рос) vs звичайно (укр)
    r"\bпожалуйста\b",  # пожалуйста (рос) vs будь ласка (укр)
    r"\bспасибо\b",  # спасибо (рос) vs дякую (укр)
    r"\bждите\b",    # ждите (рос) vs чекайте (укр)
    r"\bподождите\b",  # подождите (рос) vs зачекайте (укр)
    r"\bздравствуйте\b",  # здравствуйте (рос) vs вітаю (укр)
    r"\bпривет\b",   # привет (рос) vs привіт (укр)
]


def _validate_language_ukrainian(response: dict[str, Any]) -> list[str]:
    """Validate that response is in Ukrainian, not Russian.
    
    This is CRITICAL for brand consistency and legal compliance.
    """
    import re
    
    errors = []
    messages = response.get("messages", [])
    
    for i, msg in enumerate(messages):
        text = msg.get("text", "") if isinstance(msg, dict) else str(msg)
        
        # Check for Russian-only characters
        russian_chars_found = [c for c in text if c in RUSSIAN_ONLY_CHARS]
        if russian_chars_found:
            errors.append(
                f"Message {i}: contains Russian characters {set(russian_chars_found)} - must be Ukrainian only"
            )
        
        # Check for Russian marker words
        text_lower = text.lower()
        for pattern in RUSSIAN_MARKERS:
            if re.search(pattern, text_lower):
                errors.append(
                    f"Message {i}: contains Russian word '{pattern.strip(chr(92)+'b')}' - use Ukrainian equivalent"
                )
    
    return errors


def _validate_response_structure(response: dict[str, Any]) -> list[str]:
    """Validate response has required structure."""
    errors = []

    # Must have event
    if "event" not in response:
        errors.append("Missing 'event' field in response")

    # Must have messages array
    if "messages" not in response:
        errors.append("Missing 'messages' field in response")
    elif not isinstance(response["messages"], list):
        errors.append("'messages' must be an array")
    elif len(response["messages"]) == 0:
        errors.append("'messages' array is empty")
    else:
        # VALIDATE LANGUAGE - must be Ukrainian!
        lang_errors = _validate_language_ukrainian(response)
        errors.extend(lang_errors)

    # Must have metadata
    if "metadata" not in response:
        errors.append("Missing 'metadata' field in response")

    return errors


def should_retry(state: dict[str, Any]) -> bool:
    """Check if we should retry after validation failure."""
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    # No errors = no retry needed
    if not errors:
        return False

    # Max retries hit = escalate instead
    return not retry_count >= max_retries


def get_retry_feedback(state: dict[str, Any]) -> str:
    """Build feedback message for retry attempt."""
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)

    feedback = f"Попередня відповідь мала помилки (спроба {retry_count}):\n"
    for err in errors[:3]:  # First 3 errors
        feedback += f"- {err}\n"
    feedback += "\nВиправ ці помилки та спробуй ще раз."

    return feedback
