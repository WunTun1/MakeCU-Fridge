"""Next trip date + shopping list. Section 10."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from inventory.database import Database
from intelligence.consumption import days_left, grams_on_hand, usage_rate_g_per_day

NO_TRIP_NEEDED_WITHIN_DAYS = 14
DEFAULT_TRIP_CADENCE_DAYS = 7
SAFETY_BUFFER_PCT = 0.15


@dataclass
class GroceryItem:
    product_id: int
    product_name: str
    buy_grams: float
    buy_packages: int | None
    reason: str


def next_trip_date(db: Database) -> date | None:
    """Earliest date a staple runs out, minus 1 day."""
    with db.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE is_staple = 1")
        staples = cur.fetchall()

    soonest: date | None = None
    for staple in staples:
        dl = days_left(db, staple["id"])
        if dl is None:
            continue
        run_out = datetime.now(timezone.utc).date() + timedelta(days=dl)
        if soonest is None or run_out < soonest:
            soonest = run_out

    if soonest is None:
        return None
    today = datetime.now(timezone.utc).date()
    if (soonest - today).days > NO_TRIP_NEEDED_WITHIN_DAYS:
        return None
    # Something running out today means "shop today", not a date in the past.
    return max(soonest - timedelta(days=1), today)


def grocery_plan(
    db: Database, trip_in_days: int | None = None, cadence_days: int = DEFAULT_TRIP_CADENCE_DAYS
) -> list[GroceryItem]:
    trip_date = (
        datetime.now(timezone.utc).date() + timedelta(days=trip_in_days)
        if trip_in_days is not None
        else next_trip_date(db)
    )
    if trip_date is None:
        return []

    with db.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE is_staple = 1")
        staples = cur.fetchall()

    plan: list[GroceryItem] = []
    for product in staples:
        rate = usage_rate_g_per_day(db, product["id"])
        if rate <= 0:
            continue
        on_hand = grams_on_hand(db, product["id"])
        days_until_trip = max((trip_date - datetime.now(timezone.utc).date()).days, 0)
        on_hand_at_trip = max(on_hand - rate * days_until_trip, 0.0)

        needed_for_period = rate * cadence_days * (1 + SAFETY_BUFFER_PCT)
        buy_grams = max(needed_for_period - on_hand_at_trip, 0.0)
        if buy_grams <= 0:
            continue

        package_size = product["usual_package_size_g"]
        buy_packages = math.ceil(buy_grams / package_size) if package_size else None
        if buy_packages:
            buy_grams = buy_packages * package_size

        plan.append(GroceryItem(
            product_id=product["id"],
            product_name=product["name"],
            buy_grams=buy_grams,
            buy_packages=buy_packages,
            reason=f"~{on_hand_at_trip:.0f}g left by {trip_date.isoformat()}, uses ~{rate:.0f}g/day",
        ))
    return plan
