"""Low / out / expiring alerts. Section 10."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from inventory.database import Database
from intelligence import clock, conditions
from intelligence.consumption import days_left
from intelligence.expiry import days_until, describe_expiry

DAYS_LEFT_THRESHOLD = 3
LOW_PACKAGE_FRACTION = 0.20
EXPIRING_SOON_DAYS = 3  # the same window the app colors amber or red
LEFTOVERS_ALERT_DAYS = 1  # fresh leftovers are no alarm until they keep only until tomorrow
FRIDGE_TEMP_ALERT_C = 7.0          # above this, food safety is at risk
CONDITION_STALE_MINUTES = 30       # a reading older than this isn't trusted


# Most urgent first; each product keeps only its most urgent alert.
URGENCY = ["fridge_temp_high", "expiring_soon", "staple_out", "low_days_left", "low_fraction"]


@dataclass
class Alert:
    product_id: int | None
    product_name: str
    reason: str   # low_days_left|low_fraction|staple_out|expiring_soon|fridge_temp_high
    detail: str
    days: float | None = None   # days until it goes bad (expiring_soon) or runs out (low_days_left)


def _expiring_soon_items(db: Database):
    """(item, product) pairs inside the alert window; leftovers only from the day before they go."""
    for item in db.active_items():
        if not item["expiration_date"] or item["location"] == "freezer":
            continue
        product = db.get_product(item["product_id"])
        if product is None:
            continue
        window = LEFTOVERS_ALERT_DAYS if product["recipe_id"] is not None else EXPIRING_SOON_DAYS
        if days_until(item["expiration_date"]) <= window:
            yield item, product


def low_stock_alerts(db: Database) -> list[Alert]:
    alerts: list[Alert] = []
    seen_products: set[int] = set()

    products_on_hand: dict[int, float] = {}
    outside_freezer: dict[int, float] = {}  # frozen food keeps for months: no "running low" nudges
    for item in db.active_items():
        products_on_hand[item["product_id"]] = products_on_hand.get(item["product_id"], 0.0) + item["grams"]
        if item["location"] != "freezer":
            outside_freezer[item["product_id"]] = outside_freezer.get(item["product_id"], 0.0) + item["grams"]

    for product_id, on_hand in outside_freezer.items():
        product = db.get_product(product_id)
        if product is None or product["recipe_id"] is not None:  # leftovers are never restocked
            continue
        dl = days_left(db, product_id)
        if dl is not None and dl <= DAYS_LEFT_THRESHOLD:
            alerts.append(Alert(product_id, product["name"], "low_days_left",
                                 f"runs out in about {max(round(dl), 1)} days" if dl >= 1 else "runs out today", dl))
            seen_products.add(product_id)
        if product["usual_package_size_g"] and on_hand < product["usual_package_size_g"] * LOW_PACKAGE_FRACTION:
            if product_id not in seen_products:
                alerts.append(Alert(product_id, product["name"], "low_fraction",
                                     f"{on_hand:.0f}g left of a {product['usual_package_size_g']:.0f}g package"))
                seen_products.add(product_id)

    # Staples that are completely out
    with db.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE is_staple = 1")
        staples = cur.fetchall()
    for staple in staples:
        if staple["id"] not in products_on_hand and staple["id"] not in seen_products:
            alerts.append(Alert(staple["id"], staple["name"], "staple_out", "staple is out"))
            seen_products.add(staple["id"])

    for item, product in _expiring_soon_items(db):
        alerts.append(Alert(product["id"], product["name"], "expiring_soon",
                             describe_expiry(item["expiration_date"], bool(item["expiration_estimated"])),
                             days_until(item["expiration_date"])))

    temp_alert = _fridge_temp_alert(db)
    if temp_alert:
        alerts.append(temp_alert)

    return _most_urgent_per_product(alerts)


def _most_urgent_per_product(alerts: list[Alert]) -> list[Alert]:
    ranked = sorted(alerts, key=lambda a: (URGENCY.index(a.reason), a.days if a.days is not None else 0))
    kept: list[Alert] = []
    seen: set[int] = set()
    for alert in ranked:
        if alert.product_id is not None:
            if alert.product_id in seen:
                continue
            seen.add(alert.product_id)
        kept.append(alert)
    return kept


def _fridge_temp_alert(db: Database) -> Alert | None:
    """Reads the Pi's Grove barometer (temperature) — a real fridge-health
    check, distinct from inventory alerts."""
    reading = conditions.latest(db)  # demo numbers too, with DEMO_CONDITIONS=on
    if reading is None or reading["temperature_c"] is None:
        return None
    age = clock.utc_now() - datetime.fromisoformat(reading["occurred_at"])
    if age > timedelta(minutes=CONDITION_STALE_MINUTES):
        return None
    if reading["temperature_c"] > FRIDGE_TEMP_ALERT_C:
        return Alert(None, "Fridge", "fridge_temp_high",
                     f"{reading['temperature_c']:.1f}°C — check the door and power")
    return None
