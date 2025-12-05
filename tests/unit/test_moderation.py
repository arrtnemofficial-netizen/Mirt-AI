from src.services.moderation import moderate_user_message


def test_detects_and_redacts_pii():
    text = "Напиши на ivan@example.com або +380931112233"
    result = moderate_user_message(text)

    assert result.allowed is True
    assert set(result.flags) == {"email", "phone"}
    assert "[email]" in result.redacted_text
    assert "[phone]" in result.redacted_text


def test_blocks_safety_terms():
    result = moderate_user_message("Це справжня бомба")

    assert result.allowed is False
    assert "safety" in result.flags
    assert result.redacted_text.startswith("[вилучено")
