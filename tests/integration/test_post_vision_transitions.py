"""Integration tests for post-vision router transitions."""

from src.agents.langgraph.routers.post_process import route_after_vision
from src.core.state_machine import State


def _base_state() -> dict:
    return {
        "session_id": "vision-route-test",
        "current_state": State.STATE_2_VISION.value,
        "dialog_phase": "WAITING_FOR_SIZE",
        "selected_products": [],
        "offered_products": [],
        "validation_errors": [],
        "last_error": None,
        "metadata": {"session_id": "vision-route-test"},
    }


def test_post_vision_success_routes_to_offer_when_offer_ready() -> None:
    state = _base_state()
    state.update(
        {
            "current_state": State.STATE_4_OFFER.value,
            "dialog_phase": "SIZE_COLOR_DONE",
            "selected_products": [{"name": "Сукня", "price": 1850}],
        }
    )

    assert route_after_vision(state) == "offer"


def test_post_vision_success_routes_to_end_when_not_offer_ready() -> None:
    state = _base_state()
    state.update(
        {
            "current_state": State.STATE_3_SIZE_COLOR.value,
            "dialog_phase": "WAITING_FOR_SIZE",
            "selected_products": [{"name": "Сукня", "price": 1850}],
        }
    )

    assert route_after_vision(state) == "end"


def test_post_vision_error_routes_to_validation() -> None:
    state = _base_state()
    state.update({"last_error": "vision timeout"})

    assert route_after_vision(state) == "validation"
