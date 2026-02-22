"""Intent policy: priority resolution for mixed-intent user messages.

Canonical source of truth for mixed-intent priority is
docs/architecture/FSM_TRANSITION_TABLE.md.
Router layer must consume `primary_intent` and avoid duplicating this policy.
"""

from __future__ import annotations

from dataclasses import dataclass

PRIORITY_TABLE: dict[str, int] = {
    "safety/escalation": 0,
    "payment-critical": 1,
    "complaint": 2,
    "vision": 3,
    "offer": 4,
    "discovery": 5,
    "smalltalk": 6,
    "other": 7,
}

INTENT_TO_BUCKET: dict[str, str] = {
    "ESCALATION": "safety/escalation",
    "PAYMENT_DELIVERY": "payment-critical",
    "COMPLAINT": "complaint",
    "CONFIRMATION": "offer",
    "PRODUCT_NAMES": "offer",
    "SIZE_HELP": "offer",
    "COLOR_HELP": "offer",
    "REQUEST_PHOTO": "offer",
    "PRODUCT_CATEGORY": "offer",
    "PHOTO_IDENT": "vision",
    "DISCOVERY_OR_QUESTION": "discovery",
    "GREETING_ONLY": "smalltalk",
    "THANKYOU_SMALLTALK": "smalltalk",
}


@dataclass(frozen=True)
class IntentSelection:
    primary_intent: str
    deferred_intents: list[str]


def get_intent_bucket(intent: str) -> str:
    return INTENT_TO_BUCKET.get(intent, "other")


def sort_intents_by_policy(candidates: list[str]) -> list[str]:
    """Sort intent candidates by configured business priority (stable for ties)."""
    deduped: list[str] = []
    seen: set[str] = set()
    for intent in candidates:
        if intent not in seen:
            deduped.append(intent)
            seen.add(intent)

    return sorted(
        deduped,
        key=lambda intent: (PRIORITY_TABLE[get_intent_bucket(intent)], deduped.index(intent)),
    )


def select_intents(candidates: list[str], fallback_intent: str = "DISCOVERY_OR_QUESTION") -> IntentSelection:
    ordered = sort_intents_by_policy(candidates)
    if not ordered:
        return IntentSelection(primary_intent=fallback_intent, deferred_intents=[])
    return IntentSelection(primary_intent=ordered[0], deferred_intents=ordered[1:])
