"""
Application bootstrap for agent dependencies.
Central place to construct services and inject them into AgentDeps.
"""

from __future__ import annotations

from typing import Any

from src.agents.pydantic.deps import AgentDeps
from src.services.data.catalog_service import CatalogService
from src.services.data.order_service import OrderService
from src.services.domain.memory.memory_service import MemoryService
from src.services.domain.vision.vision_context import VisionContextService


def _split_state_and_metadata(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("metadata"), dict):
        return raw, raw.get("metadata", {})
    return {}, raw if isinstance(raw, dict) else {}


def build_agent_deps(raw_state: dict[str, Any]) -> AgentDeps:
    state, metadata = _split_state_and_metadata(raw_state)

    catalog = CatalogService()
    db = OrderService()
    memory = MemoryService()
    vision = VisionContextService(catalog)

    return AgentDeps(
        session_id=state.get("session_id", metadata.get("session_id", "")),
        user_id=metadata.get("user_id", ""),
        current_state=state.get("current_state", "STATE_0_INIT"),
        channel=metadata.get("channel", "instagram"),
        language=metadata.get("language", "uk"),
        has_image=state.get("has_image", False),
        image_url=state.get("image_url"),
        selected_products=state.get("selected_products", []),
        customer_name=metadata.get("customer_name"),
        customer_phone=metadata.get("customer_phone"),
        customer_city=metadata.get("customer_city"),
        customer_nova_poshta=metadata.get("customer_nova_poshta"),
        memory_context_prompt=state.get("memory_context_prompt"),
        memory_profile=state.get("memory_profile"),
        memory_facts=state.get("memory_facts"),
        db=db,
        catalog=catalog,
        memory=memory,
        vision=vision,
    )
