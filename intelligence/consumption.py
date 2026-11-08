"""Usage rates and days-left, from plain event history. No ML. See
ReFridge_Architecture.md section 10.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

from intelligence import clock
from inventory.database import Database

HALF_LIFE_DAYS_DEFAULT = 7.0
USAGE_EVENT_TYPES = {"consume", "remove"}   # counts as eaten/used
RETURN_EVENT_TYPE = "return"                # cancels out a prior removal
# "waste" is intentionally excluded — spoiled food isn't "usage".


def grams_on_hand(db: Database, product_id: int) -> float:
    items = db.active_items()
    return sum(i["grams"] for i in items if i["product_id"] == product_id)


def daily_usage(db: Database, product_id: int, days: int = 30) -> dict[str, float]:
    """grams consumed + removed - returned, bucketed by calendar day."""
    since = (clock.utc_now() - timedelta(days=days)).isoformat()
    events = db.events_for_product(product_id, since=since)
    by_day: dict[str, float] = defaultdict(float)
    for e in events:
        day = clock.local_date(e["occurred_at"]).isoformat()
        if e["event_type"] in USAGE_EVENT_TYPES:
            by_day[day] += -e["grams_delta"]  # grams_delta is negative for usage
        elif e["event_type"] == RETURN_EVENT_TYPE:
            by_day[day] -= e["grams_delta"]
    return dict(by_day)


def usage_rate_g_per_day(
    db: Database, product_id: int, half_life_days: float = HALF_LIFE_DAYS_DEFAULT, lookback_days: int = 30
) -> float:
    """Exponentially-weighted average daily usage — recent days count more.
    Adapts to changing habits without needing a model."""
    usage = daily_usage(db, product_id, days=lookback_days)
    if not usage:
        return 0.0
    today = clock.local_today()
    decay = math.log(2) / half_life_days
    weighted_sum = 0.0
    weight_total = 0.0
    for day_str, grams in usage.items():
        age_days = (today - date.fromisoformat(day_str)).days
        w = math.exp(-decay * age_days)
        weighted_sum += grams * w
        weight_total += w
    # Normalize against lookback window (not just days with activity) so a
    # product used once a week doesn't look like it's used every day.
    span = max((today - date.fromisoformat(min(usage.keys()))).days + 1, 1)
    span = min(span, lookback_days)
    return (weighted_sum / weight_total) * (len(usage) / span) if weight_total else 0.0


def days_left(db: Database, product_id: int, half_life_days: float = HALF_LIFE_DAYS_DEFAULT) -> float | None:
    on_hand = grams_on_hand(db, product_id)
    rate = usage_rate_g_per_day(db, product_id, half_life_days)
    if rate <= 0:
        return None  # no usage history -> can't forecast
    return on_hand / rate
