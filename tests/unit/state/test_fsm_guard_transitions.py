from src.core.state_machine import Intent, State, is_transition_allowed


def test_transition_allowed_with_intent():
    assert is_transition_allowed(
        from_state=State.STATE_0_INIT,
        to_state=State.STATE_2_VISION,
        intent=Intent.PHOTO_IDENT,
    )


def test_transition_blocked_with_wrong_intent():
    assert (
        is_transition_allowed(
            from_state=State.STATE_0_INIT,
            to_state=State.STATE_5_PAYMENT_DELIVERY,
            intent=Intent.GREETING_ONLY,
        )
        is False
    )


def test_transition_allowed_with_phase_mapping():
    assert is_transition_allowed(
        from_state=State.STATE_4_OFFER,
        to_state=State.STATE_4_OFFER,
        intent=Intent.UNKNOWN_OR_EMPTY,
        dialog_phase="OFFER_MADE",
    )
