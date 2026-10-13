"""Unit tests for the pure sliding-window calculation logic.

These tests import `calculations` and `models` directly (no Home Assistant
fixtures) since both modules are plain Python.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from custom_components.household_budget.calculations import (
    Window,
    compute_bucket_status,
    percent_used,
    release_date,
    window_for,
)
from custom_components.household_budget.models import Bucket, Expense


def make_bucket(**overrides) -> Bucket:
    """A Courses-like bucket: 30-day window, 500 EUR limit."""
    defaults = dict(
        id="courses",
        name="Courses",
        icon=None,
        color=None,
        period_days=30,
        limit_cents=50_000,
    )
    defaults.update(overrides)
    return Bucket(**defaults)


def make_expense(
    bucket_id: str, amount_cents: int, expense_date: date, expense_id: str | None = None
) -> Expense:
    return Expense(
        id=expense_id or f"e-{bucket_id}-{expense_date.isoformat()}-{amount_cents}",
        bucket_id=bucket_id,
        amount_cents=amount_cents,
        date=expense_date,
        created_by="user1",
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:00+00:00",
    )


# --- Worked example from the spec -------------------------------------------
# Courses: period_days = 30, limit = 500 EUR, one expense of 200 EUR on 15 Sep.
#
# | Day          | Window          | Spent | Remaining |
# |--------------|-----------------|-------|-----------|
# | 15 September | 17 Aug - 15 Sep | 200   | 300       |
# | 14 October   | 15 Sep - 14 Oct | 200   | 300       |
# | 15 October   | 16 Sep - 15 Oct | 0     | 500       |


def test_courses_worked_example():
    bucket = make_bucket()
    expenses = [make_expense(bucket.id, 20_000, date(2025, 9, 15))]

    on_the_day = compute_bucket_status(bucket, expenses, today=date(2025, 9, 15))
    assert on_the_day.window == Window(date(2025, 8, 17), date(2025, 9, 15))
    assert on_the_day.spent == 20_000
    assert on_the_day.remaining == 30_000

    last_counted_day = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))
    assert last_counted_day.window == Window(date(2025, 9, 15), date(2025, 10, 14))
    assert last_counted_day.spent == 20_000
    assert last_counted_day.remaining == 30_000

    release_day = compute_bucket_status(bucket, expenses, today=date(2025, 10, 15))
    assert release_day.window == Window(date(2025, 9, 16), date(2025, 10, 15))
    assert release_day.spent == 0
    assert release_day.remaining == 50_000


def test_the_money_is_announced_as_released_on_the_right_day():
    bucket = make_bucket()
    expenses = [make_expense(bucket.id, 20_000, date(2025, 9, 15))]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 9, 15))

    assert status.next_release_date == date(2025, 10, 15)
    assert status.next_release_amount == 20_000
    assert release_date(bucket, expenses[0]) == date(2025, 10, 15)


# --- Window shape ------------------------------------------------------------


def test_window_is_period_days_long_and_includes_today():
    window = window_for(make_bucket(period_days=30), today=date(2025, 10, 14))

    assert window == Window(date(2025, 9, 15), date(2025, 10, 14))
    assert (window.end - window.start).days + 1 == 30


def test_one_day_bucket_counts_today_only():
    bucket = make_bucket(period_days=1)
    today = date(2025, 10, 14)
    expenses = [
        make_expense(bucket.id, 1_000, today),
        make_expense(bucket.id, 5_000, date(2025, 10, 13)),
    ]

    assert window_for(bucket, today) == Window(today, today)
    assert compute_bucket_status(bucket, expenses, today).spent == 1_000


def test_both_window_bounds_are_inclusive():
    bucket = make_bucket()
    today = date(2025, 10, 14)
    window = window_for(bucket, today)
    expenses = [
        make_expense(bucket.id, 1_00, window.start - timedelta(days=1)),
        make_expense(bucket.id, 2_00, window.start),
        make_expense(bucket.id, 4_00, today),
    ]

    # Only the two inside the window count.
    assert compute_bucket_status(bucket, expenses, today).spent == 6_00


def test_period_days_must_be_at_least_one():
    with pytest.raises(ValueError, match="period_days"):
        window_for(make_bucket(period_days=0), today=date(2025, 10, 14))


# --- Spending ----------------------------------------------------------------


def test_overspending_gives_a_negative_remaining():
    bucket = make_bucket()
    expenses = [
        make_expense(bucket.id, 48_000, date(2025, 10, 1)),
        make_expense(bucket.id, 7_500, date(2025, 10, 10)),
    ]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))

    assert status.spent == 55_500
    assert status.remaining == -5_500
    assert status.percent_used == pytest.approx(111.0)


def test_future_dated_expense_is_not_counted_yet():
    bucket = make_bucket()
    expenses = [make_expense(bucket.id, 10_000, date(2025, 10, 20))]

    today = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))
    assert today.spent == 0
    assert today.next_release_date is None

    once_due = compute_bucket_status(bucket, expenses, today=date(2025, 10, 20))
    assert once_due.spent == 10_000


def test_backdated_expense_outside_the_window_is_ignored():
    bucket = make_bucket()
    expenses = [make_expense(bucket.id, 10_000, date(2025, 1, 5))]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))

    assert status.spent == 0
    assert status.remaining == 50_000


def test_backdated_expense_inside_the_window_counts_immediately():
    bucket = make_bucket()
    today = date(2025, 10, 14)

    before = compute_bucket_status(bucket, [], today)
    assert before.spent == 0

    backdated = [make_expense(bucket.id, 10_000, date(2025, 10, 2))]
    after = compute_bucket_status(bucket, backdated, today)
    assert after.spent == 10_000
    assert after.remaining == 40_000


def test_deleting_an_expense_corrects_the_figures():
    bucket = make_bucket()
    today = date(2025, 10, 14)
    expenses = [
        make_expense(bucket.id, 10_000, date(2025, 10, 2)),
        make_expense(bucket.id, 5_000, date(2025, 10, 9)),
    ]

    assert compute_bucket_status(bucket, expenses, today).spent == 15_000
    assert compute_bucket_status(bucket, expenses[1:], today).spent == 5_000


def test_empty_bucket_has_its_whole_limit_available():
    status = compute_bucket_status(make_bucket(), [], today=date(2025, 10, 14))

    assert status.spent == 0
    assert status.remaining == 50_000
    assert status.percent_used == 0
    assert status.next_release_date is None
    assert status.next_release_amount == 0


def test_buckets_are_isolated_from_each_other():
    courses = make_bucket()
    lunch = make_bucket(id="lunch", name="Lunch & Snack", period_days=90, limit_cents=12_000)
    expenses = [
        make_expense(courses.id, 20_000, date(2025, 10, 1)),
        make_expense(lunch.id, 3_000, date(2025, 10, 1)),
    ]
    today = date(2025, 10, 14)

    assert compute_bucket_status(courses, expenses, today).spent == 20_000
    assert compute_bucket_status(lunch, expenses, today).spent == 3_000


# --- Refunds (negative expenses) ---------------------------------------------


def test_refund_reduces_spent_then_ages_out_on_its_own_schedule():
    bucket = make_bucket()
    expenses = [
        make_expense(bucket.id, 20_000, date(2025, 9, 20)),
        make_expense(bucket.id, -5_000, date(2025, 9, 25)),
    ]

    with_refund = compute_bucket_status(bucket, expenses, today=date(2025, 10, 1))
    assert with_refund.spent == 15_000
    assert with_refund.remaining == 35_000

    # The 200 EUR expense releases first (20 Oct), leaving the refund alone:
    # spending goes back up, so the bucket shows more than its limit.
    assert with_refund.next_release_date == date(2025, 10, 20)
    assert with_refund.next_release_amount == 20_000

    after_expense_released = compute_bucket_status(bucket, expenses, today=date(2025, 10, 20))
    assert after_expense_released.spent == -5_000
    assert after_expense_released.remaining == 55_000

    after_both_released = compute_bucket_status(bucket, expenses, today=date(2025, 10, 25))
    assert after_both_released.spent == 0
    assert after_both_released.remaining == 50_000


def test_a_refund_releasing_first_is_reported_as_a_negative_release():
    bucket = make_bucket()
    expenses = [
        make_expense(bucket.id, -5_000, date(2025, 9, 20)),
        make_expense(bucket.id, 20_000, date(2025, 9, 25)),
    ]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 1))

    assert status.next_release_date == date(2025, 10, 20)
    assert status.next_release_amount == -5_000


# --- next_release ------------------------------------------------------------


def test_next_release_sums_every_expense_of_the_same_day():
    bucket = make_bucket()
    expenses = [
        make_expense(bucket.id, 3_000, date(2025, 9, 20), expense_id="a"),
        make_expense(bucket.id, 4_500, date(2025, 9, 20), expense_id="b"),
        make_expense(bucket.id, 1_000, date(2025, 9, 28), expense_id="c"),
    ]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 1))

    assert status.spent == 8_500
    assert status.next_release_date == date(2025, 10, 20)
    assert status.next_release_amount == 7_500


# --- Reconfiguration ---------------------------------------------------------


def test_changing_period_days_recomputes_immediately():
    lunch = make_bucket(id="lunch", name="Lunch & Snack", period_days=90, limit_cents=12_000)
    expenses = [make_expense(lunch.id, 4_000, date(2025, 8, 20))]
    today = date(2025, 10, 1)

    assert compute_bucket_status(lunch, expenses, today).spent == 4_000

    # Shrinking the window to 30 days drops the August expense out of it.
    shortened = replace(lunch, period_days=30)
    assert compute_bucket_status(shortened, expenses, today).spent == 0


def test_changing_the_limit_changes_remaining_with_no_history_to_preserve():
    bucket = make_bucket()
    expenses = [make_expense(bucket.id, 20_000, date(2025, 10, 1))]
    today = date(2025, 10, 14)

    assert compute_bucket_status(bucket, expenses, today).remaining == 30_000

    raised = replace(bucket, limit_cents=60_000)
    assert compute_bucket_status(raised, expenses, today).remaining == 40_000


# --- percent_used ------------------------------------------------------------


def test_percent_used_values():
    assert percent_used(limit=50_000, spent=20_000) == pytest.approx(40)
    assert percent_used(limit=50_000, spent=55_000) == pytest.approx(110)
    assert percent_used(limit=50_000, spent=-5_000) == pytest.approx(-10)
    assert percent_used(limit=0, spent=0) is None


def test_limit_of_zero_has_no_percentage():
    bucket = make_bucket(limit_cents=0)
    expenses = [make_expense(bucket.id, 1_000, date(2025, 10, 10))]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))

    assert status.spent == 1_000
    assert status.remaining == -1_000
    assert status.percent_used is None


# --- Status, released soon, recovery date -----------------------------------


def test_status_classifies_ok_warn_and_over():
    bucket = make_bucket(alert_threshold_percent=80)
    today = date(2025, 10, 14)

    def status_with(cents):
        expenses = [make_expense(bucket.id, cents, date(2025, 10, 1))]
        return compute_bucket_status(bucket, expenses, today)

    assert status_with(20_000).status == "ok"
    assert status_with(39_900).status == "ok"
    # 80 % of 500 EUR, the threshold itself: warn starts here, inclusive.
    assert status_with(40_000).status == "warn"
    assert status_with(50_001).status == "over"


def test_a_bucket_at_exactly_its_limit_is_not_over():
    bucket = make_bucket(alert_threshold_percent=80)
    expenses = [make_expense(bucket.id, 50_000, date(2025, 10, 1))]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))

    assert status.remaining == 0
    assert status.status == "warn"


def test_the_default_threshold_applies_without_one_configured():
    bucket = make_bucket()
    expenses = [make_expense(bucket.id, 40_000, date(2025, 10, 1))]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))

    assert status.threshold_percent == 80
    assert status.status == "warn"


def test_a_bucket_with_no_limit_is_over_as_soon_as_anything_is_in_it():
    bucket = make_bucket(limit_cents=0)
    expenses = [make_expense(bucket.id, 1_000, date(2025, 10, 1))]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))

    # No percentage exists, but the money says it is over.
    assert status.percent_used is None
    assert status.status == "over"


def test_released_soon_only_counts_the_next_seven_days():
    bucket = make_bucket()
    today = date(2025, 10, 14)
    expenses = [
        # Releases 15 Oct, tomorrow: inside the horizon.
        make_expense(bucket.id, 10_000, date(2025, 9, 15), expense_id="tomorrow"),
        # Releases 21 Oct, in seven days: the last day that counts.
        make_expense(bucket.id, 5_000, date(2025, 9, 21), expense_id="in_seven"),
        # Releases 22 Oct, in eight days: outside.
        make_expense(bucket.id, 3_000, date(2025, 9, 22), expense_id="in_eight"),
    ]

    status = compute_bucket_status(bucket, expenses, today)

    assert status.released_soon == 15_000


def test_released_soon_is_zero_for_an_empty_window():
    status = compute_bucket_status(make_bucket(), [], today=date(2025, 10, 14))

    assert status.released_soon == 0


def test_recovery_date_is_when_ageing_brings_it_back_under():
    bucket = make_bucket()
    today = date(2025, 10, 14)
    # 600 EUR in a 500 EUR bucket: 100 over.
    expenses = [
        make_expense(bucket.id, 15_000, date(2025, 9, 20), expense_id="oldest"),
        make_expense(bucket.id, 25_000, date(2025, 10, 1), expense_id="middle"),
        make_expense(bucket.id, 20_000, date(2025, 10, 10), expense_id="newest"),
    ]

    status = compute_bucket_status(bucket, expenses, today)

    assert status.remaining == -10_000
    assert status.status == "over"
    # Dropping the oldest (150 EUR) leaves 450 EUR, under the limit, and it
    # leaves the window on 20 September + 30 days.
    assert status.recovery_date == date(2025, 10, 20)


def test_recovery_date_walks_several_expenses_when_one_is_not_enough():
    bucket = make_bucket()
    today = date(2025, 10, 14)
    expenses = [
        make_expense(bucket.id, 5_000, date(2025, 9, 20), expense_id="small"),
        make_expense(bucket.id, 30_000, date(2025, 9, 25), expense_id="big"),
        make_expense(bucket.id, 25_000, date(2025, 10, 10), expense_id="recent"),
    ]

    status = compute_bucket_status(bucket, expenses, today)

    assert status.remaining == -10_000
    # Dropping the 50 EUR one is not enough (still 550); the 300 EUR one has
    # to go too, and it leaves on 25 September + 30 days.
    assert status.recovery_date == date(2025, 10, 25)


def test_a_healthy_bucket_has_no_recovery_date():
    bucket = make_bucket()
    expenses = [make_expense(bucket.id, 20_000, date(2025, 10, 1))]

    status = compute_bucket_status(bucket, expenses, today=date(2025, 10, 14))

    assert status.recovery_date is None
