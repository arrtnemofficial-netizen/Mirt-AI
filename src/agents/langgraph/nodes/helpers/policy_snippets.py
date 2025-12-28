"""
Policy Snippets Helper - Snippets-first policy layer.
=====================================================
This module provides a policy layer that checks for predefined snippets
before calling LLM, ensuring consistent responses for common scenarios.
"""

from __future__ import annotations

import logging
from typing import Any

from src.agents.langgraph.nodes.helpers.vision.snippet_loader import get_snippet_by_header

logger = logging.getLogger(__name__)


def _is_clarification_context(text: str) -> bool:
    """
    Перевіряє чи 'ні' є частиною уточнення, а не відмовою.
    
    Args:
        text: User message text
        
    Returns:
        True if this is a clarification (not a refusal), False otherwise
    """
    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Clarification patterns: "ні" + уточнення (розмір, колір, тощо)
    clarification_patterns = [
        "ні, не підходить",
        "нет, не подходит",
        "ні, не той",
        "нет, не тот",
        "ні, інший",
        "нет, другой",
        "ні, не підходить розмір",
        "нет, не подходит размер",
        "ні, не підходить колір",
        "нет, не подходит цвет",
        "ні, не той розмір",
        "нет, не тот размер",
        "ні, не той колір",
        "нет, не тот цвет",
        "ні, інший розмір",
        "нет, другой размер",
        "ні, інший колір",
        "нет, другой цвет",
        "ні, не підійде",
        "нет, не подойдет",
        "ні, не підходить цей",
        "нет, не подходит этот",
    ]
    
    # Check if text contains clarification pattern
    for pattern in clarification_patterns:
        if pattern in text_lower:
            return True
    
    return False


def detect_user_says_no(text: str, state: dict[str, Any] | None = None) -> tuple[bool, str]:
    """
    Detect if user explicitly says "no" or refuses.
    
    Now distinguishes between refusal and clarification.
    
    Args:
        text: User message text
        state: Current conversation state (optional, for future context checks)
        
    Returns:
        Tuple of (is_refusal, reason)
        - is_refusal: True if this is a refusal, False otherwise
        - reason: 'refusal' | 'clarification' | 'none'
    """
    if not text:
        return False, "none"
    
    # CRITICAL: Check if this is a clarification first
    if _is_clarification_context(text):
        logger.debug("Context check: '%s' is a clarification, not a refusal", text[:50])
        return False, "clarification"
    
    text_lower = text.lower().strip()
    
    # Explicit refusal patterns (standalone "no" or clear refusal)
    # These are patterns that indicate actual refusal, not clarification
    refusal_patterns = [
        "ні",  # Standalone "no"
        "нет",  # Standalone "no" (Russian)
        "не хочу",
        "не буду",
        "не потрібно",
        "не треба",
        "відміняємо",
        "відмінити",
        "передумала",
        "передумав",
        "не цікавить",
        "не цікаво",
        "не потрібен",
        "не потрібна",
        "не потрібне",
        "відмовляюсь",
        "отказываюсь",
        "не буду брати",
        "не буду купувати",
    ]
    
    # Check for exact matches or patterns
    for pattern in refusal_patterns:
        if pattern in text_lower:
            # Additional check: if pattern is "ні" or "нет", make sure it's not part of clarification
            if pattern in ("ні", "нет"):
                # If "ні" is followed by comma and clarification, it's not a refusal
                if "," in text_lower:
                    parts = text_lower.split(",")
                    if len(parts) > 1 and any(
                        kw in parts[1] for kw in ["не підходить", "не той", "інший", "не подходит", "не тот", "другой"]
                    ):
                        return False, "clarification"
            logger.debug("Refusal detected: '%s' matches pattern '%s'", text[:50], pattern)
            return True, "refusal"
    
    return False, "none"


