from src.agents.langgraph.nodes.intent import detect_intent_from_text


def test_mixed_payment_and_category_message_is_ambiguous() -> None:
    result = detect_intent_from_text(
        text="Хочу купити, але ще покажіть які є сукні",
        has_image=False,
        current_state="STATE_1_DISCOVERY",
    )

    assert result.primary_intent == "AMBIGUOUS"
    assert result.ambiguity_reason == "conflicting_patterns"
    assert "PAYMENT_DELIVERY" in result.secondary_intents
    assert "PRODUCT_CATEGORY" in result.secondary_intents


def test_low_confidence_message_is_ambiguous() -> None:
    result = detect_intent_from_text(
        text="так є",
        has_image=False,
        current_state="STATE_1_DISCOVERY",
    )

    assert result.primary_intent == "AMBIGUOUS"
    assert result.ambiguity_reason == "low_confidence"
    assert result.confidence < 0.55


def test_structured_result_for_clear_intent() -> None:
    result = detect_intent_from_text(
        text="підкажіть розмір",
        has_image=False,
        current_state="STATE_1_DISCOVERY",
    )

    assert result.primary_intent == "SIZE_HELP"
    assert result.confidence > 0.55
    assert result.ambiguity_reason is None
