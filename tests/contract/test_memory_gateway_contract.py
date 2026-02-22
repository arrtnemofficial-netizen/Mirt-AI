"""Contract tests for memory gateway interface and memory record invariants."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from src.services.memory import MemoryService
from src.services.memory.models import NewFact


@pytest.mark.contract
def test_memory_gateway_exposes_required_async_interface() -> None:
    required_methods = {
        "load_memory_context",
        "store_fact",
        "update_fact",
        "get_facts",
        "deactivate_fact",
        "get_or_create_profile",
        "update_profile",
    }

    for method_name in required_methods:
        method = getattr(MemoryService, method_name, None)
        assert callable(method), f"Missing gateway method: {method_name}"
        assert inspect.iscoroutinefunction(method), f"Method must be async: {method_name}"


@pytest.mark.contract
@pytest.mark.parametrize(
    "missing_field",
    ["content", "fact_type", "category", "importance", "surprise"],
)
def test_new_fact_requires_mandatory_memory_record_fields(missing_field: str) -> None:
    payload = {
        "content": "Клієнт любить зелений колір",
        "fact_type": "preference",
        "category": "style",
        "importance": 0.8,
        "surprise": 0.6,
    }
    payload.pop(missing_field)

    with pytest.raises(ValidationError):
        NewFact(**payload)


@pytest.mark.contract
@pytest.mark.parametrize("value", [0.0, 1.0, 0.42])
def test_new_fact_metric_invariants_accept_values_in_closed_unit_interval(value: float) -> None:
    fact = NewFact(
        content="Тест",
        fact_type="preference",
        category="general",
        importance=value,
        surprise=value,
    )

    assert fact.importance == round(value, 2)
    assert fact.surprise == round(value, 2)


@pytest.mark.contract
@pytest.mark.parametrize("invalid_value", [-0.01, 1.01])
def test_new_fact_metric_invariants_reject_values_outside_unit_interval(invalid_value: float) -> None:
    with pytest.raises(ValidationError):
        NewFact(
            content="Тест",
            fact_type="preference",
            category="general",
            importance=invalid_value,
            surprise=0.5,
        )

    with pytest.raises(ValidationError):
        NewFact(
            content="Тест",
            fact_type="preference",
            category="general",
            importance=0.5,
            surprise=invalid_value,
        )
