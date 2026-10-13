"""Tests for the websocket commands the dashboard card uses (phase 6)."""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant

from .helpers import (
    COURSES_ID,
    LUNCH_ID,
    add_expense_record,
    bucket_device_id,
    bucket_subentry,
    courses_subentry,
    lunch_subentry,
    setup_household,
)


async def _connect_then_freeze(
    hass: HomeAssistant,
    hass_ws_client,
    freezer,
    moment: str = "2025-10-14 12:00:00+02:00",
):
    """Open the websocket connection first, then freeze the clock.

    The test client authenticates with a token minted at the real current
    time. Moving the clock back to a fixed test date before connecting makes
    that token look not-yet-valid and the handshake fails with
    `auth_invalid`, so the order here matters.
    """
    client = await hass_ws_client(hass)
    freezer.move_to(moment)
    return client


async def test_subscribe_buckets_pushes_the_current_figures(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry(), lunch_subentry())
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    await client.send_json_auto_id({"type": "household_budget/subscribe_buckets"})
    assert (await client.receive_json())["success"]

    message = await client.receive_json()
    buckets = message["event"]["buckets"]

    # Sorted by name: Courses, then Lunch & Snack.
    assert [bucket["name"] for bucket in buckets] == ["Courses", "Lunch & Snack"]
    courses = buckets[0]
    assert courses["bucket_id"] == COURSES_ID
    assert courses["currency"] == "EUR"
    assert courses["period_days"] == 30
    assert courses["status"]["limit"] == 500.0
    assert courses["status"]["spent"] == 200.0
    assert courses["status"]["remaining"] == 300.0
    assert courses["status"]["percent_used"] == 40.0
    assert courses["status"]["window_start"] == "2025-09-15"
    assert courses["status"]["next_release_date"] == "2025-10-31"


