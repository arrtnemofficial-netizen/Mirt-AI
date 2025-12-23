"""
Intent-Specific Instructions Helper.
====================================
Provides context-specific instructions for LLM based on detected intent.
This is policy/logic that can be reused across nodes.
"""

from typing import Any


def get_instructions_for_intent(intent: str, state: dict[str, Any]) -> str:
    """Get context-specific instructions based on detected intent."""
    
    instructions = {
        "GREETING_ONLY": (
            "Привітай клієнта тепло, як MIRT_UA менеджер Софія. "
            "Запитай чим можеш допомогти. "
            "Не перевантажуй інформацією - будь лаконічною."
        ),
        "DISCOVERY_OR_QUESTION": (
            "Допоможи клієнту знайти товар. "
            "Запитай про вік/зріст дитини та тип речі (сукня, костюм, тощо). "
            "Будь дружньою та професійною."
        ),
        "PHOTO_IDENT": (
            "Клієнт надіслав фото. "
            "Якщо це товар з каталогу - покажи його з ціною. "
            "Якщо не впевнена - запитай уточнення або ескалюй до менеджера."
        ),
        "SIZE_HELP": (
            "Клієнт питає про розмір. "
            "Дай КОНКРЕТНУ відповідь з розмірної сітки. "
            "Якщо знаєш зріст - підбери розмір. "
            "Якщо є вибраний товар - переходь до пропозиції!"
        ),
        "COLOR_HELP": (
            "Клієнт питає про колір. "
            "Покажи доступні кольори для товару. "
            "Якщо товар є в потрібному кольорі - підтверди. "
            "Якщо немає - запропонуй альтернативи."
        ),
        "PAYMENT_DELIVERY": (
            "Клієнт готовий оформлювати замовлення. "
            "Збери дані для доставки: ПІБ, телефон, місто, відділення Нової Пошти. "
            "Після збору даних - покажи реквізити для оплати."
        ),
        "COMPLAINT": (
            "Клієнт має скаргу або проблему. "
            "Вислухай уважно, вибачся за незручності. "
            "Ескалюй до менеджера якщо потрібна допомога."
        ),
        "THANKYOU_SMALLTALK": (
            "Клієнт подякував або веде світську бесіду. "
            "Відповідай тепло, але коротко. "
            "Запропонуй допомогу, якщо потрібно."
        ),
        "OUT_OF_DOMAIN": (
            "Питання не стосується товарів MIRT_UA. "
            "Ввічливо поверни розмову до теми одягу для дітей. "
            "Якщо це неможливо - ескалюй до менеджера."
        ),
    }
    
    # Get base instruction for intent
    base_instruction = instructions.get(intent, instructions.get("DISCOVERY_OR_QUESTION", ""))
    
    # Add product context if available
    products = state.get("selected_products", [])
    if products:
        product_names = ", ".join(p.get("name", "товар") for p in products[:3])
        base_instruction = f"{base_instruction}\n\nУ діалозі вже є товари: {product_names}."
    
    # Add state-specific context if available
    current_state = state.get("current_state", "")
    dialog_phase = state.get("dialog_phase", "")
    
    # Payment-specific additions
    if intent == "PAYMENT_DELIVERY" and current_state == "STATE_5_PAYMENT_DELIVERY":
        if dialog_phase == "WAITING_FOR_DELIVERY_DATA":
            base_instruction += " Зараз збираємо дані для доставки."
        elif dialog_phase == "WAITING_FOR_PAYMENT_METHOD":
            base_instruction += " Зараз визначаємо спосіб оплати."
        elif dialog_phase == "WAITING_FOR_PAYMENT_PROOF":
            base_instruction += " Чекаємо скрін квитанції про оплату."
    
    return base_instruction

