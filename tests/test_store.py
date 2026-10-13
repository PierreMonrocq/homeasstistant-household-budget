"""Tests for the Store wrapper: round trip, delayed save, v1 -> v2 migration."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import flush_store

from custom_components.household_budget.const import DOMAIN, STORAGE_VERSION
from custom_components.household_budget.models import Expense
from custom_components.household_budget.store import (
    HouseholdBudgetStore,
    _HouseholdBudgetStorage,
)

ENTRY_ID = "entry1"
STORAGE_KEY = f"{DOMAIN}.{ENTRY_ID}"


def make_expense(expense_id: str = "exp1", **overrides) -> Expense:
    defaults = dict(
        id=expense_id,
        bucket_id="bucket1",
        amount_cents=1_000,
        date=date(2025, 10, 5),
        created_by="user1",
        created_at="2025-10-05T12:00:00+00:00",
        updated_at="2025-10-05T12:00:00+00:00",
        description="Supermarket",
    )
    defaults.update(overrides)
    return Expense(**defaults)


async def test_load_with_no_existing_data_starts_empty(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    store = HouseholdBudgetStore(hass, ENTRY_ID)
    data = await store.async_load()

    assert data.expenses == []


async def test_round_trip_persists_expenses(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    store = HouseholdBudgetStore(hass, ENTRY_ID)
    await store.async_load()

    store.add_expense(make_expense())
    store.add_expense(make_expense("exp2", amount_cents=-500, description="Refund"))
    await flush_store(store._store)

    assert STORAGE_KEY in hass_storage
    assert hass_storage[STORAGE_KEY]["version"] == STORAGE_VERSION

    reloaded_store = HouseholdBudgetStore(hass, ENTRY_ID)
    data = await reloaded_store.async_load()

    assert data.expenses == [
        make_expense(),
        make_expense("exp2", amount_cents=-500, description="Refund"),
    ]


async def test_save_is_delayed_until_flushed(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    store = HouseholdBudgetStore(hass, ENTRY_ID)
    await store.async_load()

    store.add_expense(make_expense())
    assert STORAGE_KEY not in hass_storage

    await flush_store(store._store)
    assert STORAGE_KEY in hass_storage
    assert len(hass_storage[STORAGE_KEY]["data"]["expenses"]) == 1


async def test_update_and_delete_expense(hass: HomeAssistant, hass_storage: dict[str, Any]) -> None:
    store = HouseholdBudgetStore(hass, ENTRY_ID)
    await store.async_load()
    store.add_expense(make_expense())

    updated = store.update_expense("exp1", amount_cents=2_000)
    assert updated.amount_cents == 2_000
    assert store.get_expense("exp1").amount_cents == 2_000

    store.delete_expense("exp1")
    assert store.get_expense("exp1") is None

    await flush_store(store._store)


async def test_update_missing_expense_raises(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    store = HouseholdBudgetStore(hass, ENTRY_ID)
    await store.async_load()

    with pytest.raises(KeyError):
        store.update_expense("does-not-exist", amount_cents=1)


async def test_expenses_for_bucket_filters_by_bucket(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    store = HouseholdBudgetStore(hass, ENTRY_ID)
    await store.async_load()
    store.add_expense(make_expense("exp1", bucket_id="courses"))
    store.add_expense(make_expense("exp2", bucket_id="lunch"))

    assert [e.id for e in store.expenses_for_bucket("courses")] == ["exp1"]


# --- Migration ---------------------------------------------------------------


async def test_migrate_v1_keeps_expenses_and_drops_the_rollover_model(
    hass: HomeAssistant,
) -> None:
    storage = _HouseholdBudgetStorage(hass, STORAGE_VERSION, STORAGE_KEY)
    v1_data = {
        "expenses": [
            {
                "id": "exp1",
                "amount_cents": 1_000,
                "date": "2025-10-05",
                "category_id": "cat1",
                "category_name": "Groceries",
                "bucket_id": "bucket1",
                "created_by": "user1",
                "created_at": "2025-10-05T12:00:00+00:00",
                "updated_at": "2025-10-05T12:00:00+00:00",
                "description": "Supermarket",
            }
        ],
        "adjustments": [
            {
                "id": "adj1",
                "bucket_id": "bucket1",
                "date": "2025-10-10",
                "amount_cents": 500,
                "created_by": "user1",
                "created_at": "2025-10-10T12:00:00+00:00",
                "reason": "Refund",
            }
        ],
        "budget_history": {
            "bucket1": [{"effective_from_period_start": "2025-10-01", "amount_cents": 30_000}]
        },
    }

    migrated = await storage._async_migrate_func(1, 0, v1_data)

    assert set(migrated) == {"expenses"}
    assert migrated["expenses"] == [
        {
            "id": "exp1",
            "amount_cents": 1_000,
            "date": "2025-10-05",
            "bucket_id": "bucket1",
            "created_by": "user1",
            "created_at": "2025-10-05T12:00:00+00:00",
            "updated_at": "2025-10-05T12:00:00+00:00",
            "description": "Supermarket",
        }
    ]


async def test_migrated_v1_data_deserializes(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A real v1 store on disk loads through the migration into the new model."""
    hass_storage[STORAGE_KEY] = {
        "version": 1,
        "minor_version": 1,
        "key": STORAGE_KEY,
        "data": {
            "expenses": [
                {
                    "id": "exp1",
                    "amount_cents": 1_000,
                    "date": "2025-10-05",
                    "category_id": "cat1",
                    "category_name": "Groceries",
                    "bucket_id": "bucket1",
                    "created_by": "user1",
                    "created_at": "2025-10-05T12:00:00+00:00",
                    "updated_at": "2025-10-05T12:00:00+00:00",
                    "description": "Supermarket",
                }
            ],
            "adjustments": [],
            "budget_history": {},
        },
    }

    store = HouseholdBudgetStore(hass, ENTRY_ID)
    data = await store.async_load()

    assert data.expenses == [make_expense()]


async def test_migrate_func_is_noop_for_current_version(hass: HomeAssistant) -> None:
    storage = _HouseholdBudgetStorage(hass, STORAGE_VERSION, STORAGE_KEY)
    current_data = {"expenses": []}

    migrated = await storage._async_migrate_func(STORAGE_VERSION, 0, current_data)

    assert migrated == current_data


async def test_migrate_func_rejects_future_version(hass: HomeAssistant) -> None:
    storage = _HouseholdBudgetStorage(hass, STORAGE_VERSION, STORAGE_KEY)

    with pytest.raises(ValueError):
        await storage._async_migrate_func(STORAGE_VERSION + 1, 1, {})
