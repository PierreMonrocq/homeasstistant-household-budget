"""Websocket commands backing the management panel.

Expense commands are thin wrappers over the same functions the actions use, so
there is one implementation of "add an expense", not two. Buckets are addressed
by id here rather than by HA target: the panel already knows the ids, and a
target would mean a device lookup round trip for nothing.

`household_budget/subscribe_buckets` pushes the bucket list on every
coordinator refresh, so the panel's progress bars follow an added expense — and
the window moving at midnight — without polling.

Bucket management lives here rather than in a config flow for one concrete
reason: a flow is never told which user opened it, so a personal bucket's
owner had to be picked by hand. A websocket connection knows its user, which
is what makes "the creator owns it" possible.

Two different rules apply, and they are not the same thing:

* **Reading and spending** may only touch what the panel shows the connected
  user. Those commands funnel through `_is_actionable_for`, so a bucket that is
  archived, owned by someone else, or gone is uniformly reported as not found —
  whether addressed directly or reached through one of its expenses.
* **Managing** (create / update / delete) requires admin and ignores
  visibility: an admin fixing the configuration must be able to reach an
  archived bucket to restore it, or someone else's personal bucket to correct
  it.

The actions in `services.py` apply neither. They are called from automations,
which run with no user context at all, and the spec is explicit that
shared/personal does not restrict who may add expenses. The visibility filter
is a property of this panel-facing API, not of the data model — and never a
security boundary, since the sensors stay readable through the API.
"""

from __future__ import annotations

from datetime import date
from typing import Any
import uuid

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .buckets import (
    bucket_has_records,
    buckets_for_entry,
    new_bucket_subentry_data,
    subentry_for_bucket,
)
from .calculations import BucketStatus
from .const import (
    DEFAULT_LIST_LIMIT,
    DOMAIN,
    MAX_DESCRIPTION_LENGTH,
    MAX_LIST_LIMIT,
    MAX_PERIOD_DAYS,
    SIGNAL_BUCKETS_UPDATED,
    SUBENTRY_TYPE_BUCKET,
    VISIBILITY_OPTIONS,
    VISIBILITY_PERSONAL,
    VISIBILITY_SHARED,
)
from .models import Bucket
from .services import async_add_expense, async_delete_expense, async_edit_expense


@callback
def async_setup_websocket_api(hass: HomeAssistant) -> None:
    """Register the panel's websocket commands."""
    websocket_api.async_register_command(hass, websocket_subscribe_buckets)
    websocket_api.async_register_command(hass, websocket_list_expenses)
    websocket_api.async_register_command(hass, websocket_add_expense)
    websocket_api.async_register_command(hass, websocket_edit_expense)
    websocket_api.async_register_command(hass, websocket_delete_expense)
    websocket_api.async_register_command(hass, websocket_households)
    websocket_api.async_register_command(hass, websocket_create_bucket)
    websocket_api.async_register_command(hass, websocket_update_bucket)
    websocket_api.async_register_command(hass, websocket_delete_bucket)


# -- Visibility ---------------------------------------------------------------


def _owner_user_id(hass: HomeAssistant, owner: str | None) -> str | None:
    """Resolve a bucket's owner to a Home Assistant user id.

    An owner is stored as a user id — the panel knows who is creating a
    bucket, so it records that directly and there is no indirection to get
    wrong. A `person.*` entity id is still accepted and resolved through its
    `user_id` attribute, which is what buckets configured before the panel
    existed hold.
    """
    if not owner:
        return None
    if owner.startswith("person."):
        state = hass.states.get(owner)
        return state.attributes.get("user_id") if state else None
    return owner


def _is_visible_to(hass: HomeAssistant, bucket: Bucket, user_id: str | None) -> bool:
    """Whether a bucket should be shown to the connected user.

    Shared buckets are shown to everyone. A personal bucket is shown only to
    the user its owner resolves to — with no bypass for administrators, since
    otherwise the filter would do nothing in a household where both people
    are admins. A personal bucket whose owner cannot be resolved falls back to
    being visible, so a misconfiguration never silently hides money.

    This is a convenience filter, not an access control: Home Assistant has no
    per-user ACL on entities, and the sensors stay readable through the API.
    """
    if bucket.visibility != VISIBILITY_PERSONAL:
        return True
    owner_user_id = _owner_user_id(hass, bucket.owner)
    if owner_user_id is None:
        return True
    return owner_user_id == user_id


