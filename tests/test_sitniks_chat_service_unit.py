import pytest


@pytest.mark.asyncio
async def test_sitniks_handle_first_touch_uses_status_from_settings(
    monkeypatch: pytest.MonkeyPatch,
    reset_sitniks_singleton,
):
    from src.conf.config import settings
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

    # Force "enabled"
    monkeypatch.setattr(settings, "SNITKIX_API_URL", "https://crm.sitniks.com", raising=False)
    monkeypatch.setattr(settings, "SNITKIX_API_KEY", type("S", (), {"get_secret_value": lambda self: "k"})(), raising=False)
    monkeypatch.setattr(settings, "SITNIKS_AI_MANAGER_ID", 111, raising=False)
    monkeypatch.setattr(settings, "SITNIKS_STATUS_FIRST_TOUCH", "Взято в роботу", raising=False)

    service = get_sitniks_chat_service()

    async def _find_chat(**kwargs) -> str:
        return "chat-1"
    
    async def _save_mapping(**kwargs) -> None:
        pass
    
    monkeypatch.setattr(service, "find_chat_by_username", _find_chat)
    monkeypatch.setattr(service, "_save_chat_mapping", _save_mapping)

    seen = {}

    async def _update(chat_id: str, status: str) -> bool:
        seen["chat_id"] = chat_id
        seen["status"] = status
        return True

    async def _assign(chat_id: str, manager_id: int) -> bool:
        seen["assigned"] = (chat_id, manager_id)
        return True

    monkeypatch.setattr(service, "update_chat_status", _update)
    monkeypatch.setattr(service, "assign_manager", _assign)

    result = await service.handle_first_touch(user_id="u1", instagram_username="nick")
    assert result["success"] is True
    assert seen["status"] == "Взято в роботу"
    assert seen["assigned"] == ("chat-1", 111)


@pytest.mark.asyncio
async def test_sitniks_handle_invoice_sent_uses_status_from_settings(
    monkeypatch: pytest.MonkeyPatch,
    reset_sitniks_singleton,
):
    from src.conf.config import settings
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

    monkeypatch.setattr(settings, "SNITKIX_API_URL", "https://crm.sitniks.com", raising=False)
    monkeypatch.setattr(settings, "SNITKIX_API_KEY", type("S", (), {"get_secret_value": lambda self: "k"})(), raising=False)
    monkeypatch.setattr(settings, "SITNIKS_STATUS_INVOICE_SENT", "Виставлено рахунок", raising=False)

    service = get_sitniks_chat_service()
    
    async def _get_chat_id(_uid: str) -> str:
        return "chat-2"
    
    monkeypatch.setattr(service, "_get_chat_id_for_user", _get_chat_id)

    seen = {}

    async def _update(chat_id: str, status: str) -> bool:
        seen["chat_id"] = chat_id
        seen["status"] = status
        return True

    monkeypatch.setattr(service, "update_chat_status", _update)

    ok = await service.handle_invoice_sent("u2")
    assert ok is True
    assert seen["chat_id"] == "chat-2"
    assert seen["status"] == "Виставлено рахунок"


@pytest.mark.asyncio
async def test_sitniks_handle_give_requisites_is_alias_for_invoice_sent(
    monkeypatch: pytest.MonkeyPatch,
    reset_sitniks_singleton,
):
    from src.conf.config import settings
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

    monkeypatch.setattr(settings, "SNITKIX_API_URL", "https://crm.sitniks.com", raising=False)
    monkeypatch.setattr(settings, "SNITKIX_API_KEY", type("S", (), {"get_secret_value": lambda self: "k"})(), raising=False)

    service = get_sitniks_chat_service()

    called = {"n": 0}

    async def _invoice(uid: str) -> bool:
        called["n"] += 1
        return True

    monkeypatch.setattr(service, "handle_invoice_sent", _invoice)
    ok = await service.handle_give_requisites("u3")
    assert ok is True
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_sitniks_handle_escalation_uses_status_from_settings(
    monkeypatch: pytest.MonkeyPatch,
    reset_sitniks_singleton,
):
    from src.conf.config import settings
    from src.integrations.crm.sitniks_chat_service import get_sitniks_chat_service

    monkeypatch.setattr(settings, "SNITKIX_API_URL", "https://crm.sitniks.com", raising=False)
    monkeypatch.setattr(settings, "SNITKIX_API_KEY", type("S", (), {"get_secret_value": lambda self: "k"})(), raising=False)
    monkeypatch.setattr(settings, "SITNIKS_STATUS_AI_ATTENTION", "AI Увага", raising=False)
    monkeypatch.setattr(settings, "SITNIKS_HUMAN_MANAGER_ID", 222, raising=False)

    service = get_sitniks_chat_service()
    
    async def _get_chat_id(_uid: str) -> str:
        return "chat-3"
    
    monkeypatch.setattr(service, "_get_chat_id_for_user", _get_chat_id)

    seen = {}

    async def _update(chat_id: str, status: str) -> bool:
        seen["status"] = status
        return True

    async def _assign(chat_id: str, manager_id: int) -> bool:
        seen["assigned"] = manager_id
        return True

    monkeypatch.setattr(service, "update_chat_status", _update)
    monkeypatch.setattr(service, "assign_manager", _assign)

    result = await service.handle_escalation("u4")
    assert result["status_set"] is True
    assert seen["status"] == "AI Увага"
    assert seen["assigned"] == 222


