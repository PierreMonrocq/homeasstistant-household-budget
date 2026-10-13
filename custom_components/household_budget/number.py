"""Number platform for the Household Budget integration.

A bucket's limit is a value the user sets, so it is a `number` entity with
the config entity category rather than a sensor plus a bespoke action:
`number.set_value` is all an automation needs.

The window length stays in the config flow — changing it is a structural
decision, not a dashboard control.
"""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import HouseholdBudgetConfigEntry
from .buckets import bucket_from_subentry
from .const import ATTR_LIMIT, MAX_LIMIT_MAJOR_UNITS, SUBENTRY_TYPE_BUCKET
from .coordinator import HouseholdBudgetCoordinator
from .entity import BucketEntity
from .models import Bucket


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HouseholdBudgetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the limit control for each non-archived bucket."""
    coordinator = entry.runtime_data.coordinator
    currency = entry.runtime_data.currency

    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_TYPE_BUCKET:
            continue
        bucket = bucket_from_subentry(subentry)
        if bucket.archived:
            continue

        async_add_entities(
            [BucketLimitNumber(coordinator, bucket, currency)],
            config_subentry_id=subentry.subentry_id,
        )


class BucketLimitNumber(BucketEntity, NumberEntity):
    """The amount a bucket allows over its window."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_device_class = NumberDeviceClass.MONETARY
    _attr_mode = NumberMode.BOX
    _attr_translation_key = ATTR_LIMIT
    _attr_native_min_value = 0
    _attr_native_max_value = MAX_LIMIT_MAJOR_UNITS
    _attr_native_step = 0.01

    def __init__(
        self, coordinator: HouseholdBudgetCoordinator, bucket: Bucket, currency: str
    ) -> None:
        """Set the control up, naming its unit after the household currency."""
        super().__init__(coordinator, bucket, ATTR_LIMIT)
        self._attr_native_unit_of_measurement = currency

    @property
    def native_value(self) -> float | None:
        """Return the bucket's current limit in major currency units."""
        if self._bucket_id not in self.coordinator.buckets:
            return None
        return self.bucket.limit_cents / 100

    async def async_set_native_value(self, value: float) -> None:
        """Write the new limit back to the bucket's config subentry.

        Updating a subentry notifies the config entry's update listener,
        which reloads the entry — that is what picks the new limit up
        everywhere.
        """
        entry = self.coordinator.config_entry
        subentry = next(s for s in entry.subentries.values() if s.unique_id == self._bucket_id)
        self.hass.config_entries.async_update_subentry(
            entry, subentry, data={**subentry.data, "limit_cents": round(value * 100)}
        )