def _is_actionable_for(hass: HomeAssistant, bucket: Bucket | None, user_id: str | None) -> bool:
    """Whether a card connection may read or write this bucket at all.

    One predicate for every command here, so the card can never act on
    something it does not show: an archived bucket, a bucket belonging to
    someone else, or a bucket that no longer exists (an orphaned expense).
    The actions deliberately apply none of this — see the module docstring.
    """
    if bucket is None or bucket.archived:
        return False
    return _is_visible_to(hass, bucket, user_id)


def _ready_entries(hass: HomeAssistant) -> list[Any]:
    """Households this integration can answer about right now.

    Not `async_loaded_entries`: writing a bucket reloads the entry, and the
    refresh that follows pushes to open panels while the entry is still
    `SETUP_IN_PROGRESS` — it only becomes `LOADED` once `async_setup_entry`
    returns. Filtering on `LOADED` alone therefore answered that push with
    an empty list, and no further push ever came, so a newly created bucket
    stayed invisible until the page was reloaded by hand.

    An entry being set up is perfectly answerable: its `runtime_data` is in
    place and its coordinator has just computed. The `runtime_data` check is
    what keeps a half-set-up or unloaded entry out, since Home Assistant
    leaves the attribute behind on unload.
    """
    return [
        entry
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)
        and getattr(entry, "runtime_data", None) is not None
    ]


def _bucket_of(hass: HomeAssistant, entry: Any, bucket_id: str) -> Bucket | None:
    """Return a household's bucket by id, archived included, or None."""
    return next(
        (bucket for bucket in buckets_for_entry(entry) if bucket.id == bucket_id),
        None,
    )


def _status_payload(status: BucketStatus | None) -> dict[str, Any] | None:
    if status is None:
        return None
    return {
        "window_start": status.window.start.isoformat(),
        "window_end": status.window.end.isoformat(),
        "limit": status.limit / 100,
        "spent": status.spent / 100,
        "remaining": status.remaining / 100,
        "percent_used": status.percent_used,
        "next_release_date": (
            status.next_release_date.isoformat() if status.next_release_date else None
        ),
        "next_release_amount": status.next_release_amount / 100,
        "status": status.status,
        "threshold_percent": status.threshold_percent,
        "released_soon": status.released_soon / 100,
        "recovery_date": (status.recovery_date.isoformat() if status.recovery_date else None),
    }


def _bucket_payload(
    entry_id: str,
    currency: str,
    bucket: Bucket,
    status: BucketStatus | None,
    *,
    owner_is_me: bool,
) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "currency": currency,
        "bucket_id": bucket.id,
        "name": bucket.name,
        "icon": bucket.icon,
        "color": bucket.color,
        "period_days": bucket.period_days,
        "visibility": bucket.visibility,
        "owner": bucket.owner,
        "owner_is_me": owner_is_me,
        "alert_threshold_percent": bucket.alert_threshold_percent,
        "archived": bucket.archived,
        "status": _status_payload(status),
    }


@callback
def _visible_buckets(
    hass: HomeAssistant, user_id: str | None, *, include_archived: bool = False
) -> list[dict[str, Any]]:
    """Every bucket this user may see, with its current figures.

    Archived buckets are left out unless the management panel asks for them:
    it is the one place that can restore one, so it is the one place that
    should see them.
    """
    payloads: list[dict[str, Any]] = []
    for entry in _ready_entries(hass):
        runtime = entry.runtime_data
        statuses = runtime.coordinator.data or {}
        for bucket in buckets_for_entry(entry):
            if bucket.archived:
                if not include_archived or not _is_visible_to(hass, bucket, user_id):
                    continue
            elif not _is_actionable_for(hass, bucket, user_id):
                continue
            payloads.append(
                _bucket_payload(
                    entry.entry_id,
                    runtime.currency,
                    bucket,
                    statuses.get(bucket.id),
                    owner_is_me=_owner_user_id(hass, bucket.owner) == user_id,
                )
            )
    payloads.sort(key=lambda payload: (payload["archived"], payload["name"].lower()))
    return payloads


