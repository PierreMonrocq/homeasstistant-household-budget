"""Mapping between bucket config subentries and the `Bucket` model.

Buckets live in config subentries, not in the data store, so this is the one
place that knows how a subentry's raw data maps to a `Bucket`. It sits in its
own module so the platforms, the services and the config flow can all import
it without going through `__init__`.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from .const import SUBENTRY_TYPE_BUCKET, VISIBILITY_SHARED
from .models import Bucket
from .store import HouseholdBudgetStore


def bucket_from_subentry(subentry: ConfigSubentry) -> Bucket:
    """Build a `Bucket` from a bucket config subentry.

    `Bucket.id` is `subentry.unique_id` (a UUID we assign ourselves when the
    bucket is created), not `subentry.subentry_id`, so a bucket keeps a
    stable id that expenses and its device identifiers can reference.
    """
    assert subentry.unique_id is not None
    data = subentry.data
    return Bucket(
        id=subentry.unique_id,
        name=subentry.title,
        icon=data.get("icon"),
        color=data.get("color"),
        period_days=data["period_days"],
        limit_cents=data["limit_cents"],
        visibility=data.get("visibility", VISIBILITY_SHARED),
        owner=data.get("owner"),
        alert_threshold_percent=data.get("alert_threshold_percent"),
        archived=data.get("archived", False),
    )


def bucket_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Return every bucket subentry of a household, archived included."""
    return [
        subentry
        for subentry in entry.subentries.values()
        if subentry.subentry_type == SUBENTRY_TYPE_BUCKET
    ]


def buckets_for_entry(entry: ConfigEntry) -> list[Bucket]:
    """Return every bucket (archived or not) configured for a household."""
    return [bucket_from_subentry(subentry) for subentry in bucket_subentries(entry)]


def subentry_for_bucket(entry: ConfigEntry, bucket_id: str) -> ConfigSubentry | None:
    """Return the subentry holding `bucket_id`, if this household has it."""
    return next(
        (s for s in bucket_subentries(entry) if s.unique_id == bucket_id),
        None,
    )


def bucket_has_records(store: HouseholdBudgetStore, bucket_id: str) -> bool:
    """Return True if any expense references this bucket."""
    return any(e.bucket_id == bucket_id for e in store.data.expenses)


BUCKET_SUBENTRY_FIELDS = (
    "icon",
    "color",
    "period_days",
    "limit_cents",
    "visibility",
    "owner",
    "alert_threshold_percent",
    "archived",
)


def new_bucket_subentry_data(
    *,
    period_days: int,
    limit_cents: int,
    visibility: str = VISIBILITY_SHARED,
    owner: str | None = None,
    icon: str | None = None,
    color: str | None = None,
    alert_threshold_percent: int | None = None,
) -> dict[str, object]:
    """Build the subentry data for a new bucket.

    One place defines the shape a bucket subentry has, so the management
    panel cannot drift from what `bucket_from_subentry` expects to read. The
    name is not here: it is the subentry title.
    """
    return {
        "icon": icon,
        "color": color,
        "period_days": period_days,
        "limit_cents": limit_cents,
        "visibility": visibility,
        "owner": owner,
        "alert_threshold_percent": alert_threshold_percent,
        "archived": False,
    }
