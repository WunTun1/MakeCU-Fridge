import sqlite3

import pytest

from inventory import events as inv_events
from inventory.database import Database
from inventory.units import default_grams_per_unit, guess_unit
from intelligence import grocery_list
from intelligence.alerts import low_stock_alerts
from intelligence.consumption import usage_rate_g_per_day


# ------------------------------------------------------------------- units
@pytest.mark.parametrize("name, unit", [
    ("Eggs", "count"), ("Lemon", "count"), ("Red bell pepper", "count"), ("Roma Tomatoes", "count"),
    ("Milk", "ml"), ("Orange Juice", "ml"), ("Olive oil", "ml"), ("Chicken Broth", "ml"),
    ("Sour cream", "g"), ("Eggplant", "g"), ("Baby Spinach", "g"), ("Cheddar Cheese", "g"),
])
def test_guess_unit(name, unit):
    assert guess_unit(name) == unit


def test_grams_per_unit_defaults():
    assert default_grams_per_unit("Eggs", "count") == 50
    assert default_grams_per_unit("Apples", "count") == 180
    assert default_grams_per_unit("Kiwi", "count") == 100
    assert default_grams_per_unit("Milk", "ml") == 1


def test_new_products_get_a_guessed_unit(db):
    eggs = db.get_product(db.get_or_create_product("Eggs"))
    assert (eggs["unit"], eggs["grams_per_unit"]) == ("count", 50)
    rice = db.get_product(db.get_or_create_product("Rice", unit="g"))
    assert rice["unit"] == "g"


def test_migration_adds_units_to_an_old_database(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
        category TEXT, usual_package_size_g REAL, is_staple INTEGER NOT NULL DEFAULT 0, barcode TEXT,
        calories_per_100g REAL, protein_g_per_100g REAL, carbs_g_per_100g REAL, fat_g_per_100g REAL,
        fiber_g_per_100g REAL, sugar_g_per_100g REAL, sodium_mg_per_100g REAL, nutrition_source TEXT,
        created_at TEXT NOT NULL)""")
    conn.execute("INSERT INTO products (name, created_at) VALUES ('Eggs', '2026-01-01'), ('Rice', '2026-01-01')")
    conn.commit()
    conn.close()

    db = Database(path)
    eggs, rice = db.find_product_by_name("Eggs"), db.find_product_by_name("Rice")
    assert (eggs["unit"], eggs["grams_per_unit"]) == ("count", 50)
    assert rice["unit"] == "g"
    db.close()
    Database(path).close()  # opening again is a no-op


# -------------------------------------------------------------------- undo
def test_undo_consume_and_waste_restores_grams_and_history(db):
    pid = db.get_or_create_product("Yogurt")
    item_id = inv_events.apply_add(db, pid, 500)
    used = inv_events.apply_consume(db, item_id, 200)
    wasted = inv_events.apply_waste(db, item_id)
    assert db.get_item(item_id)["status"] == "removed"

    inv_events.undo_events(db, [wasted, used])
    item = db.get_item(item_id)
    assert (item["status"], item["grams"]) == ("active", 500)
    assert [e["event_type"] for e in db.events_for_item(item_id)] == ["add"]


def test_waste_is_not_usage(db):
    pid = db.get_or_create_product("Yogurt")
    item_id = inv_events.apply_add(db, pid, 500)
    inv_events.apply_waste(db, item_id)
    assert usage_rate_g_per_day(db, pid) == 0


def test_undo_add_only_while_untouched(db):
    pid = db.get_or_create_product("Eggs")
    fresh = inv_events.apply_add(db, pid, 600)
    assert inv_events.undo_add(db, fresh) and db.get_item(fresh) is None
    used = inv_events.apply_add(db, pid, 600)
    inv_events.apply_consume(db, used, 50)
    assert not inv_events.undo_add(db, used)


def test_update_item_marks_a_given_date_as_printed(db):
    pid = db.get_or_create_product("Milk")
    item_id = inv_events.apply_add(db, pid, 1000, expiration_date="2026-11-09", expiration_estimated=True)
    db.update_item(item_id, grams=400, expiration_date="2026-11-12")
    item = db.get_item(item_id)
    assert (item["grams"], item["expiration_date"], item["expiration_estimated"]) == (400, "2026-11-12", 0)


# ------------------------------------------------------------------ alerts
def test_one_alert_per_product_most_urgent_first(db):
    pid = db.create_product("Chicken Breast", usual_package_size_g=700)
    inv_events.apply_add(db, pid, 50, expiration_date="2000-01-01")  # low fraction and expired
    alerts = [a for a in low_stock_alerts(db) if a.product_id == pid]
    assert [a.reason for a in alerts] == ["expiring_soon"]


# ----------------------------------------------------------------- grocery
def test_grocery_entries_dedupe_persist_and_clear(db):
    [lemon] = grocery_list.add_entries(db, ["Lemon"], "manual")
    assert grocery_list.add_entries(db, ["lemons"], "manual") == [lemon]
    grocery_list.add_entries(db, ["feta cheese"], "recipe", recipe_id=7, recipe_name="Greek Salad")

    db.set_grocery_checked(lemon, True)
    items = {i["name"]: i for i in grocery_list.build_list(db)["items"]}
    assert items["Lemon"]["checked"] and items["Lemon"]["source"] == "manual"
    assert items["feta cheese"]["recipe_name"] == "Greek Salad"

    db.clear_checked_grocery()
    names = [i["name"] for i in grocery_list.build_list(db)["items"]]
    assert names == ["feta cheese"]


def test_grocery_horizon_persists(db):
    assert grocery_list.build_list(db)["trip_in_days"] is None
    grocery_list.set_horizon(db, 7)
    assert grocery_list.build_list(db)["trip_in_days"] == 7
    grocery_list.set_horizon(db, None)
    assert grocery_list.get_horizon(db) is None
