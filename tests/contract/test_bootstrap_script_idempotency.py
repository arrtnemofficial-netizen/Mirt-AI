"""Contract tests for bootstrap product sync script idempotency."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from scripts.sync_products_master_to_db import ProductRow, _sync_rows


@dataclass
class _FakeDbState:
    products_by_sku: dict[str, ProductRow] = field(default_factory=dict)
    insert_calls: int = 0
    update_calls: int = 0
    schema_calls: int = 0


class _FakeCursor:
    def __init__(self, state: _FakeDbState) -> None:
        self._state = state
        self._selected_rows: list[tuple[str]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params=None) -> None:
        sql = " ".join(query.lower().split())

        if sql.startswith("alter table public.products"):
            self._state.schema_calls += 1
            return

        if sql.startswith("select sku from public.products"):
            self._selected_rows = [(sku,) for sku in self._state.products_by_sku]
            return

        if sql.startswith("insert into public.products"):
            sku = params[7]
            self._state.insert_calls += 1
            self._state.products_by_sku[sku] = ProductRow(
                sku=sku,
                name=params[0],
                category=params[2],
                subcategory=params[3],
                sizes=list(params[4]),
                colors=list(params[5]),
                photo_url=params[6],
                price_by_size={},
                visual_rules={},
                distinction_rules={},
            )
            return

        if sql.startswith("update public.products"):
            sku = params[-1]
            self._state.update_calls += 1
            assert sku in self._state.products_by_sku
            return

        raise AssertionError(f"Unexpected SQL in test: {query}")

    def fetchall(self) -> list[tuple[str]]:
        return self._selected_rows


class _FakeConnection:
    def __init__(self, state: _FakeDbState) -> None:
        self._state = state

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._state)

    def commit(self) -> None:
        return None


@pytest.fixture
def sample_rows() -> list[ProductRow]:
    return [
        ProductRow(
            sku="SKU-001",
            name="Сукня (Рожева)",
            category="dress",
            subcategory="holiday",
            colors=["pink"],
            sizes=["110", "116"],
            photo_url="https://example.test/pink.jpg",
            price_by_size={"110": 1200, "116": 1250},
            visual_rules={},
            distinction_rules={},
        )
    ]


@pytest.mark.contract
def test_repeated_bootstrap_run_does_not_create_product_duplicates(monkeypatch, sample_rows) -> None:
    state = _FakeDbState()

    monkeypatch.setattr("scripts.sync_products_master_to_db._get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr("scripts.sync_products_master_to_db.psycopg.connect", lambda *_args, **_kwargs: _FakeConnection(state))

    _sync_rows(sample_rows, drop_price=False, insert_missing=True)
    _sync_rows(sample_rows, drop_price=False, insert_missing=True)

    assert len(state.products_by_sku) == 1
    assert state.insert_calls == 1
    assert state.update_calls == 1


@pytest.mark.contract
def test_schema_step_is_idempotent_on_repeated_bootstrap_runs(monkeypatch, sample_rows) -> None:
    state = _FakeDbState()

    monkeypatch.setattr("scripts.sync_products_master_to_db._get_database_url", lambda: "postgresql://test")
    monkeypatch.setattr("scripts.sync_products_master_to_db.psycopg.connect", lambda *_args, **_kwargs: _FakeConnection(state))

    _sync_rows(sample_rows, drop_price=True, insert_missing=True)
    _sync_rows(sample_rows, drop_price=True, insert_missing=True)

    # 4 schema SQL statements per run:
    # ADD price_by_size, ADD visual_rules, ADD distinction_rules, DROP price
    assert state.schema_calls == 8
