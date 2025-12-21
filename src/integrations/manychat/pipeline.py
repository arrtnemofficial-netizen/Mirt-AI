from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.services.infra.debouncer import BufferedMessage, MessageDebouncer


if TYPE_CHECKING:
    from collections.abc import Callable

    from src.services.conversation import ConversationHandler, ConversationResult


@dataclass(frozen=True)
class PipelineResult:
    result: ConversationResult
    aggregated_msg: BufferedMessage
    has_image: bool
    final_text: str
    final_metadata: dict[str, Any] | None


async def process_manychat_pipeline(
    *,
    handler: ConversationHandler,
    debouncer: MessageDebouncer,
    user_id: str,
    text: str,
    image_url: str | None,
    extra_metadata: dict[str, Any] | None,
    time_budget: float | None = None,
    time_budget_provider: Callable[[bool], float] | None = None,
    on_superseded: Callable[[], None] | None = None,
    on_debounced: Callable[[BufferedMessage, bool, str, dict[str, Any] | None], None] | None = None,
) -> PipelineResult | None:
    buffered_msg = BufferedMessage(
        text=text,
        has_image=bool(image_url),
        image_url=image_url,
        extra_metadata=extra_metadata or {},
    )

    aggregated_msg = await debouncer.wait_for_debounce(user_id, buffered_msg)
    if aggregated_msg is None:
        if on_superseded:
            on_superseded()
        return None

    final_text = aggregated_msg.text
    final_metadata = aggregated_msg.extra_metadata
    has_image_final = bool(getattr(aggregated_msg, "has_image", False))
    if not has_image_final and isinstance(final_metadata, dict):
        has_image_final = bool(final_metadata.get("has_image"))

    if on_debounced:
        on_debounced(aggregated_msg, has_image_final, final_text, final_metadata)

    if time_budget_provider is not None:
        time_budget = time_budget_provider(has_image_final)

    if time_budget is None:
        result = await handler.process_message(user_id, final_text, extra_metadata=final_metadata)
    else:
        result = await asyncio.wait_for(
            handler.process_message(user_id, final_text, extra_metadata=final_metadata),
            timeout=max(time_budget, 1.0),
        )

    return PipelineResult(
        result=result,
        aggregated_msg=aggregated_msg,
        has_image=has_image_final,
        final_text=final_text,
        final_metadata=final_metadata,
    )
