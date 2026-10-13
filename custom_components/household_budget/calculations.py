"""Pure sliding-window calculation logic.

No Home Assistant imports here — this module is plain Python so it is
trivial to unit test. Every value is derived from the stored expenses;
nothing is cached as a source of truth.

A bucket counts the expenses of the last `period_days` days, today included.
An expense therefore counts against its bucket for exactly `period_days`
days starting on its own date, and frees up on `date + period_days`: with a
30-day window, an expense dated 15 September is counted through 14 October
and releases on 15 October.

There are no periods, no boundaries and no carry-over: the window simply
moves forward one day at a time, which is why the figures change on their own
at every local midnight even when no expense is touched.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .models import Bucket, Expense


@dataclass(frozen=True)
class Window:
    """The closed date range `[start, end]` a bucket currently counts."""

    start: date
    end: date

    def contains(self, day: date) -> bool:
        """Whether `day` falls inside the window (both bounds inclusive)."""
        return self.start <= day <= self.end


# A bucket at or past this share of its limit reads as "to watch" when it has
# no threshold of its own. The panel's "À surveiller" section and the
# threshold event both use the effective threshold, so what the UI warns about
# and what fires an event cannot disagree.
DEFAULT_ALERT_THRESHOLD_PERCENT = 80

# How far ahead "freed soon" looks, in days.
RELEASE_HORIZON_DAYS = 7

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_OVER = "over"


@dataclass(frozen=True)
class BucketStatus:
    """The computed figures for one bucket on one given day."""

    window: Window
    limit: int
    spent: int
    remaining: int
    percent_used: float | None
    next_release_date: date | None
    next_release_amount: int
    status: str
    threshold_percent: int
    released_soon: int
    recovery_date: date | None


def window_for(bucket: Bucket, today: date) -> Window:
    """Return the sliding window `bucket` counts on `today`.

    The window is `period_days` long and ends on `today`, so a one-day
    bucket counts today only.
    """
    if bucket.period_days < 1:
        raise ValueError(f"period_days must be >= 1, got {bucket.period_days}")
    return Window(start=today - timedelta(days=bucket.period_days - 1), end=today)


def release_date(bucket: Bucket, expense: Expense) -> date:
    """Return the first day `expense` no longer counts against `bucket`."""
    return expense.date + timedelta(days=bucket.period_days)


def expenses_in_window(bucket: Bucket, expenses: list[Expense], window: Window) -> list[Expense]:
    """Return the bucket's expenses dated inside `window`.

    Expenses dated in the future fall outside the window, so they are not
    counted until their day arrives.
    """
    return [e for e in expenses if e.bucket_id == bucket.id and window.contains(e.date)]


def percent_used(limit: int, spent: int) -> float | None:
    """Percentage of the bucket's limit consumed by `spent`.

    Returns `None` when the limit is 0 (nothing to compute a percentage of).
    Values above 100 mean overspending, and refunds can push this negative;
    neither is clamped, both are meaningful.
    """
    if limit == 0:
        return None
    return (spent / limit) * 100


def _next_release(bucket: Bucket, in_window: list[Expense]) -> tuple[date | None, int]:
    """Return the next day expenses age out, and the total amount leaving then.

    The amount is the sum of the `amount_cents` that stop being counted, so
    `spent` drops by it on that day. It is negative when what ages out is a
    refund, which makes `spent` go back up.
    """
    if not in_window:
        return None, 0
    soonest = min(release_date(bucket, e) for e in in_window)
    amount = sum(e.amount_cents for e in in_window if release_date(bucket, e) == soonest)
    return soonest, amount


def effective_threshold(bucket: Bucket) -> int:
    """The percentage at which a bucket starts warning."""
    return bucket.alert_threshold_percent or DEFAULT_ALERT_THRESHOLD_PERCENT


def status_for(bucket: Bucket, percent: float | None, remaining: int) -> str:
    """Classify a bucket as ok / warn / over.

    `over` is decided on the money, not the percentage, so a bucket with no
    limit at all still reads as overspent once anything is in it.
    """
    if remaining < 0:
        return STATUS_OVER
    if percent is not None and percent >= effective_threshold(bucket):
        return STATUS_WARN
    return STATUS_OK


def released_soon(
    bucket: Bucket,
    in_window: list[Expense],
    today: date,
    *,
    horizon_days: int = RELEASE_HORIZON_DAYS,
) -> int:
    """Total amount that ages out of the window within the next `horizon_days`.

    This is the "money coming back" figure: what the bucket gets back without
    anyone doing anything, just by time passing.
    """
    return sum(
        e.amount_cents for e in in_window if (release_date(bucket, e) - today).days <= horizon_days
    )


def recovery_date(bucket: Bucket, in_window: list[Expense], today: date, spent: int) -> date | None:
    """When an overspent bucket comes back under its limit on its own.

    Walk the in-window expenses from the oldest, dropping them one by one as
    they will age out, until what is left fits under the limit; the answer is
    the day the last one dropped leaves the window. Returns `None` for a
    bucket that is not over, and for one that cannot recover from ageing
    alone — which happens when refunds in the window are what keep it afloat.
    """
    if bucket.limit_cents - spent >= 0:
        return None

    still_counted = spent
    for expense in sorted(in_window, key=lambda e: e.date):
        still_counted -= expense.amount_cents
        if bucket.limit_cents - still_counted >= 0:
            return release_date(bucket, expense)
    return None


def compute_bucket_status(bucket: Bucket, expenses: list[Expense], today: date) -> BucketStatus:
    """Compute a bucket's spent / remaining figures as of `today`.

    `expenses` may be the household's whole list; expenses of other buckets
    are filtered out.
    """
    window = window_for(bucket, today)
    in_window = expenses_in_window(bucket, expenses, window)
    spent = sum(e.amount_cents for e in in_window)
    remaining = bucket.limit_cents - spent
    percent = percent_used(bucket.limit_cents, spent)
    next_release_date, next_release_amount = _next_release(bucket, in_window)

    return BucketStatus(
        window=window,
        limit=bucket.limit_cents,
        spent=spent,
        remaining=remaining,
        percent_used=percent,
        next_release_date=next_release_date,
        next_release_amount=next_release_amount,
        status=status_for(bucket, percent, remaining),
        threshold_percent=effective_threshold(bucket),
        released_soon=released_soon(bucket, in_window, today),
        recovery_date=recovery_date(bucket, in_window, today, spent),
    )
