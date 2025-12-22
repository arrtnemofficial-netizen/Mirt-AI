from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.conf.config import settings
from src.core.logging import log_event, safe_preview
from src.services.infra.media_utils import normalize_image_url

from .response_builder import _get_manychat_config


def get_time_budget(has_image: bool) -> float:
    try:
        text_budget = float(getattr(settings, "MANYCHAT_TEXT_TIME_BUDGET_SECONDS", 25.0))
        vision_budget = float(getattr(settings, "MANYCHAT_VISION_TIME_BUDGET_SECONDS", 55.0))
    except Exception:
        text_budget, vision_budget = 25.0, 55.0
    return vision_budget if has_image else text_budget


def build_extra_metadata(
    *,
    user_id: str,
    channel: str,
    image_url: str | None,
    subscriber_data: dict[str, Any] | None,
    trace_id: str,
    logger: logging.Logger,
) -> dict[str, Any]:
    extra_metadata: dict[str, Any] = {}

    if image_url:
        normalized = normalize_image_url(image_url)
        extra_metadata.update({"has_image": True, "image_url": normalized})
        log_event(
            logger,
            event="manychat_image_attached",
            trace_id=trace_id,
            user_id=user_id,
            channel=channel,
            has_image=True,
            image_url_preview=safe_preview(normalized, 100),
        )

    if subscriber_data:
        instagram_username = subscriber_data.get("instagram_username") or subscriber_data.get("username")
        if instagram_username:
            extra_metadata["instagram_username"] = instagram_username
            log_event(
                logger,
                event="manychat_subscriber_username",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
            )

        name = (
            subscriber_data.get("name")
            or subscriber_data.get("full_name")
            or subscriber_data.get("first_name")
        )
        if name:
            extra_metadata["user_nickname"] = name
            log_event(
                logger,
                event="manychat_subscriber_name",
                trace_id=trace_id,
                user_id=user_id,
                channel=channel,
            )

    return extra_metadata


async def safe_send_text(
    push_client,
    *,
    subscriber_id: str,
    text: str,
    channel: str,
    trace_id: str | None = None,
) -> bool:
    try:
        return await push_client.send_text(
            subscriber_id=subscriber_id,
            text=text,
            channel=channel,
            trace_id=trace_id,
        )
    except TypeError:
        return await push_client.send_text(
            subscriber_id=subscriber_id,
            text=text,
            channel=channel,
        )


async def safe_send_content(
    push_client,
    *,
    subscriber_id: str,
    messages: list[dict[str, Any]],
    channel: str,
    quick_replies: list[dict[str, str]] | None,
    set_field_values: list[dict[str, Any]] | None,
    add_tags: list[str] | None,
    remove_tags: list[str] | None,
    trace_id: str | None = None,
) -> bool:
    try:
        return await push_client.send_content(
            subscriber_id=subscriber_id,
            messages=messages,
            channel=channel,
            quick_replies=quick_replies,
            set_field_values=set_field_values,
            add_tags=add_tags,
            remove_tags=remove_tags,
            trace_id=trace_id,
        )
    except TypeError:
        return await push_client.send_content(
            subscriber_id=subscriber_id,
            messages=messages,
            channel=channel,
            quick_replies=quick_replies,
            set_field_values=set_field_values,
            add_tags=add_tags,
            remove_tags=remove_tags,
        )


async def maybe_push_interim(
    push_client,
    *,
    user_id: str,
    channel: str,
    trace_id: str,
    has_image: bool,
    logger: logging.Logger,
) -> None:
    """Push a short interim message if processing is taking too long."""
    try:
        fallback_after = float(getattr(settings, "MANYCHAT_FALLBACK_AFTER_SECONDS", 10.0))
    except Exception:
        fallback_after = 10.0

    if fallback_after <= 0:
        return

    await asyncio.sleep(fallback_after)

    config = _get_manychat_config()
    interim_cfg = config.get("interim_messages", {}) if isinstance(config, dict) else {}
    if has_image:
        interim_text = str(interim_cfg.get("text_with_image", "Working on it...")).strip()
    else:
        interim_text = str(interim_cfg.get("text", "Working on it...")).strip()

    if not interim_text:
        return
    await safe_send_text(
        push_client,
        subscriber_id=user_id,
        text=interim_text,
        channel=channel,
        trace_id=trace_id,
    )


async def handle_restart_command(
    *,
    user_id: str,
    channel: str,
    runner,
    store,
    debouncer,
    push_client,
    logger: logging.Logger,
) -> None:
    """Handle /restart command - clear session and confirm."""
    import time as _time

    _restart_start = _time.time()
    # Track inflight guard is handled outside (service-level set)
    try:
        debouncer.clear_session(user_id)
    except Exception:
        logger.debug("[MANYCHAT:%s] Failed to clear debouncer session", user_id, exc_info=True)

    try:
        from src.agents.langgraph.state import create_initial_state

        reset_state = create_initial_state(
            session_id=user_id,
            metadata={"channel": channel},
        )
        _lg_start = _time.time()
        await asyncio.wait_for(
            runner.aupdate_state(
                {"configurable": {"thread_id": user_id}},
                reset_state,
            ),
            timeout=5.0,
        )
        logger.info(
            "[MANYCHAT:%s] LangGraph state reset via /restart (%.2fs)",
            user_id,
            _time.time() - _lg_start,
        )
    except TimeoutError:
        logger.warning("[MANYCHAT:%s] LangGraph state reset timed out (>5s), skipping", user_id)
    except Exception:
        logger.debug(
            "[MANYCHAT:%s] Failed to reset LangGraph state via /restart",
            user_id,
            exc_info=True,
        )

    _del_start = _time.time()
    deleted = await asyncio.to_thread(store.delete, user_id)
    logger.info("[MANYCHAT:%s] store.delete took %.2fs", user_id, _time.time() - _del_start)
    if deleted:
        logger.info("[MANYCHAT:%s] session cleared", user_id)
    else:
        logger.warning("[MANYCHAT:%s] session delete returned False", user_id)

    await safe_send_text(
        push_client,
        subscriber_id=user_id,
        text="Сесія очищена! Напишіть, будь ласка, запит ще раз 🙂",
        channel=channel,
    )
