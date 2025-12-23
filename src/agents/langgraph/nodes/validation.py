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
from src.services.core.observability import log_trace, log_validation_result, track_metric


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
    errors: list[str] = []

    # Get latest structured assistant response
    # Prefer the typed/structured payload stored in state by agent nodes.
    assistant_response = _get_latest_assistant_response(state)

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

        # Catalog-aware validation (prevents hallucinations even without tool_results)
        catalog_errors = await _validate_products_against_catalog(products)
        errors.extend(catalog_errors)

        # Check for hallucination vs tool results (when available)
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
    if not passed:
        retry_count += 1
        logger.warning(
            "Validation failed for session %s (attempt %d): %s",
            session_id,
            retry_count,
            errors[:3],  # Log first 3 errors
        )
        track_metric("validation_failed", 1, {"session_id": session_id})
    else:
        track_metric("validation_passed", 1, {"session_id": session_id})

    return {
        "validation_errors": errors,
        "retry_count": retry_count,
        "last_error": errors[0] if errors else None,
        "step_number": state.get("step_number", 0) + 1,
    }


def _get_latest_assistant_response(state: dict[str, Any]) -> dict[str, Any] | None:
    """Extract latest assistant response as dict.

    Priority:
    1) `state["agent_response"]` (structured/typed output from PydanticAI agents)
    2) Parse the latest assistant message content as JSON (best-effort)
    """
    agent_payload = state.get("agent_response")
    if isinstance(agent_payload, dict) and agent_payload:
        return agent_payload

    from .utils import extract_assistant_message

    content = extract_assistant_message(state.get("messages", []))
    if content:
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _norm_text(v: Any) -> str:
    return " ".join(str(v or "").strip().split()).lower()


def _norm_list(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, list):
        return [_norm_text(x) for x in v if str(x or "").strip()]
    return [_norm_text(v)]


def _expected_price(catalog_product: dict[str, Any], size: str | None) -> float | None:
    """Resolve expected price for a product/size from catalog payload."""
    # Some environments store per-size pricing in `price_by_size` (json) even if schema.sql
    # only has `price`. Support both.
    price_by_size = catalog_product.get("price_by_size")
    if isinstance(price_by_size, dict) and size:
        try:
            if size in price_by_size:
                return float(price_by_size[size])
        except Exception:
            pass
    try:
        return float(catalog_product.get("price", 0) or 0)
    except Exception:
        return None


async def _validate_products_against_catalog(products: list[dict[str, Any]]) -> list[str]:
    """Validate that products exist in catalog and key fields match SSOT."""
    errors: list[str] = []

    ids: list[int] = []
    for p in products:
        pid = p.get("id") or p.get("product_id")
        try:
            if pid is None:
                continue
            ids.append(int(pid))
        except Exception:
            errors.append(f"Invalid product id: {pid!r}")

    ids = [i for i in ids if i > 0]
    if not ids:
        return errors

    # Lazy import to avoid heavier deps on module import.
    try:
        from src.services.data.catalog_service import CatalogService

        catalog = CatalogService()
        catalog_items = await catalog.get_products_by_ids(ids)
    except Exception as e:
        # If catalog is unavailable, treat as a validation failure (better to retry/escalate
        # than to send potentially hallucinated products).
        return [f"Catalog validation unavailable: {type(e).__name__}"]

    by_id: dict[int, dict[str, Any]] = {}
    for item in catalog_items or []:
        try:
            item_id = int(item.get("id"))
            by_id[item_id] = item
        except Exception:
            continue

    for p in products:
        pid_raw = p.get("id") or p.get("product_id")
        try:
            pid = int(pid_raw)
        except Exception:
            continue

        catalog_p = by_id.get(pid)
        if not catalog_p:
            errors.append(f"Product {pid} not found in catalog")
            continue

        # Name must match catalog (case/whitespace-insensitive).
        out_name = _norm_text(p.get("name"))
        cat_name = _norm_text(catalog_p.get("name"))
        if out_name and cat_name and out_name != cat_name:
            errors.append(f"Product {pid}: name mismatch (catalog='{catalog_p.get('name')}', got='{p.get('name')}')")

        # Size must be available in catalog sizes (if provided in output).
        out_size = str(p.get("size") or "").strip()
        if out_size:
            sizes = _norm_list(catalog_p.get("sizes"))
            if sizes and _norm_text(out_size) not in sizes:
                errors.append(f"Product {pid}: size '{out_size}' not available")

        # Color must be available in catalog colors (if provided in output).
        out_color = str(p.get("color") or "").strip()
        if out_color:
            colors = _norm_list(catalog_p.get("colors"))
            if colors and _norm_text(out_color) not in colors:
                errors.append(f"Product {pid}: color '{out_color}' not available")

        # Price must match catalog SSOT (supports price_by_size when present).
        expected = _expected_price(catalog_p, out_size or None)
        try:
            out_price = float(p.get("price", 0) or 0)
        except Exception:
            out_price = 0.0
        if expected is not None and expected > 0:
            # Use a tiny tolerance for numeric(10,2) -> float conversions.
            if abs(out_price - expected) > 0.01:
                errors.append(f"Product {pid}: price mismatch (expected={expected}, got={out_price})")

        # Photo URL should be from catalog when available.
        cat_photo = str(catalog_p.get("photo_url") or "").strip()
        out_photo = str(p.get("photo_url") or p.get("image_url") or "").strip()
        if cat_photo and out_photo and out_photo != cat_photo:
            errors.append(f"Product {pid}: photo_url mismatch")

    return errors


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
            errors.append(f"Product {i}: price {price} outside valid range ({MIN_PRICE}-{MAX_PRICE})")

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
    from src.agents.langgraph.nodes.vision.snippets import get_snippet_by_header
    
    errors = state.get("validation_errors", [])
    retry_count = state.get("retry_count", 0)

    snippets = get_snippet_by_header("VALIDATION_RETRY_FEEDBACK")
    if snippets and len(snippets) >= 2:
        prefix = snippets[0].format(retry_count=retry_count)
        suffix = snippets[1]
    else:
        prefix = f"Previous response had errors (attempt {retry_count}):"
        suffix = "Please fix these and try again."

    feedback = f"{prefix}\n"
    for err in errors[:3]:  # First 3 errors
        feedback += f"- {err}\n"
    feedback += f"\n{suffix}"

    return feedback
