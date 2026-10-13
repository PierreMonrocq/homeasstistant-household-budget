"""Tests for bucket management from the panel.

Creating, editing and archiving a bucket used to be a config subentry flow.
It is now websocket commands, which is what lets the panel default a personal
bucket's owner to whoever creates it — a flow is never told which user opened
it.
"""

from __future__ import annotations

from datetime import date

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from custom_components.household_budget.buckets import (
    bucket_from_subentry,
    buckets_for_entry,
    subentry_for_bucket,
)
from custom_components.household_budget.const import DOMAIN

from .helpers import (
    COURSES_ID,
    LUNCH_ID,
    add_expense_record,
    bucket_subentry,
    courses_subentry,
    setup_household,
)


async def _connect_then_freeze(hass, hass_ws_client, freezer, token=None):
    """Connect before freezing the clock; see tests/test_websocket_api.py."""
    client = await hass_ws_client(hass, token) if token else await hass_ws_client(hass)
    freezer.move_to("2025-10-14 12:00:00+02:00")
    return client


async def test_create_bucket_adds_a_working_bucket(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry())

    await client.send_json_auto_id(
        {
            "type": "household_budget/create_bucket",
            "name": "Vêtements",
            "period_days": 90,
            "limit": 200,
            "icon": "mdi:tshirt-crew",
            "color": "purple",
            "alert_threshold_percent": 80,
        }
    )
    response = await client.receive_json()
    assert response["success"]
    bucket_id = response["result"]["bucket_id"]
    await hass.async_block_till_done()

    subentry = subentry_for_bucket(entry, bucket_id)
    bucket = bucket_from_subentry(subentry)
    assert bucket.name == "Vêtements"
    assert bucket.period_days == 90
    assert bucket.limit_cents == 20_000
    assert bucket.icon == "mdi:tshirt-crew"
    assert bucket.color == "purple"
    assert bucket.alert_threshold_percent == 80
    assert bucket.visibility == "shared"
    assert bucket.archived is False

    # The reload that follows gives it a device and its entities.
    assert hass.states.get("sensor.vetements_remaining").state == "200.0"
    assert hass.states.get("number.vetements_limit").state == "200.0"


async def test_a_personal_bucket_belongs_to_whoever_creates_it(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, freezer
) -> None:
    """The whole point of creating from the panel rather than a config flow."""
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry())

    await client.send_json_auto_id(
        {
            "type": "household_budget/create_bucket",
            "name": "Lunch & Snack",
            "period_days": 90,
            "limit": 120,
            "visibility": "personal",
        }
    )
    response = await client.receive_json()
    assert response["success"]
    await hass.async_block_till_done()

    bucket = bucket_from_subentry(subentry_for_bucket(entry, response["result"]["bucket_id"]))
    assert bucket.visibility == "personal"
    assert bucket.owner == hass_admin_user.id


async def test_an_explicit_owner_is_kept(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry())

    await client.send_json_auto_id(
        {
            "type": "household_budget/create_bucket",
            "name": "Vêtements",
            "period_days": 90,
            "limit": 200,
            "visibility": "personal",
            "owner": "chloe-user-id",
        }
    )
    response = await client.receive_json()
    await hass.async_block_till_done()

    bucket = bucket_from_subentry(subentry_for_bucket(entry, response["result"]["bucket_id"]))
    assert bucket.owner == "chloe-user-id"
    assert bucket.owner != hass_admin_user.id