def _is_color_request_context(text: str, state: dict[str, Any] | None) -> bool:
    """
    Перевіряє чи це запит про колір, а не новий товар.
    
    Args:
        text: User message text
        state: Current conversation state
        
    Returns:
        True if this is a color request, False otherwise
    """
    if not text or not state:
        return False
    
    text_lower = text.lower()
    color_keywords = [
        "колір",
        "цвет",
        "кольори",
        "цвета",
        "інший колір",
        "другой цвет",
        "інші кольори",
        "другие цвета",
        "які кольори",
        "какие цвета",
    ]
    
    # Перевіряємо чи є ключові слова про колір
    has_color_keyword = any(kw in text_lower for kw in color_keywords)
    
    # Перевіряємо чи в state є selected_products або offered_products (контекст поточного товару)
    # Check for product context in state or metadata (stable SSOT).
    metadata = state.get("metadata", {}) if isinstance(state, dict) else {}
    has_product_context = bool(
        state.get("selected_products")
        or state.get("offered_products")
        or metadata.get("current_product_name")
        or metadata.get("color_gallery_product")
    )
    
    # Якщо є ключові слова про колір І є контекст поточного товару → це запит про колір
    return has_color_keyword and has_product_context


def detect_explicit_new_product(text: str, state: dict[str, Any] | None = None) -> bool:
    """
    Detect if user explicitly wants to analyze a new product (with photo).
    
    Now includes context check to exclude color requests.
    
    Args:
        text: User message text
        state: Current conversation state (optional, for context checking)
        
    Returns:
        True if user explicitly requests new product analysis, False otherwise
    """
    if not text:
        return False
    
    # CRITICAL: Check context first - if this is a color request, it's NOT a new product
    if _is_color_request_context(text, state):
        logger.debug("Context check: '%s' is a color request, not new product", text[:50])
        return False
    
    text_lower = text.lower().strip()
    
    # Expanded explicit new product patterns
    new_product_patterns = [
        # Original patterns
        "новий товар",
        "новый товар",
        "інший товар",
        "другой товар",
        "це інше",
        "это другое",
        "нове фото товару",
        "новое фото товара",
        "інше фото",
        "другое фото",
        "покажи інший",
        "покажи другой",
        # New expanded patterns
        "це ще одне",
        "это еще одно",
        "покажи ще",
        "покажи еще",
        "інша модель",
        "другая модель",
        "хочу подивитись інше",
        "хочу посмотреть другое",
        "покажи іншу модель",
        "покажи другую модель",
        "це інша річ",
        "это другая вещь",
        "нове фото",
        "новое фото",
        "інший товар на фото",
        "другой товар на фото",
        "це інший товар",
        "это другой товар",
        "хочу подивитись інший товар",
        "хочу посмотреть другой товар",
    ]
    
    # Check for patterns
    for pattern in new_product_patterns:
        if pattern in text_lower:
            logger.debug("Explicit new product trigger detected: '%s' matches pattern '%s'", text[:50], pattern)
            return True
    
    return False


def _get_offtopic_count(metadata: dict[str, Any]) -> int:
    """
    Отримує лічильник оффтоп-питань підряд з metadata.
    
    Args:
        metadata: Conversation metadata dict
        
    Returns:
        Count of off-topic questions in a row
    """
    policy_stats = metadata.get("policy_stats", {})
    return int(policy_stats.get("offtopic_count", 0))


