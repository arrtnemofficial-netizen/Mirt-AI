import asyncio
import pytest

from src.core.models import AgentResponse, Metadata, Message, Product
from src.services.graph import build_graph


def test_graph_updates_state_and_messages():
    async def _run():
        async def fake_runner(messages, metadata):  # noqa: ANN001
            return AgentResponse(
                event="offer",
                messages=[Message(content="Привіт!")],
                products=[
                    Product(
                        product_id=1,
                        name="Сукня",
                        size="122",
                        color="червоний",
                        price=100,
                        photo_url="x",
                    )
                ],
                metadata=Metadata(current_state="STATE4_OFFER"),
            )

        graph = build_graph(runner=fake_runner)

        state = {
            "messages": [{"role": "user", "content": "Хочу сукню"}],
            "metadata": {},
            "current_state": "STATE1_DISCOVERY",
        }

        result = await graph.ainvoke(state)

        assert result["current_state"] == "STATE4_OFFER"
        assert result["messages"][-1]["role"] == "assistant"

    asyncio.run(_run())


def test_graph_short_circuits_on_moderation_block():
    async def _run():
        runner_called = False

        async def fake_runner(messages, metadata):  # noqa: ANN001
            nonlocal runner_called
            runner_called = True
            return AgentResponse(
                event="simple_answer",
                messages=[Message(content="ok")],
                products=[],
                metadata=Metadata(current_state="STATE1_DISCOVERY"),
            )

        graph = build_graph(runner=fake_runner)

        state = {
            "messages": [{"role": "user", "content": "Це бомба"}],
            "metadata": {},
            "current_state": "STATE1_DISCOVERY",
        }

        result = await graph.ainvoke(state)

        assert result["current_state"] == "STATE1_DISCOVERY"
        assert result["messages"][-1]["role"] == "assistant"
        assert result["metadata"]["event_trigger"] == "moderation_block"
        assert result["metadata"].get("moderation_flags")
        assert runner_called is False

    asyncio.run(_run())
