"""Tests for the bucket limit `number` entity (phase 5)."""

from __future__ import annotations

from datetime import date

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.household_budget.buckets import subentry_for_bucket

from .helpers import (
    COURSES_ID,
    add_expense_record,
    courses_subentry,
    setup_household,
)


async def _set_limit(hass: HomeAssistant, value: float) -> None:
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.courses_limit", "value": value},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_limit_entity_reports_the_bucket_limit(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass)

    state = hass.states.get("number.courses_limit")
    assert state.state == "500.0"
    assert state.attributes["unit_of_measurement"] == "EUR"


async def test_setting_the_limit_updates_the_subentry_and_the_sensors(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))
    assert hass.states.get("sensor.courses_remaining").state == "300.0"

    await _set_limit(hass, 600)

    entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert subentry_for_bucket(entry, COURSES_ID).data["limit_cents"] == 60_000
    assert hass.states.get("number.courses_limit").state == "600.0"
    # The expense is untouched, so only the remaining room grows.
    assert hass.states.get("sensor.courses_spent").state == "200.0"
    assert hass.states.get("sensor.courses_remaining").state == "400.0"


async def test_the_limit_takes_cents(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)

    await _set_limit(hass, 123.45)

    entry = hass.config_entries.async_get_entry(entry.entry_id)
    assert subentry_for_bucket(entry, COURSES_ID).data["limit_cents"] == 12_345


async def test_the_limit_is_a_config_entity(
    hass: HomeAssistant, entity_registry: er.EntityRegistry, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass, courses_subentry())

    entity = entity_registry.async_get("number.courses_limit")
    assert entity.entity_category is EntityCategory.CONFIG
