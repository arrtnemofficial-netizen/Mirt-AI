from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from src.services.infra.debouncer import BufferedMessage, MessageDebouncer

logger = logging.getLogger(__name__)


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
    # Log what we're creating BufferedMessage with (INFO level for debugging)
    logger.info(
        "[PIPELINE] Creating BufferedMessage: user_id=%s text_preview=%s image_url=%s has_image=%s",
        user_id,
        text[:50] if text else "",
        image_url[:50] if image_url else None,
        bool(image_url),
    )
    
    buffered_msg = BufferedMessage(
        text=text,
        has_image=bool(image_url),
        image_url=image_url,
        extra_metadata=extra_metadata or {},
    )
    # #region agent log
    try:
        import json
        with open(r'c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"pipeline.py:55","message":"Created BufferedMessage","data":{"user_id":user_id,"has_image":bool(image_url),"image_url":image_url[:50] if image_url else None},"timestamp":int(__import__('time').time()*1000)}) + '\n')
    except: pass
    # #endregion

    aggregated_msg = await debouncer.wait_for_debounce(user_id, buffered_msg)
    if aggregated_msg is None:
        if on_superseded:
            on_superseded()
        return None

    final_text = aggregated_msg.text
    final_metadata = dict(aggregated_msg.extra_metadata) if aggregated_msg.extra_metadata else {}
    
    # CRITICAL: Extract image_url from aggregated_msg and add to final_metadata
    # This ensures image_url is preserved through debouncing
    has_image_final = bool(getattr(aggregated_msg, "has_image", False))
    image_url_final = getattr(aggregated_msg, "image_url", None)
    # #region agent log
    try:
        import json
        with open(r'c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log', 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"pipeline.py:69","message":"After debounce - extracted from aggregated_msg","data":{"user_id":user_id,"has_image":has_image_final,"image_url":image_url_final[:50] if image_url_final else None},"timestamp":int(__import__('time').time()*1000)}) + '\n')
    except: pass
    # #endregion
    
    # Update final_metadata with image info from aggregated_msg
    if image_url_final:
        final_metadata["image_url"] = image_url_final
        final_metadata["has_image"] = True
        has_image_final = True
        logger.debug(
            "[PIPELINE] Image URL extracted from aggregated_msg: url=%s (user_id=%s)",
            image_url_final[:50] if image_url_final else None,
            user_id,
        )
        # #region agent log
        try:
            import json
            with open(r'c:\Users\Zoroo\Documents\GitHub\Mirt-AI\.cursor\debug.log', 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"pipeline.py:75","message":"Added image_url to final_metadata","data":{"user_id":user_id,"image_url":image_url_final[:50] if image_url_final else None,"final_metadata_has_image":final_metadata.get("has_image")},"timestamp":int(__import__('time').time()*1000)}) + '\n')
        except: pass
        # #endregion
    elif has_image_final:
        # If has_image is True but image_url is None, check metadata
        if isinstance(final_metadata, dict) and final_metadata.get("image_url"):
            has_image_final = True
            image_url_final = final_metadata.get("image_url")
        else:
            # Fallback: check if has_image is in metadata
            has_image_final = bool(final_metadata.get("has_image", False))
    
    logger.debug(
        "[PIPELINE] Final metadata for handler: has_image=%s image_url=%s (user_id=%s)",
        has_image_final,
        "present" if image_url_final else "none",
        user_id,
    )

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
