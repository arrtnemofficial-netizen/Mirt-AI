from __future__ import annotations

from src.agents.langgraph.nodes.intent import detect_intent_candidates_from_text


def test_mixed_phrase_thanks_color_payment_priority() -> None:
    result = detect_intent_candidates_from_text(
        text="дякую, але хочу інший колір і куди оплата",
        has_image=False,
        current_state="STATE_1_DISCOVERY",
    )

    assert len(result["intent_candidates"]) >= 3
    assert result["primary_intent"] == "AMBIGUOUS"
    assert result["ambiguous_flag"] is True
    assert result["reason"] == "mixed_intent"
    assert "PAYMENT_DELIVERY" in result["deferred_intents"]
    assert "COLOR_HELP" in result["deferred_intents"]


def test_mixed_phrase_cancel_and_new_dresses() -> None:
    result = detect_intent_candidates_from_text(
        text="скасувати замовлення і покажи нові сукні",
        has_image=False,
        current_state="STATE_1_DISCOVERY",
    )

    assert len(result["intent_candidates"]) >= 3
    assert result["primary_intent"] == "AMBIGUOUS"
    assert result["ambiguous_flag"] is True
    assert result["reason"] == "mixed_intent"
    assert "PAYMENT_DELIVERY" in result["deferred_intents"]
    assert "PRODUCT_CATEGORY" in result["deferred_intents"]


def test_mixed_phrase_paid_receipt_and_add_more_item() -> None:
    result = detect_intent_candidates_from_text(
        text="оплатив, ось чек, ще додай інший товар",
        has_image=False,
        current_state="STATE_5_PAYMENT_DELIVERY",
    )

    assert len(result["intent_candidates"]) >= 3
    assert result["primary_intent"] == "PAYMENT_DELIVERY"
    assert result["deferred_intents"]


def test_chaotic_surzhyk_mixed_intent_routes_to_ambiguous() -> None:
    result = detect_intent_candidates_from_text(
        text="дякую, да я купую но покажи фото пж",
        has_image=False,
        current_state="STATE_1_DISCOVERY",
    )

    assert result["primary_intent"] == "AMBIGUOUS"
    assert result["ambiguous_flag"] is True
    assert result["reason"] == "mixed_intent"
    assert "PAYMENT_DELIVERY" in result["deferred_intents"]
    assert "REQUEST_PHOTO" in result["deferred_intents"]


def test_chaotic_dyakuyu_kupuyu_pokazhy_foto_phrase_is_not_routed_direct_to_payment() -> None:
    result = detect_intent_candidates_from_text(
        text="дякую + купую + покажи фото",
        has_image=False,
        current_state="STATE_1_DISCOVERY",
    )

    assert result["primary_intent"] == "AMBIGUOUS"
    assert result["ambiguous_flag"] is True
    assert result["reason"] == "mixed_intent"