# -- Commands -----------------------------------------------------------------


@callback
@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/subscribe_buckets",
        vol.Optional("include_archived", default=False): bool,
    }
)
def websocket_subscribe_buckets(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Send the visible buckets now, and again on every recompute."""
    user_id = connection.user.id
    include_archived = msg["include_archived"]

    @callback
    def _push() -> None:
        connection.send_message(
            websocket_api.event_message(
                msg["id"],
                {
                    "buckets": _visible_buckets(hass, user_id, include_archived=include_archived),
                    "can_manage": connection.user.is_admin,
                },
            )
        )

    # Not `coordinator.async_add_listener`: writing a bucket reloads the
    # config entry, which replaces the coordinator, and a listener bound to
    # the old object would never fire again — the panel would go silent
    # until the page was reloaded by hand.
    connection.subscriptions[msg["id"]] = async_dispatcher_connect(
        hass, SIGNAL_BUCKETS_UPDATED, _push
    )
    connection.send_result(msg["id"])
    _push()


@callback
@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/expenses",
        vol.Optional("bucket_id"): str,
        vol.Optional("limit", default=DEFAULT_LIST_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LIST_LIMIT)
        ),
    }
)
def websocket_list_expenses(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List recent expenses of the buckets this user may see, newest first."""
    wanted = {
        payload["bucket_id"]: payload["name"]
        for payload in _visible_buckets(hass, connection.user.id)
        if "bucket_id" not in msg or payload["bucket_id"] == msg["bucket_id"]
    }

    rows: list[dict[str, Any]] = []
    for entry in _ready_entries(hass):
        for expense in entry.runtime_data.store.data.expenses:
            if expense.bucket_id not in wanted:
                continue
            rows.append(
                {
                    "expense_id": expense.id,
                    "bucket_id": expense.bucket_id,
                    "bucket_name": wanted[expense.bucket_id],
                    "amount": expense.amount_cents / 100,
                    "date": expense.date.isoformat(),
                    "description": expense.description,
                    "created_by": expense.created_by,
                }
            )

    rows.sort(key=lambda row: row["date"], reverse=True)
    connection.send_result(msg["id"], {"expenses": rows[: msg["limit"]]})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/add_expense",
        vol.Required("bucket_id"): str,
        vol.Required("amount"): vol.Coerce(float),
        vol.Optional("date"): str,
        vol.Optional("description"): vol.Any(None, vol.Length(max=MAX_DESCRIPTION_LENGTH)),
    }
)
@websocket_api.async_response
async def websocket_add_expense(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add an expense from the card (a negative amount is a refund)."""
    if msg["amount"] == 0:
        connection.send_error(msg["id"], "invalid_amount", "The amount must not be zero")
        return

    located = _locate_bucket(hass, connection, msg)
    if located is None:
        return
    entry, bucket = located

    expense = await async_add_expense(
        hass,
        entry,
        bucket.id,
        amount_cents=round(msg["amount"] * 100),
        expense_date=_parse_date(msg.get("date")),
        description=msg.get("description") or None,
        created_by=connection.user.id,
    )
    connection.send_result(msg["id"], {"expense_id": expense.id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/edit_expense",
        vol.Required("expense_id"): str,
        vol.Optional("bucket_id"): str,
        vol.Optional("amount"): vol.Coerce(float),
        vol.Optional("date"): str,
        vol.Optional("description"): vol.Any(None, vol.Length(max=MAX_DESCRIPTION_LENGTH)),
    }
)
@websocket_api.async_response
async def websocket_edit_expense(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Edit an expense from the card."""
    found = _locate_expense(hass, connection, msg)
    if found is None:
        return
    entry, _expense = found

    changes: dict[str, Any] = {}
    if "amount" in msg:
        if msg["amount"] == 0:
            connection.send_error(msg["id"], "invalid_amount", "The amount must not be zero")
            return
        changes["amount_cents"] = round(msg["amount"] * 100)
    if "date" in msg:
        changes["date"] = _parse_date(msg["date"])
    if "description" in msg:
        changes["description"] = msg["description"] or None
    if "bucket_id" in msg:
        located = _locate_bucket(hass, connection, msg)
        if located is None:
            return
        changes["bucket_id"] = located[1].id

    await async_edit_expense(hass, entry, msg["expense_id"], **changes)
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/delete_expense",
        vol.Required("expense_id"): str,
    }
)
@websocket_api.async_response
async def websocket_delete_expense(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete an expense from the card."""
    found = _locate_expense(hass, connection, msg)
    if found is None:
        return
    entry, expense = found
    await async_delete_expense(hass, entry, expense)
    connection.send_result(msg["id"])


# -- Bucket management ---------------------------------------------------------
#
# Creating, editing and archiving a bucket changes the integration's
# configuration, so these require admin, exactly as the config flow did. The
# panel hides the controls for non-admins, but the check lives here.


@callback
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "household_budget/households"})
def websocket_households(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List the loaded households, so the panel knows where to create."""
    connection.send_result(
        msg["id"],
        {
            "households": [
                {
                    "entry_id": entry.entry_id,
                    "name": entry.runtime_data.name,
                    "currency": entry.runtime_data.currency,
                }
                for entry in _ready_entries(hass)
            ]
        },
    )


@callback
def _forget_bucket_device(hass: HomeAssistant, bucket_id: str) -> None:
    """Remove an archived bucket's device, and with it its entities.

    An archived bucket stops being provided, but without this its device and
    entities would linger in the registries as `unavailable` for good — the
    opposite of what archiving should look like. Removing a subentry does
    this cleanup itself; archiving has to ask.
    """
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, bucket_id)})
    if device is not None:
        device_registry.async_remove_device(device.id)