async def test_subscription_pushes_again_when_an_expense_is_added(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    """The card's bars follow a mutation without asking for them."""
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    await setup_household(hass)

    await client.send_json_auto_id({"type": "household_budget/subscribe_buckets"})
    assert (await client.receive_json())["success"]
    first = await client.receive_json()
    assert first["event"]["buckets"][0]["status"]["remaining"] == 500.0

    await client.send_json_auto_id(
        {
            "type": "household_budget/add_expense",
            "bucket_id": COURSES_ID,
            "amount": 120.50,
            "description": "Supermarché",
        }
    )

    # The push and the command result both arrive; order is not guaranteed.
    messages = [await client.receive_json(), await client.receive_json()]
    pushes = [m for m in messages if m["type"] == "event"]
    results = [m for m in messages if m["type"] == "result"]

    assert results[0]["success"]
    assert results[0]["result"]["expense_id"]
    assert pushes[0]["event"]["buckets"][0]["status"]["remaining"] == 379.5


async def test_add_expense_records_the_connected_user(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass)

    await client.send_json_auto_id(
        {
            "type": "household_budget/add_expense",
            "bucket_id": COURSES_ID,
            "amount": 10,
        }
    )
    assert (await client.receive_json())["success"]

    (expense,) = entry.runtime_data.store.data.expenses
    assert expense.created_by == hass_admin_user.id
    assert expense.date == date(2025, 10, 14)


async def test_add_expense_rejects_zero_and_unknown_buckets(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    await setup_household(hass)

    await client.send_json_auto_id(
        {"type": "household_budget/add_expense", "bucket_id": COURSES_ID, "amount": 0}
    )
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "invalid_amount"

    await client.send_json_auto_id(
        {"type": "household_budget/add_expense", "bucket_id": "nope", "amount": 10}
    )
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "bucket_not_found"


async def test_expenses_edit_and_delete_round_trip(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass)
    expense = await add_expense_record(
        hass, entry, COURSES_ID, 20_000, date(2025, 10, 1), description="Marché"
    )

    await client.send_json_auto_id({"type": "household_budget/expenses"})
    response = await client.receive_json()
    assert response["result"]["expenses"] == [
        {
            "expense_id": expense.id,
            "bucket_id": COURSES_ID,
            "bucket_name": "Courses",
            "amount": 200.0,
            "date": "2025-10-01",
            "description": "Marché",
            "created_by": "user1",
        }
    ]

    await client.send_json_auto_id(
        {
            "type": "household_budget/edit_expense",
            "expense_id": expense.id,
            "amount": 150,
            "date": "2025-10-05",
            "description": "Marché corrigé",
        }
    )
    assert (await client.receive_json())["success"]

    stored = entry.runtime_data.store.get_expense(expense.id)
    assert stored.amount_cents == 15_000
    assert stored.date == date(2025, 10, 5)
    assert stored.description == "Marché corrigé"

    await client.send_json_auto_id(
        {"type": "household_budget/delete_expense", "expense_id": expense.id}
    )
    assert (await client.receive_json())["success"]
    assert entry.runtime_data.store.data.expenses == []


async def test_deleting_an_unknown_expense_errors(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    await setup_household(hass)

    await client.send_json_auto_id(
        {"type": "household_budget/delete_expense", "expense_id": "nope"}
    )
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "expense_not_found"


async def test_expenses_can_be_filtered_to_one_bucket(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry(), lunch_subentry())
    await add_expense_record(
        hass, entry, COURSES_ID, 20_000, date(2025, 10, 1), expense_id="courses"
    )
    await add_expense_record(hass, entry, LUNCH_ID, 3_000, date(2025, 10, 2), expense_id="lunch")

    await client.send_json_auto_id({"type": "household_budget/expenses", "bucket_id": LUNCH_ID})
    response = await client.receive_json()

    assert [row["expense_id"] for row in response["result"]["expenses"]] == ["lunch"]


async def test_an_archived_bucket_is_not_offered_to_the_card(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    await setup_household(
        hass,
        courses_subentry(),
        bucket_subentry(LUNCH_ID, "Lunch & Snack", archived=True),
    )

    await client.send_json_auto_id({"type": "household_budget/subscribe_buckets"})
    assert (await client.receive_json())["success"]
    message = await client.receive_json()

    assert [bucket["name"] for bucket in message["event"]["buckets"]] == ["Courses"]


# -- Shared / personal visibility ---------------------------------------------


async def test_a_personal_bucket_is_hidden_from_other_users(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    # Chloé's person entity points at a different HA user than the one the
    # websocket client is authenticated as.
    hass.states.async_set("person.chloe", "home", {"user_id": "chloe-user-id"})
    await setup_household(
        hass,
        courses_subentry(),
        bucket_subentry(
            LUNCH_ID,
            "Vêtements",
            period_days=90,
            limit_cents=20_000,
            visibility="personal",
            owner="person.chloe",
        ),
    )

    await client.send_json_auto_id({"type": "household_budget/subscribe_buckets"})
    assert (await client.receive_json())["success"]
    message = await client.receive_json()

    assert [bucket["name"] for bucket in message["event"]["buckets"]] == ["Courses"]


async def test_a_personal_bucket_is_shown_to_its_owner(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    hass.states.async_set("person.me", "home", {"user_id": hass_admin_user.id})
    await setup_household(
        hass,
        courses_subentry(),
        bucket_subentry(
            LUNCH_ID,
            "Lunch & Snack",
            period_days=90,
            limit_cents=12_000,
            visibility="personal",
            owner="person.me",
        ),
    )

    await client.send_json_auto_id({"type": "household_budget/subscribe_buckets"})
    assert (await client.receive_json())["success"]
    message = await client.receive_json()

    assert [bucket["name"] for bucket in message["event"]["buckets"]] == [
        "Courses",
        "Lunch & Snack",
    ]


async def test_another_users_expense_cannot_be_edited_or_deleted(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    """Knowing an expense id is not enough: the bucket rule still applies."""
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    hass.states.async_set("person.chloe", "home", {"user_id": "chloe-user-id"})
    entry = await setup_household(
        hass,
        bucket_subentry(LUNCH_ID, "Vêtements", visibility="personal", owner="person.chloe"),
    )
    expense = await add_expense_record(hass, entry, LUNCH_ID, 5_000, date(2025, 10, 1))

    await client.send_json_auto_id(
        {
            "type": "household_budget/edit_expense",
            "expense_id": expense.id,
            "amount": 1,
        }
    )
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "expense_not_found"

    await client.send_json_auto_id(
        {"type": "household_budget/delete_expense", "expense_id": expense.id}
    )
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "expense_not_found"

    # Untouched on both counts.
    assert entry.runtime_data.store.get_expense(expense.id).amount_cents == 5_000


async def test_an_owner_can_edit_and_delete_their_own_expense(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, freezer
) -> None:
    """The rule must not block the person the bucket belongs to."""
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    hass.states.async_set("person.me", "home", {"user_id": hass_admin_user.id})
    entry = await setup_household(
        hass,
        bucket_subentry(LUNCH_ID, "Vêtements", visibility="personal", owner="person.me"),
    )
    expense = await add_expense_record(hass, entry, LUNCH_ID, 5_000, date(2025, 10, 1))

    await client.send_json_auto_id(
        {
            "type": "household_budget/edit_expense",
            "expense_id": expense.id,
            "amount": 80,
        }
    )
    assert (await client.receive_json())["success"]
    assert entry.runtime_data.store.get_expense(expense.id).amount_cents == 8_000

    await client.send_json_auto_id(
        {"type": "household_budget/delete_expense", "expense_id": expense.id}
    )
    assert (await client.receive_json())["success"]
    assert entry.runtime_data.store.data.expenses == []


async def test_an_archived_buckets_expense_is_not_actionable_from_the_card(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(
        hass, courses_subentry(), bucket_subentry(LUNCH_ID, "Lunch & Snack", archived=True)
    )
    expense = await add_expense_record(hass, entry, LUNCH_ID, 5_000, date(2025, 10, 1))

    await client.send_json_auto_id(
        {"type": "household_budget/delete_expense", "expense_id": expense.id}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "expense_not_found"
    assert entry.runtime_data.store.get_expense(expense.id) is not None


async def test_the_actions_deliberately_ignore_the_visibility_filter(
    hass: HomeAssistant, freezer
) -> None:
    """Automations have no user context, so the actions must stay unfiltered."""
    freezer.move_to("2025-10-14 12:00:00+02:00")
    hass.states.async_set("person.chloe", "home", {"user_id": "chloe-user-id"})
    entry = await setup_household(
        hass,
        bucket_subentry(LUNCH_ID, "Vêtements", visibility="personal", owner="person.chloe"),
    )

    await hass.services.async_call(
        "household_budget",
        "add_expense",
        {"device_id": bucket_device_id(hass, LUNCH_ID), "amount": 25},
        blocking=True,
    )
    await hass.async_block_till_done()

    assert len(entry.runtime_data.store.data.expenses) == 1


async def test_a_hidden_bucket_cannot_be_written_to(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    """The filter is for comfort, but the card's own commands still respect it."""
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    hass.states.async_set("person.chloe", "home", {"user_id": "chloe-user-id"})
    entry = await setup_household(
        hass,
        bucket_subentry(
            LUNCH_ID,
            "Vêtements",
            visibility="personal",
            owner="person.chloe",
        ),
    )

    await client.send_json_auto_id(
        {
            "type": "household_budget/add_expense",
            "bucket_id": LUNCH_ID,
            "amount": 10,
        }
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "bucket_not_found"
    assert entry.runtime_data.store.data.expenses == []
