"""Sensor platform for the Household Budget integration.

Four sensors per bucket. The bucket's limit is not here: it is a `number`
entity, since it is a value the user sets rather than one we measure.

Values come from the coordinator, which recomputes when an expense changes
and once a day at local midnight — the sliding window moves on its own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.util import dt as dt_util

from . import HouseholdBudgetConfigEntry
from .buckets import bucket_from_subentry
from .calculations import BucketStatus
from .const import SUBENTRY_TYPE_BUCKET
from .coordinator import HouseholdBudgetCoordinator
from .entity import BucketEntity
from .models import Bucket


def _as_major_units(cents: int) -> float:
    return cents / 100


def _at_local_midnight(day: date | None) -> datetime | None:
    """Turn a release date into the timestamp the money actually frees up."""
    if day is None:
        return None
    return dt_util.start_of_local_day(day)


@dataclass(frozen=True, kw_only=True)
class BucketSensorDescription(SensorEntityDescription):
    """Describes one of a bucket's sensors."""

    value_fn: Callable[[BucketStatus], StateType | datetime]
    monetary: bool = False


SENSORS: tuple[BucketSensorDescription, ...] = (
    BucketSensorDescription(
        key="remaining",
        translation_key="remaining",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        monetary=True,
        value_fn=lambda status: _as_major_units(status.remaining),
    ),
    BucketSensorDescription(
        key="spent",
        translation_key="spent",
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        monetary=True,
        value_fn=lambda status: _as_major_units(status.spent),
    ),
    BucketSensorDescription(
        key="percent_used",
        translation_key="percent_used",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda status: status.percent_used,
    ),
    BucketSensorDescription(
        key="next_release",
        translation_key="next_release",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda status: _at_local_midnight(status.next_release_date),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseholdBudgetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one device worth of sensors per non-archived bucket."""
    coordinator = entry.runtime_data.coordinator
    currency = entry.runtime_data.currency

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_BUCKET:
            continue
        bucket = bucket_from_subentry(subentry)
        if bucket.archived:
            continue

        async_add_entities(
            [BucketSensor(coordinator, bucket, description, currency) for description in SENSORS],
            config_subentry_id=subentry.subentry_id,
        )


class BucketSensor(BucketEntity, SensorEntity):
    """One computed figure for one bucket."""

    entity_description: BucketSensorDescription

    def __init__(
        self,
        coordinator: HouseholdBudgetCoordinator,
        bucket: Bucket,
        description: BucketSensorDescription,
        currency: str,
    ) -> None:
        """Set the sensor up, naming its unit after the household currency."""
        super().__init__(coordinator, bucket, description.key)
        self.entity_description = description
        if description.monetary:
            self._attr_native_unit_of_measurement = currency
        if description.key == "remaining" and bucket.icon:
            self._attr_icon = bucket.icon

    @property
    def native_value(self) -> StateType | datetime:
        """Return the figure, or None (unknown) if the bucket is gone."""
        status = self.coordinator.data.get(self._bucket_id)
        if status is None:
            return None
        return self.entity_description.value_fn(status)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose the window and the computed verdict on the main sensor.

        `status`, `threshold_percent`, `released_soon` and `recovery_date`
        are here so a template — a Jinja gauge in the iOS companion app, a
        card, an automation — can render the same verdict the panel shows
        without recomputing it. The rule the panel follows applies to them
        too: format these figures, never derive them.

        Bounded scalars only — never the list of expenses, which has no size
        limit and does not belong in a state.
        """
        if self.entity_description.key != "remaining":
            return None
        status = self.coordinator.data.get(self._bucket_id)
        if status is None:
            return None

        bucket = self.bucket
        recovery = status.recovery_date
        return {
            "window_start": status.window.start.isoformat(),
            "window_end": status.window.end.isoformat(),
            "period_days": bucket.period_days,
            "next_release_amount": _as_major_units(status.next_release_amount),
            "released_soon": _as_major_units(status.released_soon),
            "recovery_date": recovery.isoformat() if recovery is not None else None,
            "status": status.status,
            "threshold_percent": status.threshold_percent,
            "visibility": bucket.visibility,
            "owner": bucket.owner,
        }
