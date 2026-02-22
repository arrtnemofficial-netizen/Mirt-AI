from pydantic import ValidationError

from src.agents.langgraph.intent.models import IntentResultV1


def test_intent_result_v1_contract_minimal_payload() -> None:
    payload = {
        "primary_intent": "PAYMENT_DELIVERY",
        "confidence": 0.91,
        "secondary_intents": ["REQUEST_PHOTO"],
        "ambiguity": True,
        "features_used": ["kw:оплата", "kw:фото"],
    }

    result = IntentResultV1.model_validate(payload)

    assert result.contract_version == "IntentResultV1"
    assert result.primary_intent == "PAYMENT_DELIVERY"
    assert result.confidence == 0.91
    assert result.secondary_intents == ["REQUEST_PHOTO"]
    assert result.ambiguity is True
    assert result.features_used == ["kw:оплата", "kw:фото"]


def test_intent_result_v1_forbids_unknown_fields() -> None:
    payload = {
        "primary_intent": "DISCOVERY_OR_QUESTION",
        "confidence": 0.8,
        "secondary_intents": [],
        "ambiguity": False,
        "features_used": ["fallback:default"],
        "unexpected": "field",
    }

    try:
        IntentResultV1.model_validate(payload)
        assert False, "ValidationError expected for unknown field"
    except ValidationError as exc:
        assert "extra_forbidden" in str(exc)
