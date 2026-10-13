"""Shared entity base for the Household Budget integration.

Every entity belongs to exactly one bucket, and every bucket is one HA
device — which is also what actions target.
"""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HouseholdBudgetCoordinator
from .models import Bucket


class BucketEntity(CoordinatorEntity[HouseholdBudgetCoordinator]):
    """Base entity for a single bucket."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HouseholdBudgetCoordinator, bucket: Bucket, key: str) -> None:
        """Attach the entity to its bucket's device."""
        super().__init__(coordinator)
        self._bucket_id = bucket.id
        self._attr_unique_id = f"{bucket.id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, bucket.id)},
            name=bucket.name,
            manufacturer="Household Budget",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def bucket(self) -> Bucket:
        """The bucket this entity reports on, as of the last refresh.

        Read from the coordinator rather than captured at setup, so an edited
        bucket is picked up without the entity going stale.
        """
        return self.coordinator.buckets[self._bucket_id]

    @property
    def available(self) -> bool:
        """Unavailable once the bucket is gone or archived."""
        return super().available and self._bucket_id in self.coordinator.buckets
