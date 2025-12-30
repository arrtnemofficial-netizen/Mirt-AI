"""
FSM Response Policy - Определение response policy на основе manifest.
=====================================================================

Этот модуль определяет, какой snippet отправить (если нужно) на основе
manifest.json и idempotency flags.

КЛЮЧЕВАЯ ИДЕЯ:
- Snippet selection через manifest (без хардкода строк в коде)
- Idempotency через metadata flags
- Один user turn → максимум один assistant response
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.agents.langgraph.fsm.transition_reducer import ResponsePolicy

logger = logging.getLogger(__name__)

# Кэш manifest (загружается один раз)
_manifest_cache: dict[str, Any] | None = None


def load_manifest() -> dict[str, Any]:
    """Загрузить manifest.json (с кэшированием)."""
    global _manifest_cache
    
    if _manifest_cache is not None:
        return _manifest_cache
    
    manifest_path = Path(__file__).parent.parent.parent.parent / "data" / "prompts" / "snippets" / "manifest.json"
    
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            _manifest_cache = json.load(f)
        logger.debug("Loaded snippet manifest from %s", manifest_path)
        return _manifest_cache
    except FileNotFoundError:
        logger.warning("Snippet manifest not found at %s, using empty manifest", manifest_path)
        return {"actions": {}, "rules": []}
    except json.JSONDecodeError as e:
        logger.error("Failed to parse snippet manifest: %s", e)
        return {"actions": {}, "rules": []}


def determine_response_policy(
    next_state: str,
    payment_sub_phase: str | None,
    metadata: dict[str, Any],
    session_id: str,
) -> ResponsePolicy:
    """
    Определить response policy на основе manifest и idempotency.
    
    ИНВАРИАНТ: Snippet отправляется ровно один раз (контролируется idempotency_key).
    
    Args:
        next_state: Следующее состояние
        payment_sub_phase: Payment sub-phase (если STATE_5)
        metadata: Метаданные состояния (содержит idempotency flags)
        session_id: ID сессии для логирования
    
    Returns:
        ResponsePolicy с snippet_name, snippet_sent_flag, use_llm
    """
    manifest = load_manifest()
    rules = manifest.get("rules", [])
    actions = manifest.get("actions", {})
    
    # Ищем правило, которое соответствует условию
    for rule in rules:
        condition = rule.get("condition", {})
        action_id = rule.get("action")
        
        # Проверяем условие
        state_match = condition.get("state") == next_state
        sub_phase_match = condition.get("payment_sub_phase") == payment_sub_phase if payment_sub_phase else condition.get("payment_sub_phase") is None
        
        if state_match and sub_phase_match and action_id:
            # Нашли правило - проверяем action definition
            action_def = actions.get(action_id)
            if not action_def:
                logger.warning(
                    "[SESSION %s] Action '%s' not found in manifest, using LLM",
                    session_id,
                    action_id,
                )
                return ResponsePolicy(
                    snippet_name=None,
                    snippet_sent_flag=None,
                    use_llm=True,
                )
            
            snippet_header = action_def.get("snippet_header")
            idempotency_key = action_def.get("idempotency_key")
            
            if not snippet_header or not idempotency_key:
                logger.warning(
                    "[SESSION %s] Action '%s' missing snippet_header or idempotency_key, using LLM",
                    session_id,
                    action_id,
                )
                return ResponsePolicy(
                    snippet_name=None,
                    snippet_sent_flag=None,
                    use_llm=True,
                )
            
            # Проверяем idempotency (уже отправляли?)
            already_sent = metadata.get(idempotency_key, False)
            
            if already_sent:
                logger.info(
                    "[SESSION %s] Snippet '%s' already sent (idempotency_key=%s), using LLM",
                    session_id,
                    snippet_header,
                    idempotency_key,
                )
                return ResponsePolicy(
                    snippet_name=None,
                    snippet_sent_flag=None,
                    use_llm=True,
                )
            else:
                logger.info(
                    "[SESSION %s] Will send snippet '%s' (action=%s, first time)",
                    session_id,
                    snippet_header,
                    action_id,
                )
                return ResponsePolicy(
                    snippet_name=snippet_header,
                    snippet_sent_flag=idempotency_key,
                    use_llm=False,  # Используем snippet, не LLM
                )
    
    # Не нашли правило → используем LLM
    return ResponsePolicy(
        snippet_name=None,
        snippet_sent_flag=None,
        use_llm=True,
    )

