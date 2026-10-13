"""Tests for the actions (phase 5).

The one that matters most is
`test_add_expense_on_a_device_creates_exactly_one_expense`: a bucket's device
holds five entities, so without deduplication a single call would record five
expenses.
"""

from __future__ import annotations

from datetime import date

from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
import voluptuous as vol

from custom_components.household_budget.const import (
    DOMAIN,
    SERVICE_ADD_EXPENSE,
    SERVICE_DELETE_EXPENSE,
    SERVICE_EDIT_EXPENSE,
    SERVICE_LIST_EXPENSES,
)

from .helpers import (
    COURSES_ID,
    LUNCH_ID,
    add_expense_record,
    bucket_device_id,
    courses_subentry,
    lunch_subentry,
    setup_household,
)


async def test_add_expense_on_a_device_creates_exactly_one_expense(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        {
            "device_id": bucket_device_id(hass, COURSES_ID),
            "amount": 42.50,
            "description": "Supermarché",
        },
        blocking=True,
        return_response=True,
        context=Context(user_id="user-42"),
    )
    await hass.async_block_till_done()

    expenses = entry.runtime_data.store.data.expenses
    assert len(expenses) == 1
    expense = expenses[0]
    assert expense.bucket_id == COURSES_ID
    assert expense.amount_cents == 4_250
    assert expense.date == date(2025, 10, 14)
    assert expense.description == "Supermarché"
    assert expense.created_by == "user-42"
    assert response == {"expense_id": expense.id}

    assert hass.states.get("sensor.courses_spent").state == "42.5"
    assert hass.states.get("sensor.courses_remaining").state == "457.5"


async def test_add_expense_accepts_an_entity_target(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        {"entity_id": "sensor.courses_remaining", "amount": 10},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(entry.runtime_data.store.data.expenses) == 1


async def test_add_expense_accepts_a_string_amount(hass: HomeAssistant, freezer) -> None:
    """An iOS Shortcut's JSON payload carries its variables as strings."""
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        {"entity_id": "sensor.courses_remaining", "amount": "12.50"},
        blocking=True,
    )
    await hass.async_block_till_done()

    expenses = entry.runtime_data.store.data.expenses
    assert [e.amount_cents for e in expenses] == [1250]


async def test_add_expense_can_be_backdated(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        {
            "device_id": bucket_device_id(hass, COURSES_ID),
            "amount": 100,
            "date": "2025-10-02",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.store.data.expenses[0].date == date(2025, 10, 2)
    assert hass.states.get("sensor.courses_spent").state == "100.0"


async def test_a_negative_amount_records_a_refund(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    await hass.services.async_call(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        {"device_id": bucket_device_id(hass, COURSES_ID), "amount": -50},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert hass.states.get("sensor.courses_spent").state == "150.0"


async def test_a_zero_amount_is_rejected(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass)

    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_EXPENSE,
            {"device_id": bucket_device_id(hass, COURSES_ID), "amount": 0},
            blocking=True,
        )


async def test_add_expense_without_a_target_is_rejected(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, SERVICE_ADD_EXPENSE, {"amount": 10}, blocking=True)


async def test_add_expense_refuses_two_buckets_at_once(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass, courses_subentry(), lunch_subentry())

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_ADD_EXPENSE,
            {
                "device_id": [
                    bucket_device_id(hass, COURSES_ID),
                    bucket_device_id(hass, LUNCH_ID),
                ],
                "amount": 10,
            },
            blocking=True,
        )


async def test_edit_expense_changes_the_figures(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    expense = await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    await hass.services.async_call(
        DOMAIN,
        SERVICE_EDIT_EXPENSE,
        {"expense_id": expense.id, "amount": 300, "description": "Corrigé"},
        blocking=True,
    )
    await hass.async_block_till_done()

    stored = entry.runtime_data.store.get_expense(expense.id)
    assert stored.amount_cents == 30_000
    assert stored.description == "Corrigé"
    assert stored.updated_at != expense.updated_at
    assert hass.states.get("sensor.courses_remaining").state == "200.0"


async def test_edit_expense_with_a_target_moves_it_to_that_bucket(
    hass: HomeAssistant, freezer
) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass, courses_subentry(), lunch_subentry())
    expense = await add_expense_record(hass, entry, COURSES_ID, 3_000, date(2025, 10, 1))

    await hass.services.async_call(
        DOMAIN,
        SERVICE_EDIT_EXPENSE,
        {
            "expense_id": expense.id,
            "device_id": bucket_device_id(hass, LUNCH_ID),
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.store.get_expense(expense.id).bucket_id == LUNCH_ID
    assert hass.states.get("sensor.courses_spent").state == "0.0"
    assert hass.states.get("sensor.lunch_snack_spent").state == "30.0"


async def test_delete_expense_corrects_the_figures(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    expense = await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    await hass.services.async_call(
        DOMAIN, SERVICE_DELETE_EXPENSE, {"expense_id": expense.id}, blocking=True
    )
    await hass.async_block_till_done()

    assert entry.runtime_data.store.data.expenses == []
    assert hass.states.get("sensor.courses_remaining").state == "500.0"


async def test_editing_an_unknown_expense_is_rejected(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    await setup_household(hass)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN, SERVICE_EDIT_EXPENSE, {"expense_id": "nope", "amount": 1}, blocking=True
        )


async def test_list_expenses_returns_rows_newest_first(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass, courses_subentry(), lunch_subentry())
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1), expense_id="older")
    await add_expense_record(hass, entry, COURSES_ID, 5_000, date(2025, 10, 10), expense_id="newer")
    await add_expense_record(hass, entry, LUNCH_ID, 3_000, date(2025, 10, 5), expense_id="lunch")

    response = await hass.services.async_call(
        DOMAIN, SERVICE_LIST_EXPENSES, {}, blocking=True, return_response=True
    )

    assert [row["expense_id"] for row in response["expenses"]] == [
        "newer",
        "lunch",
        "older",
    ]
    assert response["expenses"][0]["amount"] == 50.0
    assert response["expenses"][0]["bucket_name"] == "Courses"


async def test_list_expenses_filters_by_target_and_dates(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass, courses_subentry(), lunch_subentry())
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1), expense_id="first")
    await add_expense_record(
        hass, entry, COURSES_ID, 5_000, date(2025, 10, 10), expense_id="second"
    )
    await add_expense_record(hass, entry, LUNCH_ID, 3_000, date(2025, 10, 5), expense_id="lunch")

    by_bucket = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST_EXPENSES,
        {"device_id": bucket_device_id(hass, COURSES_ID)},
        blocking=True,
        return_response=True,
    )
    assert {row["expense_id"] for row in by_bucket["expenses"]} == {"first", "second"}

    by_date = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST_EXPENSES,
        {"date_from": "2025-10-04", "date_to": "2025-10-06"},
        blocking=True,
        return_response=True,
    )
    assert [row["expense_id"] for row in by_date["expenses"]] == ["lunch"]


async def test_list_expenses_honours_the_limit(hass: HomeAssistant, freezer) -> None:
    freezer.move_to("2025-10-14 12:00:00+02:00")
    entry = await setup_household(hass)
    for day in (1, 2, 3):
        await add_expense_record(
            hass, entry, COURSES_ID, 1_000, date(2025, 10, day), expense_id=f"e{day}"
        )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_LIST_EXPENSES,
        {"limit": 2},
        blocking=True,
        return_response=True,
    )

    assert [row["expense_id"] for row in response["expenses"]] == ["e3", "e2"]
