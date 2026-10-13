"""Service (action) handlers for the Household Budget integration.

Buckets are addressed the HA-native way: every action declares `target:`, so
the UI offers the standard device / entity / area / label picker. A bucket is
one device, but it has several entities, so a device target resolves to all of
them — the resolution below therefore maps entities back to their device, reads
the bucket id out of the device identifiers, and **deduplicates**. Without that,
one `add_expense` on a device would create one expense per entity.

The real work of each action is a plain function taking a `bucket_id`, with the
handler as a thin target-resolving wrapper, so the phase 6 websocket commands
can call the same code with an id and no target at all.

There is no `set_bucket_limit`: the limit is a `number` entity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any
import uuid

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .buckets import buckets_for_entry
from .const import (
    ATTR_AMOUNT,
    ATTR_DATE,
    ATTR_DATE_FROM,
    ATTR_DATE_TO,
    ATTR_DESCRIPTION,
    ATTR_EXPENSE_ID,
    DEFAULT_LIST_LIMIT,
    DOMAIN,
    EVENT_EXPENSE_ADDED,
    EVENT_EXPENSE_DELETED,
    EVENT_EXPENSE_EDITED,
    MAX_DESCRIPTION_LENGTH,
    MAX_LIST_LIMIT,
    SERVICE_ADD_EXPENSE,
    SERVICE_DELETE_EXPENSE,
    SERVICE_EDIT_EXPENSE,
    SERVICE_LIST_EXPENSES,
)
from .models import Bucket, Expense

if TYPE_CHECKING:
    from . import HouseholdBudgetConfigEntry


def _non_zero_amount(value: float) -> float:
    """Validate a spendable amount: any number but zero, refunds included."""
    if value == 0:
        raise vol.Invalid("amount must not be zero")
    return value


_AMOUNT = vol.All(vol.Coerce(float), _non_zero_amount)
_DESCRIPTION = vol.All(cv.string, vol.Length(max=MAX_DESCRIPTION_LENGTH))

ADD_EXPENSE_SCHEMA = vol.Schema(
    {
        **cv.TARGET_SERVICE_FIELDS,
        vol.Required(ATTR_AMOUNT): _AMOUNT,
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_DESCRIPTION): _DESCRIPTION,
    }
)

EDIT_EXPENSE_SCHEMA = vol.Schema(
    {
        **cv.TARGET_SERVICE_FIELDS,
        vol.Required(ATTR_EXPENSE_ID): cv.string,
        vol.Optional(ATTR_AMOUNT): _AMOUNT,
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_DESCRIPTION): _DESCRIPTION,
    }
)

DELETE_EXPENSE_SCHEMA = vol.Schema({vol.Required(ATTR_EXPENSE_ID): cv.string})

LIST_EXPENSES_SCHEMA = vol.Schema(
    {
        **cv.TARGET_SERVICE_FIELDS,
        vol.Optional(ATTR_DATE_FROM): cv.date,
        vol.Optional(ATTR_DATE_TO): cv.date,
        vol.Optional("limit", default=DEFAULT_LIST_LIMIT): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_LIST_LIMIT)
        ),
    }
)


@dataclass(frozen=True)
class _TargetedBucket:
    """A bucket plus the household it belongs to."""

    entry: HouseholdBudgetConfigEntry
    bucket: Bucket


def _loaded_buckets(hass: HomeAssistant) -> dict[str, _TargetedBucket]:
    """Every non-archived bucket of every loaded household, by bucket id."""
    return {
        bucket.id: _TargetedBucket(entry, bucket)
        for entry in hass.config_entries.async_loaded_entries(DOMAIN)
        for bucket in buckets_for_entry(entry)
        if not bucket.archived
    }


def _resolve_buckets(hass: HomeAssistant, call: ServiceCall) -> list[_TargetedBucket]:
    """Resolve a service call's target into distinct buckets.

    Entities, devices, areas, floors and labels all funnel through the
    standard target helper; each resolved entity is mapped back to its device
    and the device's identifiers give the bucket id. Results are keyed by
    bucket id, so targeting a bucket's device — which holds several
    entities — yields that bucket exactly once.
    """
    selection = TargetSelection(call.data)
    if not selection.has_any_target:
        return []

    selected = async_extract_referenced_entity_ids(hass, selection)
    entity_registry = er.async_get(hass)
    device_ids = set(selected.referenced_devices)
    for entity_id in selected.referenced | selected.indirectly_referenced:
        entity = entity_registry.async_get(entity_id)
        if entity is not None and entity.device_id is not None:
            device_ids.add(entity.device_id)

    device_registry = dr.async_get(hass)
    known = _loaded_buckets(hass)
    resolved: dict[str, _TargetedBucket] = {}
    for device_id in device_ids:
        device = device_registry.async_get(device_id)
        if device is None:
            continue
        for domain, identifier in device.identifiers:
            if domain == DOMAIN and identifier in known:
                resolved[identifier] = known[identifier]

    return list(resolved.values())


def _resolve_one_bucket(hass: HomeAssistant, call: ServiceCall) -> _TargetedBucket:
    """Resolve a target that must name exactly one bucket."""
    resolved = _resolve_buckets(hass, call)
    if not resolved:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_bucket_target")
    if len(resolved) > 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="multiple_bucket_targets",
            translation_placeholders={
                "buckets": ", ".join(sorted(t.bucket.name for t in resolved))
            },
        )
    return resolved[0]


def _find_expense(
    hass: HomeAssistant, expense_id: str
) -> tuple[HouseholdBudgetConfigEntry, Expense]:
    """Locate an expense across every loaded household."""
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        expense = entry.runtime_data.store.get_expense(expense_id)
        if expense is not None:
            return entry, expense
    raise ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key="expense_not_found",
        translation_placeholders={"expense_id": expense_id},
    )


def _to_cents(amount: float) -> int:
    """Convert a major-currency-unit amount to integer cents."""
    return round(amount * 100)


def _expense_event_data(entry_id: str, expense: Expense) -> dict[str, Any]:
    return {
        "entry_id": entry_id,
        "bucket_id": expense.bucket_id,
        "expense_id": expense.id,
        "amount": expense.amount_cents / 100,
        "amount_cents": expense.amount_cents,
        "date": expense.date.isoformat(),
    }


# -- Core operations, addressed by id -----------------------------------------


async def async_add_expense(
    hass: HomeAssistant,
    entry: HouseholdBudgetConfigEntry,
    bucket_id: str,
    *,
    amount_cents: int,
    expense_date: date,
    description: str | None = None,
    created_by: str | None = None,
) -> Expense:
    """Record an expense (a negative amount records a refund)."""
    now = dt_util.utcnow().isoformat()
    expense = Expense(
        id=str(uuid.uuid4()),
        bucket_id=bucket_id,
        amount_cents=amount_cents,
        date=expense_date,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        description=description,
    )
    entry.runtime_data.store.add_expense(expense)
    await entry.runtime_data.coordinator.async_refresh()
    hass.bus.async_fire(EVENT_EXPENSE_ADDED, _expense_event_data(entry.entry_id, expense))
    return expense


async def async_edit_expense(
    hass: HomeAssistant,
    entry: HouseholdBudgetConfigEntry,
    expense_id: str,
    **changes: Any,
) -> Expense:
    """Change an expense's fields and recompute."""
    changes["updated_at"] = dt_util.utcnow().isoformat()
    expense = entry.runtime_data.store.update_expense(expense_id, **changes)
    await entry.runtime_data.coordinator.async_refresh()
    hass.bus.async_fire(EVENT_EXPENSE_EDITED, _expense_event_data(entry.entry_id, expense))
    return expense


