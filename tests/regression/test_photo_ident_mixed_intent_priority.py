"""Regression tests for PHOTO_IDENT behavior in mixed-intent policy."""

from __future__ import annotations

from src.agents.langgraph.intent.policy import select_intents


def test_photo_ident_plus_payment_delivery_prefers_payment() -> None:
    selection = select_intents(["PHOTO_IDENT", "PAYMENT_DELIVERY"])

    assert selection.primary_intent == "PAYMENT_DELIVERY"
    assert selection.deferred_intents == ["PHOTO_IDENT"]


def test_photo_ident_plus_complaint_prefers_complaint() -> None:
    selection = select_intents(["PHOTO_IDENT", "COMPLAINT"])

    assert selection.primary_intent == "COMPLAINT"
    assert selection.deferred_intents == ["PHOTO_IDENT"]


def test_photo_ident_plus_offer_prefers_vision() -> None:
    selection = select_intents(["PHOTO_IDENT", "PRODUCT_CATEGORY"])

    assert selection.primary_intent == "PHOTO_IDENT"
    assert selection.deferred_intents == ["PRODUCT_CATEGORY"]
