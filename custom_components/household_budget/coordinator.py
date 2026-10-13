"""Recompute coordinator for the Household Budget integration.

A bucket's figures change on their own as expenses age out of its sliding
window, so something has to recompute them even when nothing happens. This
coordinator is that something. It does no I/O and never polls: it recomputes
when asked, and once a day at local midnight.

It also owns the edge detection for the threshold/overspent events, because
that needs the previous value of every bucket — there is no period to scope
"fired already" to.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .buckets import buckets_for_entry
from .calculations import (
    STATUS_OVER,
    STATUS_WARN,
    BucketStatus,
    compute_bucket_status,
)
from .const import EVENT_OVERSPENT, EVENT_THRESHOLD_CROSSED, SIGNAL_BUCKETS_UPDATED
from .models import Bucket

if TYPE_CHECKING:
    from . import HouseholdBudgetConfigEntry

_LOGGER = logging.getLogger(__name__)


@dataclass
class _Alarms:
    """Whether a bucket's two alert conditions were true at the last refresh."""

    overspent: bool
    threshold_crossed: bool


class HouseholdBudgetCoordinator(DataUpdateCoordinator[dict[str, BucketStatus]]):
    """Keeps every bucket's computed status up to date."""

    config_entry: HouseholdBudgetConfigEntry

    def __init__(self, hass: HomeAssistant, entry: HouseholdBudgetConfigEntry) -> None:
        """Set up the coordinator with no update interval: it is push-only."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=None,
        )
        self.buckets: dict[str, Bucket] = {}
        self._alarms: dict[str, _Alarms] = {}

    @callback
    def async_setup_midnight_refresh(self) -> None:
        """Recompute once a day at local midnight, when the window moves.

        A single timer per config entry is enough. Recomputing every bucket
        unconditionally is cheaper than tracking one timer per expense
        expiry, and it survives DST changes, suspends and clock changes.
        """
        self.config_entry.async_on_unload(
            async_track_time_change(
                self.hass, self._async_midnight_refresh, hour=0, minute=0, second=0
            )
        )

    async def _async_midnight_refresh(self, now: datetime) -> None:
        """Handle the daily tick."""
        await self.async_refresh()

    @callback
    def async_update_listeners(self) -> None:
        """Notify entities, then anyone watching the household as a whole.

        Entities come and go with this coordinator, so binding to it is
        right for them. A panel does not: writing a bucket reloads the
        config entry, which builds a new coordinator and would leave a
        panel's subscription attached to the discarded one, silently never
        pushing again. The signal is a plain string, so it outlives reloads.

        This runs after `data` is assigned, so subscribers read the figures
        that were just computed rather than the previous ones.
        """
        super().async_update_listeners()
        async_dispatcher_send(self.hass, SIGNAL_BUCKETS_UPDATED)

    async def _async_update_data(self) -> dict[str, BucketStatus]:
        """Recompute every non-archived bucket from the stored expenses."""
        today = dt_util.now().date()
        expenses = self.config_entry.runtime_data.store.data.expenses

        self.buckets = {
            bucket.id: bucket
            for bucket in buckets_for_entry(self.config_entry)
            if not bucket.archived
        }
        statuses = {
            bucket_id: compute_bucket_status(bucket, expenses, today)
            for bucket_id, bucket in self.buckets.items()
        }
        self._fire_edge_events(statuses)
        return statuses

    def _fire_edge_events(self, statuses: dict[str, BucketStatus]) -> None:
        """Fire threshold/overspent events for buckets that just crossed.

        Both events are edge-triggered and re-arm themselves: a bucket that
        comes back under its limit will fire again the next time it goes
        over. A bucket seen for the first time — at startup, or when it is
        created — is only armed, never announced, so restarting Home
        Assistant does not replay alerts for buckets that are already over.
        """
        for bucket_id, status in statuses.items():
            bucket = self.buckets[bucket_id]
            # The same classification the panel paints with, so "À surveiller"
            # and the event can never disagree. A bucket with no threshold of
            # its own warns at the default.
            alarms = _Alarms(
                overspent=status.status == STATUS_OVER,
                threshold_crossed=status.status in (STATUS_WARN, STATUS_OVER),
            )
            threshold = status.threshold_percent
            previous = self._alarms.get(bucket_id)
            self._alarms[bucket_id] = alarms

            if previous is None:
                continue

            if alarms.overspent and not previous.overspent:
                self.hass.bus.async_fire(
                    EVENT_OVERSPENT,
                    {
                        "entry_id": self.config_entry.entry_id,
                        "bucket_id": bucket_id,
                        "bucket_name": bucket.name,
                        "remaining": status.remaining / 100,
                        "remaining_cents": status.remaining,
                    },
                )
            if alarms.threshold_crossed and not previous.threshold_crossed:
                self.hass.bus.async_fire(
                    EVENT_THRESHOLD_CROSSED,
                    {
                        "entry_id": self.config_entry.entry_id,
                        "bucket_id": bucket_id,
                        "bucket_name": bucket.name,
                        "threshold": threshold,
                        "percent_used": status.percent_used,
                    },
                )