BUCKET_FIELDS = {
    vol.Optional("icon"): vol.Any(None, str),
    vol.Optional("color"): vol.Any(None, str),
    vol.Optional("visibility"): vol.In(VISIBILITY_OPTIONS),
    vol.Optional("owner"): vol.Any(None, str),
    vol.Optional("alert_threshold_percent"): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=1, max=100))
    ),
}


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/create_bucket",
        vol.Optional("entry_id"): str,
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=100)),
        vol.Required("period_days"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_PERIOD_DAYS)
        ),
        vol.Required("limit"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        **BUCKET_FIELDS,
    }
)
@websocket_api.async_response
async def websocket_create_bucket(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create a bucket from the management panel.

    A personal bucket defaults to being owned by whoever creates it. That is
    only possible here: a config flow is never told which user opened it, so
    the owner had to be picked by hand from a person entity before the panel
    existed.
    """
    entry = _locate_entry(hass, connection, msg)
    if entry is None:
        return

    visibility = msg.get("visibility", VISIBILITY_SHARED)
    owner = msg.get("owner")
    if visibility == VISIBILITY_PERSONAL and not owner:
        owner = connection.user.id

    subentry = ConfigSubentry(
        data=new_bucket_subentry_data(
            period_days=msg["period_days"],
            limit_cents=round(msg["limit"] * 100),
            visibility=visibility,
            owner=owner,
            icon=msg.get("icon"),
            color=msg.get("color"),
            alert_threshold_percent=msg.get("alert_threshold_percent"),
        ),
        subentry_type=SUBENTRY_TYPE_BUCKET,
        title=msg["name"],
        unique_id=str(uuid.uuid4()),
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    connection.send_result(msg["id"], {"bucket_id": subentry.unique_id})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/update_bucket",
        vol.Required("bucket_id"): str,
        vol.Optional("name"): vol.All(str, vol.Length(min=1, max=100)),
        vol.Optional("period_days"): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_PERIOD_DAYS)
        ),
        vol.Optional("limit"): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional("archived"): bool,
        **BUCKET_FIELDS,
    }
)
@websocket_api.async_response
async def websocket_update_bucket(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Edit a bucket, or restore an archived one with `archived: false`."""
    located = _locate_managed_bucket(hass, connection, msg)
    if located is None:
        return
    entry, subentry = located

    data = dict(subentry.data)
    if "limit" in msg:
        data["limit_cents"] = round(msg["limit"] * 100)
    for field in ("icon", "color", "period_days", "visibility", "owner", "archived"):
        if field in msg:
            data[field] = msg[field]
    if "alert_threshold_percent" in msg:
        data["alert_threshold_percent"] = msg["alert_threshold_percent"]

    if data["visibility"] == VISIBILITY_PERSONAL and not data.get("owner"):
        data["owner"] = connection.user.id

    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data=data,
        **({"title": msg["name"]} if "name" in msg else {}),
    )
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "household_budget/delete_bucket",
        vol.Required("bucket_id"): str,
    }
)
@websocket_api.async_response
async def websocket_delete_bucket(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Delete a bucket, or archive it when it already has expenses."""
    located = _locate_managed_bucket(hass, connection, msg)
    if located is None:
        return
    entry, subentry = located
    bucket_id = msg["bucket_id"]

    if bucket_has_records(entry.runtime_data.store, bucket_id):
        hass.config_entries.async_update_subentry(
            entry, subentry, data={**subentry.data, "archived": True}
        )
        _forget_bucket_device(hass, bucket_id)
        connection.send_result(msg["id"], {"archived": True})
        return

    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    connection.send_result(msg["id"], {"archived": False})


# -- Lookups that answer the connection on failure ----------------------------


def _parse_date(raw: str | None) -> date:
    """Parse an ISO date from the card, defaulting to today."""
    if not raw:
        return dt_util.now().date()
    return date.fromisoformat(raw)


@callback
def _locate_bucket(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> tuple[Any, Bucket] | None:
    """Find the message's bucket, or answer with an error and return None."""
    bucket_id = msg["bucket_id"]
    for entry in _ready_entries(hass):
        bucket = _bucket_of(hass, entry, bucket_id)
        if bucket is None:
            continue
        if _is_actionable_for(hass, bucket, connection.user.id):
            return entry, bucket
        break
    connection.send_error(msg["id"], "bucket_not_found", f"No bucket with id {bucket_id}")
    return None


@callback
def _locate_expense(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> tuple[Any, Any] | None:
    """Find the message's expense, or answer with an error and return None.

    An expense whose bucket this connection may not act on answers
    `expense_not_found` rather than a distinct "not yours": the card never
    listed it, so from the card's point of view it does not exist. Cleaning
    up an expense left over from a deleted bucket is the actions' job, not
    the card's.
    """
    expense_id = msg["expense_id"]
    for entry in _ready_entries(hass):
        expense = entry.runtime_data.store.get_expense(expense_id)
        if expense is None:
            continue
        bucket = _bucket_of(hass, entry, expense.bucket_id)
        if _is_actionable_for(hass, bucket, connection.user.id):
            return entry, expense
        break
    connection.send_error(msg["id"], "expense_not_found", f"No expense with id {expense_id}")
    return None


@callback
def _locate_entry(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> Any | None:
    """Find the household to create in: the named one, or the only one."""
    entries = _ready_entries(hass)
    entry_id = msg.get("entry_id")
    if entry_id is not None:
        entry = next((e for e in entries if e.entry_id == entry_id), None)
        if entry is not None:
            return entry
    elif len(entries) == 1:
        return entries[0]
    elif len(entries) > 1:
        connection.send_error(
            msg["id"],
            "household_required",
            "Several households exist; name one with entry_id",
        )
        return None

    connection.send_error(msg["id"], "household_not_found", "No such household")
    return None


@callback
def _locate_managed_bucket(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> tuple[Any, ConfigSubentry] | None:
    """Find a bucket's subentry for editing, archived ones included.

    Management deliberately does not go through `_is_actionable_for`: an
    admin editing the configuration must be able to reach an archived bucket
    to restore it, and someone else's personal bucket to fix it. The
    visibility filter is about what the panel *shows*, not about who may
    administer the integration.
    """
    bucket_id = msg["bucket_id"]
    for entry in _ready_entries(hass):
        subentry = subentry_for_bucket(entry, bucket_id)
        if subentry is not None:
            return entry, subentry
    connection.send_error(msg["id"], "bucket_not_found", f"No bucket with id {bucket_id}")
    return None
