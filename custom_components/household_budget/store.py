"""Storage wrapper for the Household Budget integration.

Wraps `homeassistant.helpers.storage.Store` to persist one household's
expenses (one store per config entry, at
`.storage/household_budget.<entry_id>`). Writes are delayed and batched; the
schema version lives in `const.STORAGE_VERSION` and
`_HouseholdBudgetStorage._async_migrate_func` is the single place migrations
are added.

Buckets are not stored here — they live in config subentries.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import date
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_VERSION
from .models import Expense, HouseholdBudgetStoreData

SAVE_DELAY = 10


class _HouseholdBudgetStorage(Store[dict[str, Any]]):
    """`Store` subclass holding the migration function for this schema."""

    async def _async_migrate_func(
        self,
        old_major_version: int,
        old_minor_version: int,
        old_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Migrate stored data to the current schema version."""
        if old_major_version > self.version:
            raise ValueError(
                f"household_budget storage version {old_major_version} is newer "
                f"than the version this integration supports ({self.version})"
            )

        data = old_data
        if old_major_version < 2:
            data = _migrate_v1_to_v2(data)
        return data


def _migrate_v1_to_v2(old_data: dict[str, Any]) -> dict[str, Any]:
    """Drop everything the monthly-rollover model needed.

    Version 1 stored adjustments and a per-bucket budget history, and each
    expense carried the category it was added under. Buckets are now sliding
    windows with a single current limit and expenses point straight at a
    bucket, so only the expenses survive — they already carried `bucket_id`.
    Refunds, which used to be adjustments, are negative expenses now.
    """
    return {
        "expenses": [
            {key: value for key, value in expense.items() if key in _EXPENSE_KEYS}
            for expense in old_data.get("expenses", [])
        ]
    }


_EXPENSE_KEYS = frozenset(
    {
        "id",
        "bucket_id",
        "amount_cents",
        "date",
        "created_by",
        "created_at",
        "updated_at",
        "description",
    }
)


def _expense_to_raw(expense: Expense) -> dict[str, Any]:
    raw = asdict(expense)
    raw["date"] = expense.date.isoformat()
    return raw


def _expense_from_raw(raw: dict[str, Any]) -> Expense:
    return Expense(
        id=raw["id"],
        bucket_id=raw["bucket_id"],
        amount_cents=raw["amount_cents"],
        date=date.fromisoformat(raw["date"]),
        created_by=raw.get("created_by"),
        created_at=raw["created_at"],
        updated_at=raw["updated_at"],
        description=raw.get("description"),
    )


def _serialize(data: HouseholdBudgetStoreData) -> dict[str, Any]:
    return {"expenses": [_expense_to_raw(e) for e in data.expenses]}


def _deserialize(raw: dict[str, Any]) -> HouseholdBudgetStoreData:
    return HouseholdBudgetStoreData(
        expenses=[_expense_from_raw(e) for e in raw.get("expenses", [])]
    )


class HouseholdBudgetStore:
    """Typed access to one household's persisted expenses."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = _HouseholdBudgetStorage(hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
        self.data = HouseholdBudgetStoreData()

    async def async_load(self) -> HouseholdBudgetStoreData:
        """Load persisted data, or start empty if there is none yet."""
        raw = await self._store.async_load()
        self.data = _deserialize(raw) if raw is not None else HouseholdBudgetStoreData()
        return self.data

    @callback
    def async_save_delayed(self) -> None:
        """Queue a batched, delayed write of the current in-memory data.

        `Store` itself guarantees this is flushed on Home Assistant
        shutdown via `EVENT_HOMEASSISTANT_FINAL_WRITE`.
        """
        self._store.async_delay_save(lambda: _serialize(self.data), SAVE_DELAY)

    # -- expenses -------------------------------------------------------

    def add_expense(self, expense: Expense) -> None:
        self.data.expenses.append(expense)
        self.async_save_delayed()

    def get_expense(self, expense_id: str) -> Expense | None:
        return next((e for e in self.data.expenses if e.id == expense_id), None)

    def expenses_for_bucket(self, bucket_id: str) -> list[Expense]:
        return [e for e in self.data.expenses if e.bucket_id == bucket_id]

    def update_expense(self, expense_id: str, **changes: Any) -> Expense:
        existing = self.get_expense(expense_id)
        if existing is None:
            raise KeyError(expense_id)
        index = self.data.expenses.index(existing)
        updated = replace(existing, **changes)
        self.data.expenses[index] = updated
        self.async_save_delayed()
        return updated

    def delete_expense(self, expense_id: str) -> None:
        self.data.expenses = [e for e in self.data.expenses if e.id != expense_id]
        self.async_save_delayed()
