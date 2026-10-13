"""Data models for the Household Budget integration.

Plain dataclasses, no Home Assistant imports, so they can be shared freely
between the storage layer and the pure calculation layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

type Visibility = Literal["shared", "personal"]


@dataclass
class Bucket:
    """A spending bucket: a sliding window of days with a spending limit.

    A bucket is defined by just `period_days` and `limit_cents`: the sum of
    its expenses over the last `period_days` days should stay under
    `limit_cents`. Nothing is anchored to a start date, so every field can be
    changed at any time — the current window is simply recomputed.
    """

    id: str
    name: str
    icon: str | None
    color: str | None
    period_days: int
    limit_cents: int
    visibility: Visibility = "shared"
    owner: str | None = None
    alert_threshold_percent: int | None = None
    archived: bool = False


@dataclass
class Expense:
    """A single expense charged to a bucket.

    `amount_cents` may be negative: that is how refunds and corrections are
    recorded. A negative expense ages out of the window like any other.
    """

    id: str
    bucket_id: str
    amount_cents: int
    date: date
    created_by: str | None
    created_at: str
    updated_at: str
    description: str | None = None


@dataclass
class HouseholdBudgetStoreData:
    """Everything persisted in the `Store` for a household."""

    expenses: list[Expense] = field(default_factory=list)
