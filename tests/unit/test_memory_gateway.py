from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.services.memory.models import NewFact
from src.services.memory_gateway import InMemoryMemoryGateway


@pytest.mark.asyncio
async def test_inmemory_gateway_upsert_and_fetch_context_filters_importance() -> None:
    gateway = InMemoryMemoryGateway()

    await gateway.upsert_fact(
        session_id="u-1",
        fact=NewFact(
            content="Клієнт любить синій колір",
            fact_type="preference",
            category="style",
            importance=0.2,
            surprise=0.6,
        ),
        importance=0.2,
        confidence=0.9,
        source="s-1",
    )

    await gateway.upsert_fact(
        session_id="u-1",
        fact=NewFact(
            content="Клієнт з Києва",
            fact_type="logistics",
            category="delivery",
            importance=0.8,
            surprise=0.7,
        ),
        importance=0.8,
        confidence=0.9,
        source="s-1",
    )

    context = await gateway.fetch_context(session_id="u-1", limit=10, min_importance=0.5)

    assert context is not None
    assert len(context.facts) == 1
    assert context.facts[0].content == "Клієнт з Києва"


@pytest.mark.asyncio
async def test_inmemory_gateway_decay_or_cleanup_is_graceful_noop() -> None:
    gateway = InMemoryMemoryGateway()

    result = await gateway.decay_or_cleanup(datetime.now(timezone.utc))

    assert result.ok is True
    assert result.details == "noop"
