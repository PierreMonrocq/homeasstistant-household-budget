"""Tests for the bucket sensors (phase 5).

The important one here is `test_an_expense_frees_itself_at_midnight`: in this
model the figures move on their own as expenses age out, with nobody touching
a record.
"""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from .helpers import (
    COURSES_ID,
    LUNCH_ID,
    add_expense_record,
    bucket_subentry,
    courses_subentry,
    lunch_subentry,
    setup_household,
)


async def test_sensors_report_the_current_window(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    assert hass.states.get("sensor.courses_spent").state == "200.0"
    assert hass.states.get("sensor.courses_remaining").state == "300.0"
    assert hass.states.get("sensor.courses_used").state == "40.0"

    next_release = hass.states.get("sensor.courses_next_release")
    assert dt_util.parse_datetime(next_release.state) == dt_util.start_of_local_day(
        date(2025, 10, 31)
    )


async def test_remaining_carries_the_window_as_attributes(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    attributes = hass.states.get("sensor.courses_remaining").attributes
    assert attributes["window_start"] == "2025-09-15"
    assert attributes["window_end"] == "2025-10-14"
    assert attributes["period_days"] == 30
    assert attributes["next_release_amount"] == 200.0
    assert attributes["visibility"] == "shared"
    assert attributes["owner"] is None
    assert attributes["unit_of_measurement"] == "EUR"
    # The verdict travels with the figures, so a template formats it instead
    # of deciding it again.
    assert attributes["status"] == "ok"
    assert attributes["threshold_percent"] == 80
    assert attributes["released_soon"] == 0.0
    assert attributes["recovery_date"] is None


async def test_remaining_carries_the_warn_verdict(hass: HomeAssistant, freezer) -> None:
    """90 % of the limit warns, and what ages out this week is reported."""
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    # Releases on 16 October: inside the 7-day horizon.
    await add_expense_record(hass, entry, COURSES_ID, 10_000, date(2025, 9, 16))
    await add_expense_record(hass, entry, COURSES_ID, 35_000, date(2025, 10, 10))

    attributes = hass.states.get("sensor.courses_remaining").attributes
    assert hass.states.get("sensor.courses_used").state == "90.0"
    assert attributes["status"] == "warn"
    assert attributes["released_soon"] == 100.0
    assert attributes["recovery_date"] is None


async def test_remaining_carries_the_recovery_date_when_overspent(
    hass: HomeAssistant, freezer
) -> None:
    """An overspent bucket says when ageing alone brings it back under."""
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 55_000, date(2025, 10, 1))

    attributes = hass.states.get("sensor.courses_remaining").attributes
    assert hass.states.get("sensor.courses_remaining").state == "-50.0"
    assert attributes["status"] == "over"
    assert attributes["recovery_date"] == "2025-10-31"


async def test_only_remaining_carries_attributes(hass: HomeAssistant, freezer) -> None:
    """The window belongs to the main sensor; the others stay bare."""
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    for entity_id in ("sensor.courses_spent", "sensor.courses_used"):
        assert "status" not in hass.states.get(entity_id).attributes


async def test_an_expense_frees_itself_at_midnight(hass: HomeAssistant, freezer) -> None:
    """The window moves on its own; no record is touched here."""
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 9, 15))

    assert hass.states.get("sensor.courses_spent").state == "200.0"
    assert hass.states.get("sensor.courses_remaining").state == "300.0"

    # 15 September + 30 days: the expense stops counting today.
    freezer.move_to("2025-10-15 00:00:30+02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert hass.states.get("sensor.courses_spent").state == "0.0"
    assert hass.states.get("sensor.courses_remaining").state == "500.0"


async def test_overspending_shows_a_negative_remaining(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 55_000, date(2025, 10, 1))

    assert hass.states.get("sensor.courses_remaining").state == "-50.0"
    assert hass.states.get("sensor.courses_used").state == "110.0"


async def test_a_refund_gives_back_room(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))
    await add_expense_record(
        hass, entry, COURSES_ID, -5_000, date(2025, 10, 2), expense_id="refund"
    )

    assert hass.states.get("sensor.courses_spent").state == "150.0"
    assert hass.states.get("sensor.courses_remaining").state == "350.0"


async def test_percent_used_is_unknown_without_a_limit(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass, courses_subentry(limit_cents=0))
    await add_expense_record(hass, entry, COURSES_ID, 1_000, date(2025, 10, 1))

    assert hass.states.get("sensor.courses_used").state == "unknown"
    assert hass.states.get("sensor.courses_remaining").state == "-10.0"


async def test_next_release_is_unknown_when_the_window_is_empty(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass)

    assert hass.states.get("sensor.courses_next_release").state == "unknown"
    assert hass.states.get("sensor.courses_remaining").state == "500.0"


async def test_each_bucket_gets_its_own_device_and_sensors(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass, courses_subentry(), lunch_subentry())
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))
    await add_expense_record(hass, entry, LUNCH_ID, 3_000, date(2025, 8, 20))

    assert hass.states.get("sensor.courses_spent").state == "200.0"
    # 20 August is still inside Lunch & Snack's 90-day window.
    assert hass.states.get("sensor.lunch_snack_spent").state == "30.0"
    assert hass.states.get("sensor.lunch_snack_remaining").state == "90.0"


async def test_an_archived_bucket_has_no_entities(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(
        hass,
        courses_subentry(),
        bucket_subentry(LUNCH_ID, "Lunch & Snack", archived=True),
    )

    assert hass.states.get("sensor.courses_remaining") is not None
    assert hass.states.get("sensor.lunch_snack_remaining") is None
    assert hass.states.get("number.lunch_snack_limit") is None


async def test_the_bucket_icon_is_used_for_the_main_sensor(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass, courses_subentry(icon="mdi:cart"))

    assert hass.states.get("sensor.courses_remaining").attributes["icon"] == "mdi:cart"
