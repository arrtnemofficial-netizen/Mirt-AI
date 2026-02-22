"""Static SSOT guard: business keyword rules must live in intent node, not router."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROUTER_PATH = Path("src/agents/langgraph/routers/intent.py")
INTENT_NODE_PATH = Path("src/agents/langgraph/nodes/intent.py")

# Business phrases intentionally owned by intent detection layer.
SENSITIVE_BUSINESS_PHRASES = {
    "відміна",
    "скасувати",
    "не хочу",
    "не треба",
    "передум",
    "cancel",
    "купую",
    "беру",
    "оплата",
    "доставк",
    "нова пошта",
}

# Router is allowed to reason only with intent/state-level symbols.
ALLOWED_ROUTER_LITERALS = {
    "ESCALATION",
    "COMPLAINT",
    "AMBIGUOUS",
    "GREETING_ONLY",
    "THANKYOU_SMALLTALK",
    "PHOTO_IDENT",
    "PAYMENT_DELIVERY",
    "CONFIRMATION",
    "SIZE_HELP",
    "COLOR_HELP",
    "STATE_4_OFFER",
    "STATE_5_PAYMENT_DELIVERY",
}


@pytest.mark.smoke
def test_business_phrases_do_not_leak_from_intent_node_to_router() -> None:
    router_tree = ast.parse(ROUTER_PATH.read_text(encoding="utf-8"))
    router_strings = {
        node.value.strip().lower()
        for node in ast.walk(router_tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    leaked = sorted(phrase for phrase in SENSITIVE_BUSINESS_PHRASES if phrase in router_strings)
    assert not leaked, f"Router містить бізнес-фрази (мають бути тільки в intent-node): {leaked}"


@pytest.mark.smoke
def test_router_uses_only_intent_or_state_symbols() -> None:
    router_tree = ast.parse(ROUTER_PATH.read_text(encoding="utf-8"))
    literal_candidates = {
        node.value
        for node in ast.walk(router_tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.isupper()
        and "_" in node.value
    }

    unexpected = sorted(literal_candidates - ALLOWED_ROUTER_LITERALS)
    assert not unexpected, f"Router має неочікувані символьні правила: {unexpected}"


@pytest.mark.smoke
def test_sensitive_phrases_are_defined_in_intent_node() -> None:
    source = INTENT_NODE_PATH.read_text(encoding="utf-8")
    missing = sorted(phrase for phrase in SENSITIVE_BUSINESS_PHRASES if phrase not in source)
    assert not missing, f"Intent-node втратив обов'язкові бізнес-фрази: {missing}"
