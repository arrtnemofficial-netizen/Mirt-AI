"""
Core Intent Definitions.
========================
Single Source of Truth for all intent keywords and patterns.
Moved here to break circular dependencies between `nodes/agent.py` and `state_prompts.py`.
"""

from __future__ import annotations

# Intent keywords for quick detection
INTENT_PATTERNS = {
    "PAYMENT_DELIVERY": [
        "купую",
        "беру",
        "оплата",
        "реквізит",
        "замовл",
        "оформ",
        "карта",
        "переказ",
        "оплачу",
        "доставк",
        "нова пошта",
        "хочу куп",  # explicit purchase intent
    ],
    # Confirmation words that mean "yes" in OFFER state
    "CONFIRMATION": [
        "так",
        "да",
        "yes",
        "ок",
        "ok",
        "добре",
        "згодна",
        "згоден",
        "підходить",
        "давай",
        "давайте",
        "можна",
        "хочу",
        "буду",
        "годі",
        "файно",
        "супер",
    ],
    # Product names for selection in OFFER state
    "PRODUCT_NAMES": [
        "лагуна",
        "мрія",
        "ритм",
        "каприз",
        "валері",
        "мерея",
        "анна",
        "тренч",
        "еліт",
        "зірка",
        "софія",
        "вікторія",
        "мілана",
        "діана",
        "перший",
        "другий",
        "третій",
        "1",
        "2",
        "3",  # selection by number
    ],
    # Product category browsing - general type requests
    "PRODUCT_CATEGORY": [
        # Костюми
        "костюм",
        "костюмчик",
        "комплект",
        # Сукні
        "сукн",  # сукня, сукню, сукні
        "плаття",
        "платтячко",
        # Верхній одяг
        "тренч",
        "куртка",
        "курточка",
        "плащ",
        # Штани
        "штани",
        "штанці",
        "брюки",
        "джогери",
        # Верх
        "блуз",  # блуза, блузка, блузу
        "кофт",  # кофта, кофту
        "світшот",
        "худі",
        # General
        "одяг",
        "річ",
        "щось на",  # "щось на свято"
    ],
    "SIZE_HELP": [
        "зріст",
        "розмір",
        "вік",
        "см",
        "років",
        "рік",
        "міс",
        "скільки",
        "який розмір",
        "підбери",
        "підійде",
    ],
    "COLOR_HELP": [
        # Generic color questions (specific patterns to avoid false positives)
        "який колір",
        "які кольори",
        "інший колір",  # More specific than just "інший"
        "є в кольорі",  # More specific than "є в "
        "колір є",
        # Specific colors (longer stems to avoid false positives)
        "чорний",
        "чорного",
        "чорному",
        "чорним",
        "білий",
        "білого",
        "білому",
        "білим",
        "рожев",  # рожевий, рожевого - safe, no FP
        "синій",
        "синього",
        "синьому",  # NOT "син" - FP with "син" (son)!
        "червон",  # червоний - safe
        "зелен",  # зелений - safe
        "жовт",  # жовтий - safe
        "помаранч",  # помаранчевий - safe
        "сірий",
        "сірого",
        "сірому",  # NOT "сір" - FP with "сір" (cheese)!
        "молоч",  # молочний - safe
        "бордо",  # бордо - safe
        "шоколад",  # шоколадний - safe
        "бежев",  # бежевий - safe
        "малинов",  # малиновий - safe
    ],
    "COMPLAINT": [
        "скарга",
        "проблем",
        "повернен",
        "брак",
        "жалоба",
        "обман",
        "не працює",
        "зламан",
        "погано",
        "відмов",
    ],
    # PHOTO_IDENT - used when has_image=True (user sent photo)
    # Note: This is not matched via keywords, only via has_image flag
    "PHOTO_IDENT": [
        # These are kept for reference but detection is via has_image flag
    ],
    # REQUEST_PHOTO - user asks to see a product photo (no image attached)
    "REQUEST_PHOTO": [
        "покажи фото",
        "можна фото",
        "є фото",
        "скинь фото",
        "фотку",
        "як виглядає",
        "покажіть",
        "хочу побачити",
        "можна подивитись",
    ],
    "DISCOVERY_OR_QUESTION": [
        # NOTE: Clothing types (костюм, сукня, тренч) are now in PRODUCT_CATEGORY
        # which has higher priority. Keep only general discovery keywords here.
        "покаж",
        "є",  # "чи є?"
        "хочу",  # "хочу щось"
        "підбери",
        "порадь",
        "шукаю",
        "ціна",
        "скільки кошт",
    ],
    "GREETING_ONLY": [
        "привіт",
        "вітаю",
        "добр",
        "hello",
        "hi",
        "хай",
    ],
    # Thank you / small talk - end of conversation
    "THANKYOU_SMALLTALK": [
        "дякую",
        "дякуємо",
        "спасибі",
        "дуже вдячна",
        "вдячна",
        "ок",
        "окей",
        "добре",
        "зрозуміло",
        "гарного дня",
        "до побачення",
        "бувайте",
    ],
}