async def async_delete_expense(
    hass: HomeAssistant,
    entry: HouseholdBudgetConfigEntry,
    expense: Expense,
) -> None:
    """Delete an expense and recompute."""
    entry.runtime_data.store.delete_expense(expense.id)
    await entry.runtime_data.coordinator.async_refresh()
    hass.bus.async_fire(EVENT_EXPENSE_DELETED, _expense_event_data(entry.entry_id, expense))


# -- Service handlers ---------------------------------------------------------


async def _async_add_expense_service(call: ServiceCall) -> ServiceResponse:
    """Handle `household_budget.add_expense`."""
    target = _resolve_one_bucket(call.hass, call)
    expense = await async_add_expense(
        call.hass,
        target.entry,
        target.bucket.id,
        amount_cents=_to_cents(call.data[ATTR_AMOUNT]),
        expense_date=call.data.get(ATTR_DATE) or dt_util.now().date(),
        description=call.data.get(ATTR_DESCRIPTION),
        created_by=call.context.user_id,
    )
    return {"expense_id": expense.id}


async def _async_edit_expense_service(call: ServiceCall) -> None:
    """Handle `household_budget.edit_expense`."""
    entry, _expense = _find_expense(call.hass, call.data[ATTR_EXPENSE_ID])

    changes: dict[str, Any] = {}
    if ATTR_AMOUNT in call.data:
        changes["amount_cents"] = _to_cents(call.data[ATTR_AMOUNT])
    if ATTR_DATE in call.data:
        changes["date"] = call.data[ATTR_DATE]
    if ATTR_DESCRIPTION in call.data:
        changes["description"] = call.data[ATTR_DESCRIPTION]
    if TargetSelection(call.data).has_any_target:
        # A target on an edit means "move this expense to that bucket".
        changes["bucket_id"] = _resolve_one_bucket(call.hass, call).bucket.id

    await async_edit_expense(call.hass, entry, call.data[ATTR_EXPENSE_ID], **changes)


