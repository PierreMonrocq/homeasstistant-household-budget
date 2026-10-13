"""Tests for the integration's events (phase 5).

The threshold and overspent events are edge-triggered: they fire on the
crossing, re-arm when the bucket comes back under, and stay quiet at startup
for a bucket that is already over.
"""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.household_budget.const import (
    DOMAIN,
    EVENT_EXPENSE_ADDED,
    EVENT_EXPENSE_DELETED,
    EVENT_EXPENSE_EDITED,
    EVENT_OVERSPENT,
    EVENT_THRESHOLD_CROSSED,
    SERVICE_ADD_EXPENSE,
    SERVICE_DELETE_EXPENSE,
    SERVICE_EDIT_EXPENSE,
)

from .helpers import (
    COURSES_ID,
    ENTRY_ID,
    add_expense_record,
    bucket_device_id,
    courses_subentry,
    raw_expense,
    seed_store,
    setup_household,
)


async def test_expense_lifecycle_events(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    added = async_capture_events(hass, EVENT_EXPENSE_ADDED)
    edited = async_capture_events(hass, EVENT_EXPENSE_EDITED)
    deleted = async_capture_events(hass, EVENT_EXPENSE_DELETED)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        {"device_id": bucket_device_id(hass, COURSES_ID), "amount": 120},
        blocking=True,
        return_response=True,
    )
    await hass.async_block_till_done()
    expense_id = response["expense_id"]

    assert len(added) == 1
    assert added[0].data == {
        "entry_id": entry.entry_id,
        "bucket_id": COURSES_ID,
        "expense_id": expense_id,
        "amount": 120.0,
        "amount_cents": 12_000,
        "date": "2025-10-14",
    }

    await hass.services.async_call(
        DOMAIN, SERVICE_EDIT_EXPENSE, {"expense_id": expense_id, "amount": 90}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(edited) == 1
    assert edited[0].data["amount"] == 90.0

    await hass.services.async_call(
        DOMAIN, SERVICE_DELETE_EXPENSE, {"expense_id": expense_id}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(deleted) == 1
    assert deleted[0].data["expense_id"] == expense_id


async def test_overspent_fires_once_on_the_crossing_then_re_arms(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    events = async_capture_events(hass, EVENT_OVERSPENT)

    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))
    assert events == []

    # Crossing into the red.
    overspending = await add_expense_record(
        hass, entry, COURSES_ID, 40_000, date(2025, 10, 2), expense_id="over"
    )
    assert len(events) == 1
    assert events[0].data["bucket_id"] == COURSES_ID
    assert events[0].data["bucket_name"] == "Courses"
    assert events[0].data["remaining"] == -100.0

    # Still in the red: no second announcement.
    await add_expense_record(hass, entry, COURSES_ID, 1_000, date(2025, 10, 3), expense_id="more")
    assert len(events) == 1

    # Back under the limit, then over again: the event re-arms.
    await hass.services.async_call(
        DOMAIN, SERVICE_DELETE_EXPENSE, {"expense_id": overspending.id}, blocking=True
    )
    await hass.async_block_till_done()
    assert len(events) == 1

    await add_expense_record(hass, entry, COURSES_ID, 40_000, date(2025, 10, 4), expense_id="again")
    assert len(events) == 2


async def test_threshold_crossed_fires_at_the_configured_percentage(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass, courses_subentry(alert_threshold_percent=90))
    events = async_capture_events(hass, EVENT_THRESHOLD_CROSSED)

    await add_expense_record(hass, entry, COURSES_ID, 40_000, date(2025, 10, 1))
    assert events == []

    await add_expense_record(
        hass, entry, COURSES_ID, 5_500, date(2025, 10, 2), expense_id="tips_it"
    )
    assert len(events) == 1
    assert events[0].data["threshold"] == 90
    assert events[0].data["percent_used"] == 91.0


async def test_a_bucket_without_a_threshold_warns_at_the_default(
    hass: HomeAssistant, freezer
) -> None:
    """The panel paints "À surveiller" from the same classification.

    A bucket with no threshold of its own would otherwise look alarming in
    the panel while firing nothing, so the default applies to both.
    """
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    events = async_capture_events(hass, EVENT_THRESHOLD_CROSSED)

    # Half the limit: comfortably under the 80 % default.
    await add_expense_record(hass, entry, COURSES_ID, 25_000, date(2025, 10, 1))
    assert events == []

    await add_expense_record(
        hass, entry, COURSES_ID, 24_900, date(2025, 10, 2), expense_id="tips_it"
    )
    assert len(events) == 1
    assert events[0].data["threshold"] == 80


async def test_startup_does_not_replay_alerts_for_an_overspent_bucket(
    hass: HomeAssistant, hass_storage: dict, freezer
) -> None:
    """Restarting Home Assistant must not re-announce what is already over."""
    freezer.move_to("2025-10-14 12:00:00+02:00")
    seed_store(
        hass_storage,
        [raw_expense(COURSES_ID, 60_000, date(2025, 10, 1), expense_id="seeded")],
    )
    overspent = async_capture_events(hass, EVENT_OVERSPENT)
    threshold = async_capture_events(hass, EVENT_THRESHOLD_CROSSED)

    await setup_household(hass, courses_subentry(alert_threshold_percent=90), entry_id=ENTRY_ID)

    assert hass.states.get("sensor.courses_remaining").state == "-100.0"
    assert overspent == []
    assert threshold == []
