"""Application service for intent detection pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from src.agents.langgraph.intent.models import IntentResultV1


INTENT_PATTERNS: dict[str, list[str]] = {
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
        "чек",
        "квитанці",
    ],
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
        "3",
    ],
    "PRODUCT_CATEGORY": [
        "костюм",
        "костюмчик",
        "комплект",
        "сукн",
        "плаття",
        "платтячко",
        "тренч",
        "куртка",
        "курточка",
        "плащ",
        "штани",
        "штанці",
        "брюки",
        "джогери",
        "блуз",
        "кофт",
        "світшот",
        "худі",
        "одяг",
        "річ",
        "щось на",
    ],
    "SIZE_HELP": [
        "зріст",
        "розмір",
        "вік",
        "см",
        "років",
        "рік",
        "міс",
        "скільки років",
        "скільки см",
        "який розмір",
        "підбери",
        "підійде",
    ],
    "COLOR_HELP": [
        "який колір",
        "які кольори",
        "інший колір",
        "є в кольорі",
        "колір є",
        "чорний",
        "чорного",
        "чорному",
        "чорним",
        "білий",
        "білого",
        "білому",
        "білим",
        "рожев",
        "синій",
        "синього",
        "синьому",
        "червон",
        "зелен",
        "жовт",
        "помаранч",
        "сірий",
        "сірого",
        "сірому",
        "молоч",
        "бордо",
        "шоколад",
        "бежев",
        "малинов",
    ],
    "COMPLAINT": [
        "скарга",
        "проблем",
        "повернен",
        "поверн",
        "брак",
        "жалоба",
        "обман",
        "не працює",
        "зламан",
        "погано",
        "відмов",
    ],
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
        "реальне фото",
        "живе фото",
        "фото вживу",
    ],
    "DISCOVERY_OR_QUESTION": [
        "покаж",
        "є",
        "хочу",
        "підбери",
        "порадь",
        "шукаю",
        "ціна",
        "скільки кошт",
    ],
    "GREETING_ONLY": ["привіт", "вітаю", "добр", "hello", "hi", "хай"],
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
        "ні",
        "не",
        "не хочу",
        "не треба",
        "відміна",
        "відмова",
        "скасувати",
        "no",
        "cancel",
    ],
}

STATE5_EXPLICIT_CANCEL_PATTERNS = ["відміна", "відмов", "скасувати", "не хочу", "не треба", "передум", "cancel"]
PRIORITY_INTENTS = [
    "PAYMENT_DELIVERY",
    "COMPLAINT",
    "SIZE_HELP",
    "COLOR_HELP",
    "REQUEST_PHOTO",
    "PRODUCT_CATEGORY",
]


@dataclass(frozen=True)
class ClassifierSignal:
    intent: str
    features: list[str]


class IntentDetectionService:
    """Prefilter + classifier + calibration + multi-intent policy."""

    def detect(self, *, text: str, has_image: bool, current_state: str) -> IntentResultV1:
        text_lower = (text or "").lower().strip()

        prefiltered = self._prefilter(text_lower=text_lower, has_image=has_image, current_state=current_state)
        if prefiltered:
            return prefiltered

        signals = self._classify(text_lower=text_lower, text_len=len(text or ""))
        return self._apply_multi_intent_policy(signals)

    def _prefilter(self, *, text_lower: str, has_image: bool, current_state: str) -> IntentResultV1 | None:
        if not text_lower and has_image:
            return IntentResultV1(
                primary_intent="PHOTO_IDENT",
                confidence=0.99,
                features_used=["image:empty_text"],
            )

        if current_state == "STATE_4_OFFER":
            for bucket in ("PAYMENT_DELIVERY", "CONFIRMATION", "PRODUCT_NAMES"):
                for keyword in INTENT_PATTERNS[bucket]:
                    if keyword in text_lower:
                        return IntentResultV1(
                            primary_intent="PAYMENT_DELIVERY",
                            confidence=0.97,
                            features_used=[f"prefilter:{bucket}:{keyword}"],
                        )

        if current_state == "STATE_5_PAYMENT_DELIVERY":
            for keyword in INTENT_PATTERNS["COMPLAINT"]:
                if keyword in text_lower:
                    return None

            for keyword in STATE5_EXPLICIT_CANCEL_PATTERNS:
                if keyword in text_lower:
                    return IntentResultV1(
                        primary_intent="THANKYOU_SMALLTALK",
                        confidence=0.96,
                        features_used=[f"prefilter:state5_cancel:{keyword}"],
                    )

            for intent in ("PRODUCT_CATEGORY", "REQUEST_PHOTO"):
                for keyword in INTENT_PATTERNS[intent]:
                    if keyword in text_lower:
                        return IntentResultV1(
                            primary_intent=intent,
                            confidence=0.93,
                            features_used=[f"prefilter:state5_offtopic:{keyword}"],
                        )

            return IntentResultV1(
                primary_intent="PAYMENT_DELIVERY",
                confidence=0.92,
                features_used=["prefilter:state5_default"],
            )

        if has_image:
            for keyword in INTENT_PATTERNS["PAYMENT_DELIVERY"]:
                if keyword in text_lower:
                    return None
            return IntentResultV1(
                primary_intent="PHOTO_IDENT",
                confidence=0.9,
                features_used=["prefilter:image_present"],
            )

        return None

    def _classify(self, *, text_lower: str, text_len: int) -> list[ClassifierSignal]:
        matches: list[ClassifierSignal] = []
        for intent in PRIORITY_INTENTS:
            matched = [k for k in INTENT_PATTERNS[intent] if k in text_lower]
            if matched:
                matches.append(ClassifierSignal(intent=intent, features=[f"kw:{m}" for m in matched]))

        if text_len < 50:
            for intent in ("GREETING_ONLY", "THANKYOU_SMALLTALK"):
                matched = [k for k in INTENT_PATTERNS[intent] if k in text_lower]
                if matched:
                    matches.append(ClassifierSignal(intent=intent, features=[f"kw:{m}" for m in matched]))

        if not matches:
            matched = [k for k in INTENT_PATTERNS["DISCOVERY_OR_QUESTION"] if k in text_lower]
            if matched:
                matches.append(
                    ClassifierSignal(
                        intent="DISCOVERY_OR_QUESTION",
                        features=[f"kw:{m}" for m in matched],
                    )
                )

        if not matches:
            matches.append(ClassifierSignal(intent="DISCOVERY_OR_QUESTION", features=["fallback:default"]))

        return matches

    def _apply_multi_intent_policy(self, signals: list[ClassifierSignal]) -> IntentResultV1:
        primary = signals[0]
        secondary = [s.intent for s in signals[1:] if s.intent != primary.intent]
        all_features: list[str] = []
        for signal in signals:
            all_features.extend(signal.features)

        ambiguity = len(set([s.intent for s in signals])) > 1
        confidence = self._calibrate_confidence(primary_features=primary.features, ambiguity=ambiguity)
        return IntentResultV1(
            primary_intent=primary.intent,
            confidence=confidence,
            secondary_intents=secondary,
            ambiguity=ambiguity,
            features_used=all_features,
        )

    @staticmethod
    def _calibrate_confidence(*, primary_features: list[str], ambiguity: bool) -> float:
        raw = 0.65 + min(len(primary_features), 3) * 0.1
        if ambiguity:
            raw -= 0.2
        return max(0.0, min(1.0, round(raw, 2)))


intent_detection_service = IntentDetectionService()


def detect_intent_legacy(text: str, has_image: bool, current_state: str) -> str:
    """Legacy compatible detector returning only primary intent label."""
    return intent_detection_service.detect(text=text, has_image=has_image, current_state=current_state).primary_intent