def _increment_offtopic_count(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Збільшує лічильник оффтоп-питань підряд.
    
    Args:
        metadata: Conversation metadata dict
        
    Returns:
        Updated metadata dict
    """
    if "policy_stats" not in metadata:
        metadata["policy_stats"] = {}
    policy_stats = metadata["policy_stats"]
    policy_stats["offtopic_count"] = policy_stats.get("offtopic_count", 0) + 1
    return metadata


def _get_no_count(metadata: dict[str, Any]) -> int:
    """
    Отримує лічильник відмов підряд з metadata.
    
    Args:
        metadata: Conversation metadata dict
        
    Returns:
        Count of "no" responses in a row
    """
    policy_stats = metadata.get("policy_stats", {})
    return int(policy_stats.get("no_count", 0))


def _increment_no_count(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Збільшує лічильник відмов підряд.
    
    Args:
        metadata: Conversation metadata dict
        
    Returns:
        Updated metadata dict
    """
    if "policy_stats" not in metadata:
        metadata["policy_stats"] = {}
    policy_stats = metadata["policy_stats"]
    policy_stats["no_count"] = policy_stats.get("no_count", 0) + 1
    return metadata


def _get_payment_reminder_by_phase(dialog_phase: str) -> str | None:
    """
    Генерує конкретне нагадування про оплату залежно від фази.
    
    Args:
        dialog_phase: Current dialog phase
        
    Returns:
        Payment reminder text or None
    """
    reminders = {
        "WAITING_FOR_PAYMENT_PROOF": "Надішліть, будь ласка, квитанцію після оплати, щоб ми одразу сформували замовлення для вас 🙂",
        "WAITING_FOR_PAYMENT_METHOD": "Виберіть, будь ласка, спосіб оплати: повна оплата або передплата 200 грн 🤍",
        "WAITING_FOR_DELIVERY_DATA": "Вкажіть, будь ласка, дані для відправки: місто, відділення Нової Пошти, ПІБ та телефон ☺️",
    }
    return reminders.get(dialog_phase)


def _reset_policy_counters(metadata: dict[str, Any]) -> dict[str, Any]:
    """
    Скидає всі policy лічильники.
    
    Args:
        metadata: Conversation metadata dict
        
    Returns:
        Updated metadata dict with reset counters
    """
    if "policy_stats" not in metadata:
        metadata["policy_stats"] = {}
    policy_stats = metadata["policy_stats"]
    policy_stats["offtopic_count"] = 0
    policy_stats["no_count"] = 0
    return metadata


def detect_payment_problem(text: str) -> bool:
    """
    Detect if user reports payment problems.
    
    Args:
        text: User message text
        
    Returns:
        True if user reports payment problem, False otherwise
    """
    if not text:
        return False
    
    text_lower = text.lower().strip()
    
    # Payment problem patterns
    problem_patterns = [
        "не отримується",
        "не получается",
        "не проходить",
        "не проходит",
        "помилка оплати",
        "ошибка оплаты",
        "не можу оплатити",
        "не могу оплатить",
        "не виходить",
        "не выходит",
        "проблема з оплатою",
        "проблема с оплатой",
        "не працює оплата",
        "не работает оплата",
    ]
    
    # Check for patterns
    for pattern in problem_patterns:
        if pattern in text_lower:
            return True
    
    return False


def maybe_apply_snippet_policy(
    state: dict[str, Any],
    *,
    detected_intent: str | None = None,
    user_text: str | None = None,
) -> dict[str, Any] | None:
    """
    Apply snippets-first policy: check for predefined snippets before LLM.
    
    This function checks for common scenarios (NO, off-topic, etc.) and
    returns a ready-to-use response if a snippet is found.
    
    Args:
        state: Current graph state
        detected_intent: Detected intent from intent node
        user_text: User message text
        
    Returns:
        State update dict with agent_response/messages if snippet found, None otherwise
    """
    if not user_text:
        # Try to extract from state
        from src.agents.langgraph.nodes.utils import extract_user_message
        user_text = extract_user_message(state.get("messages", []))
    
    if not user_text:
        return None
    
    dialog_phase = state.get("dialog_phase", "INIT")
    metadata = state.get("metadata", {}) or {}
    session_id = state.get("session_id") or metadata.get("session_id") or "?"
    
    # Check for product addition intent WITHOUT photo (snippet response)
    has_image = bool(state.get("has_image", False) or metadata.get("has_image", False))
    if not has_image and dialog_phase in {"WAITING_FOR_PAYMENT_PROOF", "WAITING_FOR_PAYMENT_METHOD", "WAITING_FOR_DELIVERY_DATA"}:
        from src.agents.langgraph.rules.product_addition import detect_product_addition_intent
        
        if detect_product_addition_intent(user_text):
            logger.info(
                "[SESSION %s] Snippets-first: product addition intent detected without photo, returning snippet",
                session_id,
            )
            return {
                "agent_response": {
                    "event": "product_addition",
                    "messages": [
                        {
                            "type": "text",
                            "content": "Так, звісно, можна додати 😊 Надішліть, будь ласка, фото товару або опишіть що хочете додати до замовлення.",
                        }
                    ],
                    "metadata": {
                        "session_id": session_id,
                        "current_state": state.get("current_state", "STATE_5_PAYMENT_DELIVERY"),
                        "intent": "PRODUCT_ADDITION",
                        "escalation_level": "NONE",
                    },
                },
                "dialog_phase": dialog_phase,  # Stay in same phase
                "metadata": metadata,
            }
    
    # Check for "user says no" scenarios
    is_refusal, refusal_reason = detect_user_says_no(user_text, state)
    
    # Only process if it's an actual refusal (not clarification)
    if is_refusal and refusal_reason == "refusal":
        # Check "no" counter
        no_count = _get_no_count(metadata)
        
        next_no_count = no_count + 1

        # If 3+ "no" responses in a row → escalate
        if next_no_count >= 3:
            logger.warning(
                "[SESSION %s] Too many 'no' responses (%d) in a row, escalating",
                session_id,
                next_no_count,
            )
            return {
                "should_escalate": True,
                "escalation_reason": f"User refused 3+ times in a row ({next_no_count} times)",
                "escalation_level": "L1",
                "agent_response": {
                    "event": "escalation",
                    "messages": [
                        {
                            "type": "text",
                            "content": "Зрозуміло, без проблем 🤍\n\nЯкщо передумаєте - завжди раді допомогти. Можу показати інші варіанти, якщо цікаво",
                        }
                    ],
                    "metadata": {
                        **metadata,
                        "session_id": session_id,
                        "current_state": metadata.get("current_state", "STATE_5_PAYMENT_DELIVERY"),
                        "intent": detected_intent or "DISCOVERY_OR_QUESTION",
                        "escalation_level": "L1",
                        "policy_case": "no_escalation",
                        "should_notify_manager": True,
                    },
                },
                "metadata": {
                    **metadata,
                    "policy_case": "no_escalation",
                },
                "dialog_phase": dialog_phase,
            }
        
        # Normal handling: respond with snippet + increment counter
        snippet_header = None
        
        # Determine snippet header based on phase
        if dialog_phase in {
            "WAITING_FOR_PAYMENT_PROOF",
            "WAITING_FOR_PAYMENT_METHOD",
            "WAITING_FOR_DELIVERY_DATA",
        }:
            snippet_header = "Відмова (ні) під час оплати"
        elif dialog_phase == "OFFER_MADE":
            snippet_header = "Відмова (ні) після пропозиції (OFFER_MADE)"
        elif dialog_phase in {"WAITING_FOR_SIZE", "WAITING_FOR_COLOR"}:
            snippet_header = "Відмова (ні) на етапі підбору (WAITING_FOR_SIZE/WAITING_FOR_COLOR)"
        
        if snippet_header:
            bubbles = get_snippet_by_header(snippet_header)
            if bubbles:
                logger.info(
                    "[SESSION %s] Snippets-first: found snippet for 'user says no' in phase %s (count: %d)",
                    session_id,
                    dialog_phase,
                    no_count,
                )
                
                # Increment "no" counter
                updated_metadata = _increment_no_count(metadata.copy())
                
                # Build response messages
                messages = [{"role": "assistant", "content": bubble} for bubble in bubbles]
                
                # Determine if we need to notify manager (for payment phase)
                should_notify = dialog_phase == "WAITING_FOR_PAYMENT_PROOF"
                
                return {
                    "messages": messages,
                    "agent_response": {
                        "event": "snippet_response",
                        "messages": [{"type": "text", "content": bubble} for bubble in bubbles],
                        "metadata": {
                            **updated_metadata,
                            "session_id": session_id,
                            "current_state": metadata.get("current_state", "STATE_5_PAYMENT_DELIVERY"),
                            "intent": detected_intent or "DISCOVERY_OR_QUESTION",
                            "escalation_level": "NONE",
                            "policy_case": "user_says_no",
                            "snippet_used": snippet_header,
                            "should_notify_manager": should_notify,
                            "no_count": no_count + 1,
                        },
                    },
                    "metadata": updated_metadata,
                    # Keep dialog_phase unchanged (don't break FSM)
                    "dialog_phase": dialog_phase,
                }
    
    # Check for payment problems (in payment phases)
    if dialog_phase in {
        "WAITING_FOR_PAYMENT_PROOF",
        "WAITING_FOR_PAYMENT_METHOD",
        "WAITING_FOR_DELIVERY_DATA",
    }:
        if detect_payment_problem(user_text):
            # Payment problem: notify manager but continue dialogue
            logger.info(
                "[SESSION %s] Payment problem detected in phase %s, will notify manager",
                session_id,
                dialog_phase,
            )
            
            # Return state update with notification flag
            return {
                "agent_response": {
                    "event": "payment_problem",
                    "messages": [
                        {
                            "type": "text",
                            "content": "Зрозуміло, зараз перевірю з менеджером 🤍\n\nСпробуйте, будь ласка, ще раз, або напишіть деталі помилки",
                        }
                    ],
                    "metadata": {
                        **metadata,
                        "session_id": session_id,
                        "current_state": metadata.get("current_state", "STATE_5_PAYMENT_DELIVERY"),
                        "intent": "PAYMENT_DELIVERY",
                        "escalation_level": "NONE",
                        "policy_case": "payment_problem",
                        "should_notify_manager": True,
                    },
                },
                "metadata": {
                    **metadata,
                    "policy_case": "payment_problem",
                    "should_notify_manager": True,
                },
                "dialog_phase": dialog_phase,  # Stay in payment phase
            }
    
    # Check for off-topic in payment phase
    if dialog_phase in {
        "WAITING_FOR_PAYMENT_PROOF",
        "WAITING_FOR_PAYMENT_METHOD",
        "WAITING_FOR_DELIVERY_DATA",
    }:
        # Off-topic intents that should be handled but return to payment
        off_topic_intents = {
            "PRODUCT_CATEGORY",
            "REQUEST_PHOTO",
            "DISCOVERY_OR_QUESTION",
        }
        
        if detected_intent in off_topic_intents:
            # Check off-topic counter
            offtopic_count = _get_offtopic_count(metadata)
            next_offtopic_count = offtopic_count + 1
            
            # If 3+ off-topic questions in a row → escalate
            if next_offtopic_count >= 3:
                logger.warning(
                    "[SESSION %s] Too many off-topic questions (%d) in payment phase, escalating",
                    session_id,
                    next_offtopic_count,
                )
                return {
                    "should_escalate": True,
                    "escalation_reason": f"Too many off-topic questions in payment phase ({next_offtopic_count} in a row)",
                    "escalation_level": "L1",
                    "agent_response": {
                        "event": "escalation",
                        "messages": [
                            {
                                "type": "text",
                                "content": "Зрозуміло, що у вас є питання 🤍\n\nДавайте спочатку завершимо оплату, а потім я відповім на всі ваші питання детально",
                            }
                        ],
                        "metadata": {
                            **metadata,
                            "session_id": session_id,
                            "current_state": metadata.get("current_state", "STATE_5_PAYMENT_DELIVERY"),
                            "intent": detected_intent,
                            "escalation_level": "L1",
                            "policy_case": "offtopic_escalation",
                        },
                    },
                    "metadata": {
                        **metadata,
                        "policy_case": "offtopic_escalation",
                    },
                    "dialog_phase": dialog_phase,
                }
            
            # Normal handling: respond with snippet + increment counter
            snippet_header = "Оффтоп під час оплати (коротко + повернення до оплати)"
            bubbles = get_snippet_by_header(snippet_header)
            
            if bubbles:
                logger.info(
                    "[SESSION %s] Snippets-first: found snippet for off-topic in payment phase (count: %d)",
                    session_id,
                    offtopic_count,
                )
                
                # Increment off-topic counter
                updated_metadata = _increment_offtopic_count(metadata.copy())
                
                # Get payment reminder by phase
                payment_reminder = _get_payment_reminder_by_phase(dialog_phase)
                
                # Build response messages (snippet bubbles + payment reminder)
                messages = [{"role": "assistant", "content": bubble} for bubble in bubbles]
                if payment_reminder:
                    messages.append({"role": "assistant", "content": payment_reminder})
                
                # Prepare bubbles for agent_response (include reminder)
                response_bubbles = [bubble for bubble in bubbles]
                if payment_reminder:
                    response_bubbles.append(payment_reminder)
                
                return {
                    "messages": messages,
                    "agent_response": {
                        "event": "offtopic_in_payment",
                        "messages": [{"type": "text", "content": bubble} for bubble in response_bubbles],
                        "metadata": {
                            **updated_metadata,
                            "session_id": session_id,
                            "current_state": metadata.get("current_state", "STATE_5_PAYMENT_DELIVERY"),
                            "intent": detected_intent,
                            "escalation_level": "NONE",
                            "policy_case": "offtopic_in_payment",
                            "snippet_used": snippet_header,
                            "offtopic_count": offtopic_count + 1,
                        },
                    },
                    "metadata": updated_metadata,
                    # Keep dialog_phase unchanged (return to payment)
                    "dialog_phase": dialog_phase,
                }
    
    # =========================================================================
    # EXIT CONDITIONS CHECK (before LLM)
    # =========================================================================
    # These are deterministic exit conditions that should trigger escalation
    # without calling LLM
    
    # 1. Wholesale/opт/гурт exit
    if detect_wholesale_exit(user_text):
        session_id = state.get("session_id", "?")
        logger.info(
            "[POLICY] Wholesale/opт detected - silent exit (session=%s)",
            session_id,
        )
        # Track metric for analytics
        from src.services.observability import track_metric
        track_metric(
            "wholesale_exit_triggered",
            1,
            {
                "session_id": session_id,
                "dialog_phase": state.get("dialog_phase", "UNKNOWN"),
            },
        )
        # CRITICAL: Silent exit - не відповідаємо клієнту, але менеджеру відправляємо Telegram
        # Це потенційний великий клієнт, менеджер має знати
        return {
            "messages": [],  # Empty messages - клієнту нічого не відправляємо
            "should_escalate": True,  # Менеджеру відправляємо Telegram
            "escalation_reason": "Замовлення на гурт (опт)",
            "escalation_level": "L1",
            "dialog_phase": "ESCALATED",
            "metadata": {
                **state.get("metadata", {}),
                "exit_condition": "wholesale_order",
                "policy_case": "wholesale_exit",
                "silent_exit": True,  # Flag для channel layer - не відправляти empty messages
            },
        }
    
    # 2. Return/exchange action exit
    if detect_return_exchange_action(user_text):
        session_id = state.get("session_id", "?")
        logger.info(
            "[POLICY] Return/exchange action detected - exiting (session=%s)",
            session_id,
        )
        # Track metric for analytics
        from src.services.observability import track_metric
        track_metric(
            "return_exchange_exit_triggered",
            1,
            {
                "session_id": session_id,
                "dialog_phase": state.get("dialog_phase", "UNKNOWN"),
            },
        )
        # Bot is forbidden from accepting returns/exchanges
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Зрозуміло. Передаю ваш запит менеджеру для обробки обміну/повернення.",
                }
            ],
            "should_escalate": True,
            "escalation_reason": "Клієнт бажає обміняти чи повернути товар",
            "escalation_level": "L1",
            "dialog_phase": "ESCALATED",
            "metadata": {
                **state.get("metadata", {}),
                "exit_condition": "return_exchange_action",
                "policy_case": "return_exchange_exit",
            },
        }
    
    # 3. Urgent delivery exit
    if detect_urgent_delivery_exit(user_text):
        session_id = state.get("session_id", "?")
        logger.info(
            "[POLICY] Urgent delivery request detected - exiting (session=%s)",
            session_id,
        )
        # Track metric for analytics
        from src.services.observability import track_metric
        track_metric(
            "urgent_delivery_exit_triggered",
            1,
            {
                "session_id": session_id,
                "dialog_phase": state.get("dialog_phase", "UNKNOWN"),
            },
        )
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": "Зрозуміло, термінова відправка. Передаю менеджеру для обробки.",
                }
            ],
            "should_escalate": True,
            "escalation_reason": "Термінова відправка",
            "escalation_level": "L1",
            "dialog_phase": "ESCALATED",
            "metadata": {
                **state.get("metadata", {}),
                "exit_condition": "urgent_delivery",
                "policy_case": "urgent_delivery_exit",
            },
        }
    
    # 4. Missing product info (handled via escalation_reason from LLM)
    # This is checked in agent node after LLM call
    
    # No snippet found - return None to continue with LLM
    return None


