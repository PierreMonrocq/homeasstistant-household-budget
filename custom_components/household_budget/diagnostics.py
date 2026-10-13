"""Diagnostics support for the Household Budget integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import HouseholdBudgetConfigEntry
from .buckets import buckets_for_entry

# A description says where someone shopped and a user id says who they are.
# Diagnostics get downloaded and pasted into issues, so neither goes in.
TO_REDACT = {"description", "created_by", "owner"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HouseholdBudgetConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data.coordinator
    store = entry.runtime_data.store

    buckets = []
    for bucket in buckets_for_entry(entry):
        status = coordinator.data.get(bucket.id) if coordinator.data else None
        buckets.append(
            async_redact_data(
                {
                    "id": bucket.id,
                    "period_days": bucket.period_days,
                    "limit_cents": bucket.limit_cents,
                    "visibility": bucket.visibility,
                    "owner": bucket.owner,
                    "alert_threshold_percent": bucket.alert_threshold_percent,
                    "archived": bucket.archived,
                    "expense_count": len(store.expenses_for_bucket(bucket.id)),
                    "status": None
                    if status is None
                    else {
                        "window_start": status.window.start.isoformat(),
                        "window_end": status.window.end.isoformat(),
                        "spent": status.spent,
                        "remaining": status.remaining,
                        "percent_used": status.percent_used,
                        "next_release_date": (
                            status.next_release_date.isoformat()
                            if status.next_release_date
                            else None
                        ),
                        "next_release_amount": status.next_release_amount,
                    },
                },
                TO_REDACT,
            )
        )

    return {
        "currency": entry.runtime_data.currency,
        "expense_count": len(store.data.expenses),
        "buckets": buckets,
        "expenses": [
            async_redact_data(
                {
                    "id": expense.id,
                    "bucket_id": expense.bucket_id,
                    "amount_cents": expense.amount_cents,
                    "date": expense.date.isoformat(),
                    "description": expense.description,
                    "created_by": expense.created_by,
                    "created_at": expense.created_at,
                    "updated_at": expense.updated_at,
                },
                TO_REDACT,
            )
            for expense in store.data.expenses
        ],
    }
