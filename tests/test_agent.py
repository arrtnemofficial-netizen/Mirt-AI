import asyncio

import pytest

from src.core.models import AgentResponse, Metadata, Message, Product
from src.services.agent import AgentRunner, DummyAgent
from src.services.catalog import CatalogService
from src.services.metadata import apply_metadata_defaults


def build_dummy_response(state: str = "STATE4_OFFER") -> AgentResponse:
    return AgentResponse(
        event="offer",
        messages=[Message(content="Ось що знайшла")],
        products=[
            Product(
                product_id=123,
                name="Тестовий товар",
                size="122",
                color="червоний",
                price=100.0,
                photo_url="https://example.com/1.jpg",
                category="dress",
            )
        ],
        metadata=Metadata(current_state=state),
    )


@pytest.fixture()
def catalog(tmp_path):
    sample = tmp_path / "catalog.json"
    sample.write_text(
        """
[
  {"product_id": 1, "name": "Сукня святкова", "size": "122", "color": "червоний", "price": 100, "photo_url": "x", "category": "dress"}
]
""",
        encoding="utf-8",
    )
    return CatalogService(path=sample)


def test_agent_runner_forwards_metadata_and_returns_response(catalog):
    async def _run():
        response = build_dummy_response()
        captures = []
        dummy = DummyAgent(response, capture=captures)
        runner = AgentRunner(agent=dummy, catalog=catalog)

        history = [{"role": "user", "content": "Шукаю сукню"}]
        metadata = {"session_id": "abc", "current_state": "STATE1_DISCOVERY"}

        result = await runner.run(history, metadata)

        assert result.event == "offer"
        assert captures, "Agent.run should be called"

        sent_settings = captures[0].kwargs["model_settings"]["extra_body"]
        assert sent_settings["metadata"]["session_id"] == "abc"
        assert sent_settings["metadata"]["current_state"] == "STATE1_DISCOVERY"

    asyncio.run(_run())


def test_default_metadata_populates_basics():
    meta = apply_metadata_defaults({"session_id": "abc"}, current_state="STATE2_VISION")
    assert meta["session_id"] == "abc"
    assert meta["current_state"] == "STATE2_VISION"
    assert meta["event_trigger"] == ""
