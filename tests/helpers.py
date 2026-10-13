"""Shared helpers for the Household Budget tests."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry, flush_store

from custom_components.household_budget.const import (
    DOMAIN,
    SUBENTRY_TYPE_BUCKET,
    VISIBILITY_SHARED,
)
from custom_components.household_budget.models import Expense

# Fixed ids so tests can address buckets and the seeded store directly.
ENTRY_ID = "household1"
COURSES_ID = "11111111-1111-1111-1111-111111111111"
LUNCH_ID = "22222222-2222-2222-2222-222222222222"

# A timezone with a known offset, so expected dates are unambiguous.
TIME_ZONE = "Europe/Paris"


def bucket_subentry(
    bucket_id: str,
    name: str,
    *,
    period_days: int = 30,
    limit_cents: int = 50_000,
    visibility: str = VISIBILITY_SHARED,
    owner: str | None = None,
    alert_threshold_percent: int | None = None,
    archived: bool = False,
    icon: str | None = None,
) -> ConfigSubentryData:
    """Build a bucket subentry as the config flow would have stored it."""
    return ConfigSubentryData(
        data={
            "icon": icon,
            "color": None,
            "period_days": period_days,
            "limit_cents": limit_cents,
            "visibility": visibility,
            "owner": owner,
            "alert_threshold_percent": alert_threshold_percent,
            "archived": archived,
        },
        subentry_type=SUBENTRY_TYPE_BUCKET,
        title=name,
        unique_id=bucket_id,
    )


def courses_subentry(**kwargs: Any) -> ConfigSubentryData:
    """Courses: shared, 30-day window, 500 EUR."""
    return bucket_subentry(COURSES_ID, "Courses", **kwargs)


def lunch_subentry(**kwargs: Any) -> ConfigSubentryData:
    """Lunch & Snack: 90-day window, 120 EUR."""
    kwargs.setdefault("period_days", 90)
    kwargs.setdefault("limit_cents", 12_000)
    return bucket_subentry(LUNCH_ID, "Lunch & Snack", **kwargs)


async def setup_household(
    hass: HomeAssistant,
    *subentries: ConfigSubentryData,
    currency: str = "EUR",
    entry_id: str = ENTRY_ID,
) -> MockConfigEntry:
    """Set up a household with the given buckets (Courses alone by default)."""
    await hass.config.async_set_time_zone(TIME_ZONE)
    entry = MockConfigEntry(
        domain=DOMAIN,
        entry_id=entry_id,
        title="Our Household",
        data={"name": "Our Household", "currency": currency},
        subentries_data=list(subentries) or [courses_subentry()],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def raw_expense(
    bucket_id: str,
    amount_cents: int,
    expense_date: date,
    *,
    expense_id: str = "exp1",
    description: str | None = None,
) -> dict[str, Any]:
    """An expense as it is persisted, for seeding a store before setup."""
    return {
        "id": expense_id,
        "bucket_id": bucket_id,
        "amount_cents": amount_cents,
        "date": expense_date.isoformat(),
        "created_by": "user1",
        "created_at": "2025-01-01T00:00:00+00:00",
        "updated_at": "2025-01-01T00:00:00+00:00",
        "description": description,
    }


def seed_store(
    hass_storage: dict[str, Any],
    expenses: list[dict[str, Any]],
    *,
    entry_id: str = ENTRY_ID,
) -> None:
    """Pre-populate a household's store, so expenses exist before setup."""
    key = f"{DOMAIN}.{entry_id}"
    hass_storage[key] = {
        "version": 2,
        "minor_version": 1,
        "key": key,
        "data": {"expenses": expenses},
    }


async def add_expense_record(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    bucket_id: str,
    amount_cents: int,
    expense_date: date,
    *,
    expense_id: str | None = None,
    description: str | None = None,
) -> Expense:
    """Write an expense straight to the store, bypassing the action.

    The store is flushed so the expense survives a config entry reload, and
    the coordinator is refreshed so the entities already show it.
    """
    expense = Expense(
        id=expense_id or f"e-{bucket_id}-{expense_date.isoformat()}-{amount_cents}",
        bucket_id=bucket_id,
        amount_cents=amount_cents,
        date=expense_date,
        created_by="user1",
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
        description=description,
    )
    store = entry.runtime_data.store
    store.add_expense(expense)
    await flush_store(store._store)
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()
    return expense


def bucket_device_id(hass: HomeAssistant, bucket_id: str) -> str:
    """Return the HA device id of a bucket — what actions target."""
    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, bucket_id)})
    assert device is not None
    return device.id
