"""Generates weeks of realistic fake history so the app has something to
show even with no hardware attached. Section 15: "Demo seeder" is the first
backend deliverable after the DB + event logging, and the thing that keeps
the demo alive if hardware breaks on the day.

Run: python scripts/seed_demo.py
"""
from __future__ import annotations

import os
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.expiry import estimate_shelf_life_days  # noqa: E402
from inventory.database import Database  # noqa: E402

DAYS_OF_HISTORY = 21
RNG_SEED = 7

# (name, category, package_g, is_staple, calories, protein, carbs, fat, avg_daily_use_g)
PRODUCTS = [
    ("Milk", "Dairy", 1000, True, 42, 3.4, 5.0, 1.0, 180),
    ("Eggs", "Dairy", 600, True, 143, 12.6, 0.7, 9.5, 85),
    ("Baby Spinach", "Leafy Greens", 150, False, 23, 2.9, 3.6, 0.4, 25),
    ("Greek Yogurt", "Dairy", 500, False, 59, 10.0, 3.6, 0.4, 60),
    ("Chicken Breast", "Meat", 700, True, 120, 22.5, 0.0, 2.6, 110),
    ("Cheddar Cheese", "Dairy", 300, False, 403, 25.0, 1.3, 33.0, 20),
    ("Butter", "Dairy", 450, True, 717, 0.9, 0.1, 81.0, 12),
    ("Orange Juice", "Beverages", 1000, False, 45, 0.7, 10.4, 0.2, 90),
]

PANTRY_PRODUCTS = [
    ("Rice", "Grains", 2000, True, 130, 2.7, 28.0, 0.3, 60),
    ("Pasta", "Grains", 1000, True, 131, 5.0, 25.0, 1.1, 50),
    ("Canned Chickpeas", "Canned Goods", 400, False, 139, 7.6, 22.5, 2.6, 30),
]


def seed(db: Database) -> None:
    random.seed(RNG_SEED)
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=DAYS_OF_HISTORY)

    for location, product_defs in (("fridge", PRODUCTS), ("pantry", PANTRY_PRODUCTS)):
        for i, (name, category, package_g, is_staple, cal, protein, carbs, fat, daily_use) in enumerate(product_defs):
            # Half the fridge sits on the weighed shelf (0); the rest is elsewhere in the fridge.
            shelf = 0 if location == "fridge" and i % 2 == 0 else None
            product_id = db.get_or_create_product(
                name, category=category, usual_package_size_g=package_g, is_staple=is_staple,
                nutrition_per_100g={"calories": cal, "protein_g": protein, "carbs_g": carbs, "fat_g": fat},
                nutrition_source="seed",
            )

            item_id = db.create_item(product_id, grams=package_g, location=location, shelf=shelf)
            db.log_event("add", product_id=product_id, item_id=item_id, grams_delta=package_g,
                         shelf=shelf, occurred_at=start.isoformat())
            remaining = float(package_g)
            t = start

            while t < now:
                t += timedelta(hours=random.uniform(6, 14))
                if t >= now or remaining <= 0:
                    break
                used = max(random.gauss(daily_use / 2, daily_use / 6), 0)
                used = min(used, remaining)
                if used <= 0:
                    continue
                remaining -= used
                db.log_event("consume", product_id=product_id, item_id=item_id, grams_delta=-used,
                             occurred_at=t.isoformat())

                if remaining < package_g * 0.1 and random.random() < 0.6:
                    db.update_item_grams(item_id, package_g)
                    db.log_event("remove", product_id=product_id, item_id=item_id, grams_delta=-remaining,
                                 occurred_at=t.isoformat())
                    remaining = float(package_g)
                    db.log_event("add", product_id=product_id, item_id=item_id, grams_delta=package_g,
                                 occurred_at=t.isoformat())

            db.update_item_grams(item_id, remaining)

    # A couple of meals today, and an expiring item, to make the home screen feel alive.
    db.log_meal("Spinach Omelette", servings=1, calories=320, protein_g=24, carbs_g=6, fat_g=22, source="chat",
                occurred_at=now.isoformat())

    # Fridge items get an estimated expiry partway through their typical shelf life;
    # the spinach gets a "printed" date for tomorrow, so the app shows both kinds.
    spinach = db.find_product_by_name("Baby Spinach")
    for item in db.active_items(location="fridge"):
        product = db.get_product(item["product_id"])
        if spinach and item["product_id"] == spinach["id"]:
            expires, estimated = (now + timedelta(days=1)).date().isoformat(), 0
        else:
            shelf_life = estimate_shelf_life_days(product["name"], product["category"])
            if shelf_life is None:
                continue
            expires, estimated = (now + timedelta(days=random.randint(1, shelf_life))).date().isoformat(), 1
        with db.cursor() as cur:
            cur.execute(
                "UPDATE items SET expiration_date = ?, expiration_estimated = ? WHERE id = ?",
                (expires, estimated, item["id"]),
            )

    print(f"Seeded {len(PRODUCTS)} fridge products and {len(PANTRY_PRODUCTS)} pantry products "
          f"with {DAYS_OF_HISTORY} days of history.")


if __name__ == "__main__":
    db_path = os.getenv("DATABASE_PATH", "refridge.db")
    seed(Database(db_path))