# =============================================================================
# EXIT CONDITIONS DETECTION (SSOT)
# =============================================================================

def detect_wholesale_exit(user_text: str) -> bool:
    """
    Detect if user asks about wholesale/opт/гурт/дроп.
    
    This is an exit condition - bot should respond with snippet and escalate.
    
    Args:
        user_text: User message text
        
    Returns:
        True if wholesale/opт detected, False otherwise
    """
    if not user_text:
        return False
    
    text_lower = user_text.lower()
    wholesale_keywords = [
        "опт", "оптом", "оптов", "оптово",
        "гурт", "гуртом", "гуртов",
        "дроп", "дропом", "дропшип",
        "ростовки", "ростовок",
        "прайс для перепродажу",
        "wholesale", "bulk",
    ]
    
    return any(keyword in text_lower for keyword in wholesale_keywords)


def detect_return_exchange_action(user_text: str) -> bool:
    """
    Detect if user wants to RETURN or EXCHANGE (action, not consultation).
    
    CRITICAL: This is NOT a consultation question (e.g., "чи можна повернути?").
    This is an ACTION request (e.g., "хочу повернути", "оформити обмін").
    
    Args:
        user_text: User message text
        
    Returns:
        True if return/exchange action detected, False otherwise
    """
    if not user_text:
        return False
    
    text_lower = user_text.lower()
    
    # Consultation patterns (NOT exit conditions)
    consultation_patterns = [
        "чи можна повернути",
        "можно ли вернуть",
        "чи є обмін",
        "есть ли обмен",
        "які умови повернення",
        "какие условия возврата",
        "чи можна обміняти",
        "можно ли обменять",
        "як повернути",
        "как вернуть",
        "як обміняти",
        "как обменять",
    ]
    
    # Check if this is a consultation question first
    for pattern in consultation_patterns:
        if pattern in text_lower:
            return False  # This is a consultation, not an action
    
    # Action patterns (exit conditions)
    action_patterns = [
        "хочу повернути",
        "хочу вернуть",
        "повернути товар",
        "вернуть товар",
        "оформити повернення",
        "оформить возврат",
        "зробити повернення",
        "сделать возврат",
        "хочу обміняти",
        "хочу обменять",
        "обміняти товар",
        "обменять товар",
        "оформити обмін",
        "оформить обмен",
        "зробити обмін",
        "сделать обмен",
        "повертаю товар",
        "возвращаю товар",
        "обмінюю товар",
        "обмениваю товар",
    ]
    
    return any(pattern in text_lower for pattern in action_patterns)


