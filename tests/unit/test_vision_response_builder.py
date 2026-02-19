from unittest.mock import patch


def test_build_vision_messages_does_not_repeat_greeting_if_history_has_greeting():
    from src.agents.langgraph.nodes.helpers.vision.response_builder import build_vision_messages
    from src.agents.pydantic.models import ProductMatch, VisionResponse

    prev = [
        {"role": "assistant", "content": "Вітаю 🎀 З вами MIRT_UA, менеджер Софія."},
        {"role": "assistant", "content": "Це наш Тренч екошкіра 💛"},
    ]

    response = VisionResponse(
        reply_to_user="",
        identified_product=ProductMatch(
            id=1,
            name="Тренч екошкіра",
            price=2380.0,
            size=None,
            color="капучіно",
            photo_url="https://cdn.example.com/photo.jpg",
        ),
        confidence=0.95,
        needs_clarification=False,
        clarification_question=None,
    )

    messages = build_vision_messages(
        response=response,
        previous_messages=prev,
        vision_greeted=False,  # simulate bug condition
        user_message="Цена на рост 154",
        catalog_product={"name": "Тренч екошкіра", "price": 2380, "photo_url": "https://cdn.example.com/photo.jpg"},
    )

    all_text = " ".join([m.get("content", "") for m in messages]).lower()
    assert "менеджер соф" not in all_text, "Greeting must not repeat when history already has greeting"


def test_build_vision_messages_handles_broken_history_with_fallback_metric():
    from src.agents.langgraph.nodes.helpers.vision.response_builder import build_vision_messages
    from src.agents.pydantic.models import ProductMatch, VisionResponse

    response = VisionResponse(
        reply_to_user="",
        identified_product=ProductMatch(
            id=1,
            name="Тренч екошкіра",
            price=2380.0,
            size=None,
            color="капучіно",
            photo_url="https://cdn.example.com/photo.jpg",
        ),
        confidence=0.95,
        needs_clarification=False,
        clarification_question=None,
    )

    with (
        patch(
            "src.agents.langgraph.nodes.helpers.vision.response_builder.settings.STRICT_EXCEPTION_POLICY",
            True,
        ),
        patch(
            "src.agents.langgraph.nodes.helpers.vision.response_builder.track_metric"
        ) as metric_mock,
    ):
        messages = build_vision_messages(
            response=response,
            previous_messages=123,  # force history parser type error
            vision_greeted=False,
            user_message="Цена на рост 154",
            catalog_product={
                "name": "Тренч екошкіра",
                "price": 2380,
                "photo_url": "https://cdn.example.com/photo.jpg",
            },
        )

    assert messages
    assert any(
        call.args and call.args[0] == "fallback_triggered"
        for call in metric_mock.call_args_list
    )


