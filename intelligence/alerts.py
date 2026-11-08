"""Low / out / expiring alerts. Section 10."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from inventory.database import Database
from intelligence.consumption import days_left
from intelligence.expiry import describe_expiry, local_today

DAYS_LEFT_THRESHOLD = 3
LOW_PACKAGE_FRACTION = 0.20
EXPIRING_SOON_DAYS = 2
FRIDGE_TEMP_ALERT_C = 7.0          # above this, food safety is at risk
CONDITION_STALE_MINUTES = 30       # a reading older than this isn't trusted


@dataclass
class Alert:
    product_id: int | None
    product_name: str
    reason: str   # low_days_left|low_fraction|staple_out|expiring_soon|fridge_temp_high
    detail: str


def _expiring_soon_items(db: Database):
    cutoff = local_today() + timedelta(days=EXPIRING_SOON_DAYS)  # local calendar date, like the expiry dates
    for item in db.active_items():
        if item["expiration_date"]:
            exp = datetime.fromisoformat(item["expiration_date"]).date()
            if exp <= cutoff:
                yield item


def low_stock_alerts(db: Database) -> list[Alert]:
    alerts: list[Alert] = []
    seen_products: set[int] = set()

    products_on_hand = {}
    for item in db.active_items():
        products_on_hand.setdefault(item["product_id"], 0.0)
        products_on_hand[item["product_id"]] += item["grams"]

    for product_id, on_hand in products_on_hand.items():
        product = db.get_product(product_id)
        if product is None:
            continue
        dl = days_left(db, product_id)
        if dl is not None and dl <= DAYS_LEFT_THRESHOLD:
            alerts.append(Alert(product_id, product["name"], "low_days_left",
                                 f"runs out in ~{dl:.1f} days"))
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

    for item in _expiring_soon_items(db):
        product = db.get_product(item["product_id"])
        if product is None:
            continue
        alerts.append(Alert(product["id"], product["name"], "expiring_soon",
                             describe_expiry(item["expiration_date"], bool(item["expiration_estimated"]))))

    temp_alert = _fridge_temp_alert(db)
    if temp_alert:
        alerts.append(temp_alert)

    return alerts


def _fridge_temp_alert(db: Database) -> Alert | None:
    """Reads the Pi's Grove barometer (temperature) — a real fridge-health
    check, distinct from inventory alerts."""
    reading = db.latest_condition()
    if reading is None or reading["temperature_c"] is None:
        return None
    age = datetime.now(timezone.utc) - datetime.fromisoformat(reading["occurred_at"])
    if age > timedelta(minutes=CONDITION_STALE_MINUTES):
        return None
    if reading["temperature_c"] > FRIDGE_TEMP_ALERT_C:
        return Alert(None, "Fridge", "fridge_temp_high",
                     f"{reading['temperature_c']:.1f}°C — check the door and power")
    return None