async def test_a_user_id_owner_is_resolved_without_a_person_entity(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    """Storing the user id directly removes the unlinked-person trap."""
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    await setup_household(
        hass,
        courses_subentry(),
        bucket_subentry(LUNCH_ID, "Vêtements", visibility="personal", owner="chloe-user-id"),
    )

    await client.send_json_auto_id({"type": "household_budget/subscribe_buckets"})
    assert (await client.receive_json())["success"]
    message = await client.receive_json()

    # No person entity involved at all, and it is hidden from this user.
    assert [b["name"] for b in message["event"]["buckets"]] == ["Courses"]


async def test_update_bucket_changes_name_window_and_limit(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry())
    await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    await client.send_json_auto_id(
        {
            "type": "household_budget/update_bucket",
            "bucket_id": COURSES_ID,
            "name": "Courses & maison",
            "period_days": 14,
            "limit": 600,
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    bucket = bucket_from_subentry(subentry_for_bucket(entry, COURSES_ID))
    assert bucket.name == "Courses & maison"
    assert bucket.period_days == 14
    assert bucket.limit_cents == 60_000

    # Renaming a bucket renames its device, but Home Assistant deliberately
    # keeps entity ids stable, so automations and dashboards keep working.
    state = hass.states.get("sensor.courses_remaining")
    assert state.state == "400.0"


async def test_delete_bucket_without_expenses_removes_it(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry())

    await client.send_json_auto_id(
        {"type": "household_budget/delete_bucket", "bucket_id": COURSES_ID}
    )
    response = await client.receive_json()
    assert response["result"] == {"archived": False}
    await hass.async_block_till_done()

    assert buckets_for_entry(entry) == []
    assert hass.states.get("sensor.courses_remaining") is None


async def test_delete_bucket_with_expenses_archives_it(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry())
    expense = await add_expense_record(hass, entry, COURSES_ID, 20_000, date(2025, 10, 1))

    await client.send_json_auto_id(
        {"type": "household_budget/delete_bucket", "bucket_id": COURSES_ID}
    )
    response = await client.receive_json()
    assert response["result"] == {"archived": True}
    await hass.async_block_till_done()

    bucket = bucket_from_subentry(subentry_for_bucket(entry, COURSES_ID))
    assert bucket.archived is True
    # The history survives; the device and its entities are gone rather than
    # left behind as `unavailable` forever.
    assert entry.runtime_data.store.get_expense(expense.id) is not None
    assert dr.async_get(hass).async_get_device(identifiers={(DOMAIN, COURSES_ID)}) is None
    assert hass.states.get("sensor.courses_remaining") is None


async def test_an_archived_bucket_can_be_restored(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, bucket_subentry(COURSES_ID, "Courses", archived=True))

    await client.send_json_auto_id(
        {
            "type": "household_budget/update_bucket",
            "bucket_id": COURSES_ID,
            "archived": False,
        }
    )
    assert (await client.receive_json())["success"]
    await hass.async_block_till_done()

    assert bucket_from_subentry(subentry_for_bucket(entry, COURSES_ID)).archived is False
    assert hass.states.get("sensor.courses_remaining") is not None


async def test_archived_buckets_are_only_sent_when_asked_for(
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
    assert [b["name"] for b in (await client.receive_json())["event"]["buckets"]] == ["Courses"]

    await client.send_json_auto_id(
        {"type": "household_budget/subscribe_buckets", "include_archived": True}
    )
    assert (await client.receive_json())["success"]
    buckets = (await client.receive_json())["event"]["buckets"]

    # Active first, archived last: the panel lists them in separate sections.
    assert [b["name"] for b in buckets] == ["Courses", "Lunch & Snack"]
    assert [b["archived"] for b in buckets] == [False, True]


async def test_households_lists_where_a_bucket_can_be_created(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    entry = await setup_household(hass, courses_subentry())

    await client.send_json_auto_id({"type": "household_budget/households"})
    response = await client.receive_json()

    assert response["result"]["households"] == [
        {"entry_id": entry.entry_id, "name": "Our Household", "currency": "EUR"}
    ]


async def test_managing_buckets_requires_admin(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token, freezer
) -> None:
    """Changing a bucket changes the integration's configuration."""
    client = await _connect_then_freeze(
        hass, hass_ws_client, freezer, token=hass_read_only_access_token
    )
    entry = await setup_household(hass, courses_subentry())

    await client.send_json_auto_id(
        {
            "type": "household_budget/create_bucket",
            "name": "Sneaky",
            "period_days": 30,
            "limit": 100,
        }
    )
    response = await client.receive_json()
    assert not response["success"]
    assert response["error"]["code"] == "unauthorized"

    await client.send_json_auto_id(
        {"type": "household_budget/delete_bucket", "bucket_id": COURSES_ID}
    )
    assert not (await client.receive_json())["success"]

    assert [b.name for b in buckets_for_entry(entry)] == ["Courses"]


async def test_a_non_admin_can_still_record_an_expense(
    hass: HomeAssistant, hass_ws_client, hass_read_only_access_token, freezer
) -> None:
    """Spending is everyday use, not configuration."""
    client = await _connect_then_freeze(
        hass, hass_ws_client, freezer, token=hass_read_only_access_token
    )
    entry = await setup_household(hass, courses_subentry())

    await client.send_json_auto_id(
        {
            "type": "household_budget/add_expense",
            "bucket_id": COURSES_ID,
            "amount": 12.5,
        }
    )
    assert (await client.receive_json())["success"]

    assert len(entry.runtime_data.store.data.expenses) == 1


async def test_updating_an_unknown_bucket_errors(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    await setup_household(hass, courses_subentry())

    await client.send_json_auto_id(
        {"type": "household_budget/update_bucket", "bucket_id": "nope", "limit": 1}
    )
    response = await client.receive_json()

    assert not response["success"]
    assert response["error"]["code"] == "bucket_not_found"


async def test_creating_a_bucket_pushes_it_to_open_panels(
    hass: HomeAssistant, hass_ws_client, freezer
) -> None:
    """Creating a bucket reloads the entry, which replaces the coordinator.

    A subscription bound to the old coordinator object would go silent and
    the panel would show a stale list until it was reloaded by hand.
    """
    client = await _connect_then_freeze(hass, hass_ws_client, freezer)
    await setup_household(hass, courses_subentry())

    await client.send_json_auto_id({"type": "household_budget/subscribe_buckets"})
    assert (await client.receive_json())["success"]
    first = await client.receive_json()
    assert [b["name"] for b in first["event"]["buckets"]] == ["Courses"]

    await client.send_json_auto_id(
        {
            "type": "household_budget/create_bucket",
            "name": "Sorties",
            "period_days": 30,
            "limit": 30,
        }
    )

    # The reload happens while the command is being handled, so the push
    # lands just before the command's own result. Reading exactly the two
    # expected messages means a regression fails here rather than hanging
    # the suite waiting for a push that never comes — a timeout would not
    # help, the clock is frozen.
    messages = [await client.receive_json(), await client.receive_json()]
    pushes = [m for m in messages if m["type"] == "event"]
    results = [m for m in messages if m["type"] == "result"]

    assert results[0]["success"]
    assert pushes, "no bucket push reached the open panel"
    assert [b["name"] for b in pushes[0]["event"]["buckets"]] == ["Courses", "Sorties"]
