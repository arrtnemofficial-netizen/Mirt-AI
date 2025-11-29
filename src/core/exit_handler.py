"""Exit conditions handler for MIRT AI.

Handles all exit conditions from the prompt rules:
- Незрозуміле повідомлення
- Відсутня інформація
- Замовлення прийнято
- Ескалація до адміна
etc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from src.core.models import AgentResponse, Escalation, Message, Metadata


logger = logging.getLogger(__name__)


class ExitCondition(str, Enum):
    """All possible exit conditions from prompt."""

    # Медіа/порожні повідомлення
    UNREADABLE_MESSAGE = "Незрозуміле повідомлення або незрозумілий формат повідомлення"

    # Відсутня інформація
    MISSING_PRODUCT_INFO = "Відсутня інформація по товару в інструкції"
    MISSING_MODEL_INFO = "Відсутня інформація по моделі в інструкції"
    MISSING_PROMPT_INFO = "Виклик адміна – відсутня інфо у промпті"

    # Замовлення
    ORDER_ACCEPTED = "замовлення прийнято, перехід до оплати"
    ORDER_WITH_PAYMENT_INFO = "Реквізити надано та замовлення прийнято"

    # Спеціальні випадки
    WHOLESALE = "Замовлення на гурт (опт)"
    RETURN_EXCHANGE = "Клієнт бажає обміняти чи повернути товар"
    URGENT_SHIPPING = "Термінова відправка"
    MORE_MEDIA_REQUEST = "Адмін клієнт просить більше фото та відео"

    # Адмін
    ADMIN = "Адмін"


@dataclass
class ExitResponse:
    """Response for exit condition."""

    condition: ExitCondition
    escalation_level: str  # L1, L2, L3
    escalation_target: str  # admin, manager, logistics, etc.
    message_to_user: str | None = None  # None = не відповідати
    track_conversion: bool = False  # Чи це конверсія (замовлення)


# Конфігурація для кожної exit condition
EXIT_CONFIGS: dict[ExitCondition, ExitResponse] = {
    # Незрозумілі повідомлення - ескалація L1
    ExitCondition.UNREADABLE_MESSAGE: ExitResponse(
        condition=ExitCondition.UNREADABLE_MESSAGE,
        escalation_level="L1",
        escalation_target="admin",
        message_to_user=None,  # Не відповідати!
    ),
    # Відсутня інформація - ескалація L2
    ExitCondition.MISSING_PRODUCT_INFO: ExitResponse(
        condition=ExitCondition.MISSING_PRODUCT_INFO,
        escalation_level="L2",
        escalation_target="product_manager",
        message_to_user=None,  # Не писати користувачу
    ),
    ExitCondition.MISSING_MODEL_INFO: ExitResponse(
        condition=ExitCondition.MISSING_MODEL_INFO,
        escalation_level="L2",
        escalation_target="product_manager",
        message_to_user=None,
    ),
    ExitCondition.MISSING_PROMPT_INFO: ExitResponse(
        condition=ExitCondition.MISSING_PROMPT_INFO,
        escalation_level="L2",
        escalation_target="admin",
        message_to_user=None,
    ),
    # Замовлення прийнято - КОНВЕРСІЯ!
    ExitCondition.ORDER_ACCEPTED: ExitResponse(
        condition=ExitCondition.ORDER_ACCEPTED,
        escalation_level="L1",
        escalation_target="sales_manager",
        message_to_user="Дякую! Зараз надішлю реквізити для оплати 🤍",
        track_conversion=True,
    ),
    ExitCondition.ORDER_WITH_PAYMENT_INFO: ExitResponse(
        condition=ExitCondition.ORDER_WITH_PAYMENT_INFO,
        escalation_level="L1",
        escalation_target="sales_manager",
        message_to_user=None,  # Реквізити вже надані
        track_conversion=True,
    ),
    # Гурт
    ExitCondition.WHOLESALE: ExitResponse(
        condition=ExitCondition.WHOLESALE,
        escalation_level="L1",
        escalation_target="wholesale_manager",
        message_to_user=None,  # Нічого не відповідати
    ),
    # Повернення/обмін
    ExitCondition.RETURN_EXCHANGE: ExitResponse(
        condition=ExitCondition.RETURN_EXCHANGE,
        escalation_level="L2",
        escalation_target="customer_service",
        message_to_user="Дякую, інформація прийнята 🤍",
    ),
    # Термінова відправка
    ExitCondition.URGENT_SHIPPING: ExitResponse(
        condition=ExitCondition.URGENT_SHIPPING,
        escalation_level="L1",
        escalation_target="logistics_manager",
        message_to_user="Зрозуміло, передаю на термінову обробку! Менеджер зв'яжеться найближчим часом 🤍",
    ),
    # Більше медіа
    ExitCondition.MORE_MEDIA_REQUEST: ExitResponse(
        condition=ExitCondition.MORE_MEDIA_REQUEST,
        escalation_level="L1",
        escalation_target="admin",
        message_to_user="Передаю менеджеру для додаткових фото 🤍",
    ),
    # Адмін
    ExitCondition.ADMIN: ExitResponse(
        condition=ExitCondition.ADMIN,
        escalation_level="L2",
        escalation_target="admin",
        message_to_user="Перевіряю, зараз уточню у менеджера 🤍",
    ),
}


def handle_exit_condition(
    condition: str | ExitCondition,
    session_id: str,
    current_state: str = "STATE_0_INIT",
    metadata: dict | None = None,
) -> AgentResponse:
    """
    Handle exit condition and create appropriate response.

    Args:
        condition: Exit condition name
        session_id: Session identifier
        current_state: Current conversation state
        metadata: Additional metadata

    Returns:
        AgentResponse with escalation
    """
    # Normalize condition
    if isinstance(condition, str):
        try:
            condition = ExitCondition(condition)
        except ValueError:
            logger.warning("Unknown exit condition: %s", condition)
            condition = ExitCondition.ADMIN

    # Get config
    config = EXIT_CONFIGS.get(condition)
    if not config:
        logger.error("No config for exit condition: %s", condition)
        config = EXIT_CONFIGS[ExitCondition.ADMIN]

    # Build response
    messages = []
    if config.message_to_user:
        messages.append(Message(type="text", content=config.message_to_user))

    response = AgentResponse(
        event="escalation",
        messages=messages,
        products=[],
        metadata=Metadata(
            session_id=session_id,
            current_state=current_state,
            intent="EXIT_CONDITION",
            escalation_level=config.escalation_level,
            notes=f"Exit: {condition.value}",
        ),
        escalation=Escalation(
            level=config.escalation_level,
            reason=condition.value,
            target=config.escalation_target,
        ),
    )

    logger.info(
        "Exit condition triggered: %s (session: %s, target: %s)",
        condition.value,
        session_id,
        config.escalation_target,
    )

    return response


def should_track_conversion(condition: str | ExitCondition) -> bool:
    """Check if exit condition represents a conversion."""
    if isinstance(condition, str):
        try:
            condition = ExitCondition(condition)
        except ValueError:
            return False

    config = EXIT_CONFIGS.get(condition)
    return config.track_conversion if config else False


def is_exit_condition(text: str) -> ExitCondition | None:
    """
    Check if text matches any exit condition.

    Returns:
        ExitCondition if matched, None otherwise
    """
    text_lower = text.lower()

    # Check for wholesale
    if any(word in text_lower for word in ["гурт", "опт", "оптом"]):
        return ExitCondition.WHOLESALE

    # Check for urgent shipping
    urgent_keywords = ["терміново", "якнайшвидше", "сьогодні відправити"]
    if any(word in text_lower for word in urgent_keywords):
        return ExitCondition.URGENT_SHIPPING

    # Check for return/exchange (actual, not consultation)
    return_keywords = ["хочу повернути", "хочу обміняти", "номер картки"]
    if any(word in text_lower for word in return_keywords):
        return ExitCondition.RETURN_EXCHANGE

    return None
