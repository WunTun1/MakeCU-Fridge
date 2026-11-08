"""Fresh test kiosk for the camera bench (vision/snap.py): an empty Shelf, and
a few ingredients elsewhere in the fridge so recipe ideas have
something to work with. Writes data/kiosk-test.db (git-ignored); your demo
database (refridge.db) isn't touched.

Run with the backend stopped, then start it on this database:
    python scripts/seed_kiosk_test.py
    DATABASE_PATH=data/kiosk-test.db ENABLE_FRIDGE_LOOP=false python main.py

The rest of the fridge has no scale, so these are added "Not weighed" (0 g),
just like items the camera adds.
"""
from __future__ import annotations

import os
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from inventory import events as inv_events  # noqa: E402
from inventory.database import Database  # noqa: E402

DB_PATH = ROOT / "data" / "kiosk-test.db"
# Photos are stored by item id, and a fresh database restarts ids at 1 — clear them too.
ITEM_IMAGE_DIR = ROOT / "data" / "item_images"

# (name, category, days until it goes bad)
# Demo setup (tested against the recipe engine): with these in the fridge, putting in
# red onion -> lime -> jalapeno brings up a different recipe each time:
# Korean Beef Patties -> Steaks in Garlic Lime Marinade -> Caribbean Chicken.
REST_OF_FRIDGE = [
    ("Chicken Thighs", "meat", 1),  # goes bad tomorrow: the one red item (tested: demo unchanged)
    ("Beef Steak", "meat", 3),
    ("Ground Beef", "meat", 2),
    ("Heavy Cream", "dairy", 7),
    # Filler, so the fridge looks lived-in. Tested together: they leave every step of the demo
    # exactly the same (milk, juice, ketchup, mustard, apples and others did change it).
    ("Mayonnaise", "packaged", 60),
    ("Strawberry Jam", "packaged", 120),
    ("Bottled Water", "drink", 365),
    ("Hummus", "packaged", 7),
]


def main() -> None:
    if os.getenv("DATABASE_PATH") and Path(os.environ["DATABASE_PATH"]).resolve() != DB_PATH:
        print(f"Note: always writes {DB_PATH}, not DATABASE_PATH.")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-journal", "-wal", "-shm"):
        Path(f"{DB_PATH}{suffix}").unlink(missing_ok=True)
    shutil.rmtree(ITEM_IMAGE_DIR, ignore_errors=True)

    db = Database(DB_PATH)
    today = date.today()
    for name, category, days in REST_OF_FRIDGE:
        product_id = db.get_or_create_product(name, category=category)
        inv_events.apply_add(
            db, product_id, 0, location="fridge", shelf=None,
            expiration_date=(today + timedelta(days=days)).isoformat(), expiration_estimated=True,
        )
    db.close()
    print(f"Fresh kiosk: empty shelf, {len(REST_OF_FRIDGE)} items in the rest of the fridge -> {DB_PATH}")


if __name__ == "__main__":
    main()