async def _async_delete_expense_service(call: ServiceCall) -> None:
    """Handle `household_budget.delete_expense`."""
    entry, expense = _find_expense(call.hass, call.data[ATTR_EXPENSE_ID])
    await async_delete_expense(call.hass, entry, expense)


async def _async_list_expenses_service(call: ServiceCall) -> ServiceResponse:
    """Handle `household_budget.list_expenses`, a read-only query."""
    hass = call.hass
    targeted = _resolve_buckets(hass, call)
    if targeted:
        wanted = {t.bucket.id: t for t in targeted}
    else:
        wanted = _loaded_buckets(hass)

    date_from: date | None = call.data.get(ATTR_DATE_FROM)
    date_to: date | None = call.data.get(ATTR_DATE_TO)

    rows: list[dict[str, Any]] = []
    for bucket_id, target in wanted.items():
        for expense in target.entry.runtime_data.store.expenses_for_bucket(bucket_id):
            if date_from is not None and expense.date < date_from:
                continue
            if date_to is not None and expense.date > date_to:
                continue
            rows.append(
                {
                    "expense_id": expense.id,
                    "bucket_id": bucket_id,
                    "bucket_name": target.bucket.name,
                    "amount": expense.amount_cents / 100,
                    "amount_cents": expense.amount_cents,
                    "date": expense.date.isoformat(),
                    "description": expense.description,
                    "created_by": expense.created_by,
                    "created_at": expense.created_at,
                    "updated_at": expense.updated_at,
                }
            )

    rows.sort(key=lambda row: (row["date"], row["created_at"]), reverse=True)
    return {"expenses": rows[: call.data["limit"]]}


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions, once for all households."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_EXPENSE,
        _async_add_expense_service,
        schema=ADD_EXPENSE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EDIT_EXPENSE,
        _async_edit_expense_service,
        schema=EDIT_EXPENSE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_EXPENSE,
        _async_delete_expense_service,
        schema=DELETE_EXPENSE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_EXPENSES,
        _async_list_expenses_service,
        schema=LIST_EXPENSES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