def detect_urgent_delivery_exit(user_text: str) -> bool:
    """
    Detect if user explicitly requests URGENT delivery.
    
    CRITICAL: Only exit if user EXPLICITLY requests urgent delivery.
    Do NOT exit for general questions like "як швидко відправляєте?".
    
    Args:
        user_text: User message text
        
    Returns:
        True if explicit urgent delivery request, False otherwise
    """
    if not user_text:
        return False
    
    text_lower = user_text.lower()
    
    # General questions (NOT exit conditions)
    general_questions = [
        "як швидко ви відправляєте",
        "как быстро вы отправляете",
        "коли буде доставка",
        "когда будет доставка",
        "коли приблизно отримаю",
        "когда примерно получу",
        "скільки часу доставка",
        "сколько времени доставка",
        "як довго йде посилка",
        "как долго идет посылка",
    ]
    
    # Check if this is a general question first
    for pattern in general_questions:
        if pattern in text_lower:
            return False  # This is a general question, not urgent request
    
    # Explicit urgent patterns (exit conditions)
    urgent_patterns = [
        "мені терміново треба",
        "мне срочно нужно",
        "потрібна якнайшвидша доставка",
        "нужна как можно скорее доставка",
        "можете сьогодні відправити",
        "можете сегодня отправить",
        "терміново",
        "срочно",
        "якнайшвидше",
        "как можно скорее",
        "дуже терміново",
        "очень срочно",
        "потрібно терміново",
        "нужно срочно",
    ]
    
    return any(pattern in text_lower for pattern in urgent_patterns)


def detect_missing_product_info(user_text: str, state: dict[str, Any]) -> bool:
    """
    Detect if user asks about product info that's missing from instructions.
    
    This is detected when:
    1. User asks a product question
    2. LLM would need to answer but info is not in instructions
    (This is handled via escalation_reason="missing_product_info" from LLM)
    
    For now, this is a placeholder - actual detection happens in agent node
    when LLM sets escalation_reason="missing_product_info".
    
    Args:
        user_text: User message text
        state: Current conversation state
        
    Returns:
        True if missing info detected, False otherwise
    """
    # Check if escalation_reason indicates missing info
    escalation_reason = state.get("escalation_reason") or state.get("metadata", {}).get("escalation_reason")
    if escalation_reason == "missing_product_info":
        return True
    
    return False



