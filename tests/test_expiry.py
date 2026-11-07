import sqlite3
from datetime import date

import pytest

from intelligence.expiry import describe_expiry, estimate_shelf_life_days, resolve_expiration
from inventory.database import Database

TODAY = date(2026, 11, 7)


def test_printed_date_beats_any_estimate():
    assert resolve_expiration(printed_date="2026-11-20", estimated_days=2, name="Milk", today=TODAY) == ("2026-11-20", False)


def test_model_estimate_used_when_nothing_printed():
    assert resolve_expiration(estimated_days=3, name="Milk", today=TODAY) == ("2026-11-10", True)


def test_falls_back_to_shelf_life_table():
    assert resolve_expiration(name="Whole Milk", today=TODAY) == ("2026-11-14", True)  # milk ~7 days


def test_unknown_food_gets_no_date():
    assert resolve_expiration(name="Mystery Jar", today=TODAY) == (None, False)


@pytest.mark.parametrize("bad", ["soon", -3, 9999, True, None, "5"])
def test_nonsense_model_estimates_are_ignored(bad):
    # falls through to the table (milk = 7 days) instead of trusting junk
    assert resolve_expiration(estimated_days=bad, name="Milk", today=TODAY) == ("2026-11-14", True)


def test_unreadable_printed_date_is_ignored():
    assert resolve_expiration(printed_date="11/20", estimated_days=3, today=TODAY) == ("2026-11-10", True)


@pytest.mark.parametrize(
    "name, days",
    [("Eggplant", 7), ("Eggs", 28), ("Pineapple chunks", 5), ("Apple", 30), ("Cream Cheese", 14),
     ("Cheddar Cheese", 21), ("Orange Juice", 7), ("Chicken Breast", 2)],
)
def test_specific_names_win_over_shorter_keywords(name, days):
    assert estimate_shelf_life_days(name) == days


def test_category_fallback():
    assert estimate_shelf_life_days("Thing", category="Meat") == 2


@pytest.mark.parametrize(
    "expires, estimated, text",
    [("2026-11-06", False, "expired"), ("2026-11-07", False, "expires today"),
     ("2026-11-08", True, "expires tomorrow (est.)"), ("2026-11-11", True, "expires in 4 days (est.)")],
)
def test_describe_expiry(expires, estimated, text):
    assert describe_expiry(expires, estimated, today=TODAY) == text


def test_old_database_gets_the_new_column(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("""CREATE TABLE items (id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL,
                   location TEXT NOT NULL DEFAULT 'fridge', shelf INTEGER, position_x REAL, position_y REAL,
                   grams REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active', added_at TEXT NOT NULL,
                   expiration_date TEXT, last_seen TEXT, confidence REAL)""")
    old.commit()
    old.close()

    db = Database(path)
    pid = db.create_product("Milk")
    item_id = db.create_item(pid, 1000, expiration_date="2026-11-14", expiration_estimated=True)
    assert db.get_item(item_id)["expiration_estimated"] == 1
