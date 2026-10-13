"""Tests for the diagnostics dump (phase 5)."""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant

from custom_components.household_budget.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .helpers import COURSES_ID, add_expense_record, courses_subentry, setup_household


async def test_diagnostics_report_statuses_and_hide_personal_details(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass, courses_subentry(owner="person.chloe"))
    await add_expense_record(
        hass,
        entry,
        COURSES_ID,
        20_000,
        date(2025, 10, 1),
        description="Supermarché du coin",
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["currency"] == "EUR"
    assert diagnostics["expense_count"] == 1

    (bucket,) = diagnostics["buckets"]
    assert bucket["period_days"] == 30
    assert bucket["limit_cents"] == 50_000
    assert bucket["expense_count"] == 1
    assert bucket["status"]["spent"] == 20_000
    assert bucket["status"]["remaining"] == 30_000
    assert bucket["status"]["window_start"] == "2025-09-15"
    assert bucket["status"]["next_release_date"] == "2025-10-31"

    # Who shops where stays out of a file people paste into bug reports.
    (expense,) = diagnostics["expenses"]
    assert expense["amount_cents"] == 20_000
    assert expense["description"] == "**REDACTED**"
    assert expense["created_by"] == "**REDACTED**"
    assert bucket["owner"] == "**REDACTED**"
