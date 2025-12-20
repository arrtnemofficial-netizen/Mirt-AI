from src.core.state_machine import DIALOG_PHASE_TO_STATE, State, expected_state_for_phase


def test_phase_to_state_mapping_is_valid():
    states = {s.value for s in State}
    for phase, state in DIALOG_PHASE_TO_STATE.items():
        assert state.value in states, f"Invalid state for phase {phase}: {state}"


def test_phase_to_state_mapping_key_phases():
    assert expected_state_for_phase("WAITING_FOR_SIZE") == State.STATE_3_SIZE_COLOR
    assert expected_state_for_phase("WAITING_FOR_COLOR") == State.STATE_3_SIZE_COLOR
    assert expected_state_for_phase("OFFER_MADE") == State.STATE_4_OFFER
