"""Snapshot-style contract tests for STATE_5 prompt directives."""

from __future__ import annotations

from src.core.prompt_registry import PromptRegistry


_registry = PromptRegistry()
STATE5_KEYS = [
    "STATE_5_PAYMENT_DELIVERY",
    "STATE_5_PAYMENT_DELIVERY_REQUEST",
    "STATE_5_PAYMENT_DELIVERY_CONFIRM",
    "STATE_5_PAYMENT_DELIVERY_PAYMENT",
    "STATE_5_PAYMENT_DELIVERY_THANKS",
]


def _state5_text() -> str:
    return "\n".join(_registry.get(f"state.{key}").content.lower() for key in STATE5_KEYS)


def _contains_without_negation(text: str, phrase: str) -> bool:
    needle = phrase.lower()
    if f"не {needle}" in text:
        return False
    return needle in text


def test_state5_short_ack_patterns_are_marked_as_payment_flow() -> None:
    from src.agents.langgraph.fsm.transition_reducer import _STATE5_SHORT_ACKS

    text = _state5_text()
    cyrillic_alias = {
        "ok": "ок",
        "okay": "ок",
        "okey": "ок",
        "окей": "ок",
        "yes": "так",
        "spasibo": "дякую",
        "спасибі": "дякую",
    }
    for token in _STATE5_SHORT_ACKS:
        token_to_check = cyrillic_alias.get(token.lower(), token.lower())
        assert token_to_check in text, f"STATE_5 prompt contract missing short-ack token: {token}"


def test_state5_finish_only_with_evidence_or_explicit_cancel() -> None:
    text = _state5_text()

    contradiction_phrases = [
        "завершуй діалог без скрін",
        "завершуй діалог без квитанц",
        "закінчувати діалог без скрін",
        "закінчуй діалог без скрін",
    ]

    for phrase in contradiction_phrases:
        assert not _contains_without_negation(text, phrase), (
            f"Contradictory directive found: {phrase}"
        )


def test_state5_cancel_phrase_is_preserved_in_prompt_contract() -> None:
    from src.agents.langgraph.nodes.intent import STATE5_EXPLICIT_CANCEL_PATTERNS

    text = _state5_text()
    documented = [token for token in STATE5_EXPLICIT_CANCEL_PATTERNS if token in text]
    assert documented, "Expected explicit cancel tokens to be present in STATE_5 prompts"


def test_state5_payment_prompts_gate_transitions() -> None:
    # Thanks and proof prompts must be tied to payment proof completion.
    delivery = _registry.get("state.STATE_5_PAYMENT_DELIVERY").content.lower()
    payment = _registry.get("state.STATE_5_PAYMENT_DELIVERY_PAYMENT").content.lower()
    thanks = _registry.get("state.STATE_5_PAYMENT_DELIVERY_THANKS").content.lower()
    confirm = _registry.get("state.STATE_5_PAYMENT_DELIVERY_CONFIRM").content.lower()

    assert "не завершуй діалог" in delivery
    assert "не завершуй діалог" in payment
    assert ("після скріну" in payment) or ("після фото" in payment) or ("скрін" in payment)
    assert ("без скріну" in confirm) or ("без скріншота" in confirm) or ("скрін" in confirm)
    assert "тільки після payment proof" in thanks or "лише після payment proof" in thanks
