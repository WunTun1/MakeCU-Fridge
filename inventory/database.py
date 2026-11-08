"""SQLite schema + a thin query layer. See ReFridge_Architecture.md section 8.

Every other module talks to the database through this file so the schema
only has to change in one place.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from inventory.units import default_grams_per_unit, guess_unit

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT,
    usual_package_size_g REAL,
    is_staple INTEGER NOT NULL DEFAULT 0,
    barcode TEXT,
    calories_per_100g REAL,
    protein_g_per_100g REAL,
    carbs_g_per_100g REAL,
    fat_g_per_100g REAL,
    fiber_g_per_100g REAL,
    sugar_g_per_100g REAL,
    sodium_mg_per_100g REAL,
    nutrition_source TEXT,
    created_at TEXT NOT NULL,
    unit TEXT NOT NULL DEFAULT 'g',             -- g | count | ml: how amounts are entered and shown
    grams_per_unit REAL NOT NULL DEFAULT 1,     -- grams in one egg / one ml; 1 for g
    recipe_id INTEGER                           -- leftovers: the library recipe they were cooked from
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    location TEXT NOT NULL DEFAULT 'fridge',   -- fridge | pantry | freezer
    shelf INTEGER,
    position_x REAL,
    position_y REAL,
    grams REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',     -- active | removed
    added_at TEXT NOT NULL,
    expiration_date TEXT,
    expiration_estimated INTEGER NOT NULL DEFAULT 0,  -- 1 = estimated shelf life, 0 = printed on package
    last_seen TEXT,
    confidence REAL,
    leaving_shelf INTEGER NOT NULL DEFAULT 0   -- moved elsewhere (freezer) in the app: its shelf drop is expected
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER REFERENCES items(id),
    product_id INTEGER REFERENCES products(id),
    event_type TEXT NOT NULL,   -- add|remove|consume|move|return|waste|needs_review
    grams_delta REAL NOT NULL DEFAULT 0,
    shelf INTEGER,
    occurred_at TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 1,
    meta TEXT                   -- json blob: free-form context (e.g. candidate matches)
);

CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    recipe_name TEXT,
    servings REAL NOT NULL DEFAULT 1,
    calories REAL,
    protein_g REAL,
    carbs_g REAL,
    fat_g REAL,
    source TEXT NOT NULL DEFAULT 'manual'   -- chat|manual|recipe
);

CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    daily_calories REAL,
    daily_protein_g REAL,
    daily_carbs_g REAL,
    daily_fat_g REAL,
    diet_type TEXT,
    allergies TEXT,     -- json list
    dislikes TEXT       -- json list
);

CREATE TABLE IF NOT EXISTS chat_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,     -- user|assistant
    content TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

-- What one chat reply changed, so it can be undone from under that reply.
CREATE TABLE IF NOT EXISTS chat_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    meal_ids TEXT NOT NULL,     -- json list: meals it logged (their tagged events go with them)
    event_ids TEXT NOT NULL,    -- json list: other inventory events (an add, a consume)
    undone INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS taste_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    signal TEXT NOT NULL,      -- cooked | liked | disliked | asked
    feature TEXT NOT NULL,     -- recipe:<id> | cuisine:<name> | ingredient:<canonical name>
    weight REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS fridge_conditions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    temperature_c REAL,
    pressure_hpa REAL,
    humidity_pct REAL,
    light_raw REAL
);

CREATE TABLE IF NOT EXISTS grocery_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    norm TEXT NOT NULL,          -- normalized name, for de-duplication
    source TEXT NOT NULL,        -- plan | manual | recipe
    recipe_id INTEGER,
    recipe_name TEXT,
    trip_date TEXT,              -- plan entries only: the trip they were planned for
    checked INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,   -- removed by you (plan entries: for that trip)
    added_at TEXT NOT NULL,
    amount TEXT                  -- "6", "2 L": how much, when you said
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_product ON items(product_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_events_product ON events(product_id);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at);
"""


# A counted item with less than this many units left is finished: nobody keeps 0.4 of an egg.
REMNANT_UNITS = 0.5


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Wraps a single SQLite file. Not thread-safe across processes by design —
    the fridge loop and API server share one file via check_same_thread=False.

    Within a process, one connection is shared by the fridge loop and every API
    request thread, so each `cursor()` block holds a lock: concurrent use of a
    single sqlite3 connection mixes up rows or fails with "API misuse"."""

    def __init__(self, path: str | Path = "refridge.db"):
        self.path = str(path)
        self._lock = threading.RLock()  # re-entrant: a cursor() block may call other methods
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()
        self._ensure_profile_row()

    def _migrate(self) -> None:
        """Bring databases created by older versions up to the current schema.
        CREATE TABLE IF NOT EXISTS never adds columns to an existing table."""
        item_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(items)")}
        if "expiration_estimated" not in item_columns:
            self._conn.execute(
                "ALTER TABLE items ADD COLUMN expiration_estimated INTEGER NOT NULL DEFAULT 0"
            )
        grocery_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(grocery_entries)")}
        if "amount" not in grocery_columns:
            self._conn.execute("ALTER TABLE grocery_entries ADD COLUMN amount TEXT")
        if "leaving_shelf" not in item_columns:
            self._conn.execute("ALTER TABLE items ADD COLUMN leaving_shelf INTEGER NOT NULL DEFAULT 0")
        product_columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(products)")}
        if "recipe_id" not in product_columns:
            self._conn.execute("ALTER TABLE products ADD COLUMN recipe_id INTEGER")
        if "unit" not in product_columns:
            self._conn.execute("ALTER TABLE products ADD COLUMN unit TEXT NOT NULL DEFAULT 'g'")
            self._conn.execute("ALTER TABLE products ADD COLUMN grams_per_unit REAL NOT NULL DEFAULT 1")
            for row in self._conn.execute("SELECT id, name FROM products").fetchall():
                unit = guess_unit(row["name"])
                self._conn.execute(
                    "UPDATE products SET unit = ?, grams_per_unit = ? WHERE id = ?",
                    (unit, default_grams_per_unit(row["name"], unit), row["id"]),
                )
        self._finish_remnants_once()

    def _finish_remnants_once(self) -> None:
        """Counted items left with less than half a unit (0.4 of an egg) are finished. Deductions
        do this as they happen (inventory/events.py); this clears what older versions left behind."""
        done = self._conn.execute("SELECT 1 FROM settings WHERE key = 'remnants_finished'").fetchone()
        if done:
            return
        self._conn.execute(
            """UPDATE items SET status = 'removed', grams = 0
               WHERE status = 'active' AND product_id IN (SELECT id FROM products WHERE unit = 'count')
               AND grams < (SELECT ? * grams_per_unit FROM products WHERE products.id = items.product_id)""",
            (REMNANT_UNITS,),
        )
        self._conn.execute("INSERT INTO settings (key, value) VALUES ('remnants_finished', '1')")

    def _ensure_profile_row(self) -> None:
        cur = self._conn.execute("SELECT id FROM profile WHERE id = 1")
        if cur.fetchone() is None:
            self._conn.execute(
                """INSERT INTO profile
                   (id, daily_calories, daily_protein_g, daily_carbs_g, daily_fat_g,
                    diet_type, allergies, dislikes)
                   VALUES (1, 2000, 100, 225, 65, 'none', '[]', '[]')"""
            )
            self._conn.commit()

    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- products
    def find_product_by_name(self, name: str) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE name = ? COLLATE NOCASE", (name,))
            return cur.fetchone()

    def find_product_by_barcode(self, barcode: str) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE barcode = ?", (barcode,))
            return cur.fetchone()

    def get_product(self, product_id: int) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
            return cur.fetchone()

    def create_product(
        self,
        name: str,
        category: str | None = None,
        usual_package_size_g: float | None = None,
        is_staple: bool = False,
        barcode: str | None = None,
        nutrition_per_100g: dict[str, float] | None = None,
        nutrition_source: str | None = None,
        unit: str | None = None,
        recipe_id: int | None = None,
        grams_per_unit: float | None = None,
    ) -> int:
        """`unit` defaults to a guess from the name (eggs are counted, milk is poured)."""
        n = nutrition_per_100g or {}
        unit = unit or guess_unit(name)
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO products
                   (name, category, usual_package_size_g, is_staple, barcode,
                    calories_per_100g, protein_g_per_100g, carbs_g_per_100g, fat_g_per_100g,
                    fiber_g_per_100g, sugar_g_per_100g, sodium_mg_per_100g,
                    nutrition_source, created_at, unit, grams_per_unit, recipe_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name, category, usual_package_size_g, int(is_staple), barcode,
                    n.get("calories"), n.get("protein_g"), n.get("carbs_g"), n.get("fat_g"),
                    n.get("fiber_g"), n.get("sugar_g"), n.get("sodium_mg"),
                    nutrition_source, now_iso(), unit, grams_per_unit or default_grams_per_unit(name, unit),
                    recipe_id,
                ),
            )
            return cur.lastrowid

    def get_or_create_product(
        self,
        name: str,
        category: str | None = None,
        usual_package_size_g: float | None = None,
        is_staple: bool = False,
        barcode: str | None = None,
        nutrition_per_100g: dict[str, float] | None = None,
        nutrition_source: str | None = None,
        unit: str | None = None,
        recipe_id: int | None = None,
        grams_per_unit: float | None = None,
    ) -> int:
        existing = self.find_product_by_name(name)
        if existing:
            return existing["id"]
        return self.create_product(
            name, category, usual_package_size_g, is_staple, barcode,
            nutrition_per_100g, nutrition_source, unit, recipe_id, grams_per_unit,
        )

    def product_for_recipe(self, recipe_id: int) -> Optional[sqlite3.Row]:
        """The leftovers product cooked from this recipe, if any."""
        with self.cursor() as cur:
            cur.execute("SELECT * FROM products WHERE recipe_id = ? ORDER BY id LIMIT 1", (recipe_id,))
            return cur.fetchone()

    # ------------------------------------------------------------------- items
    def create_item(
        self,
        product_id: int,
        grams: float,
        location: str = "fridge",
        shelf: int | None = None,
        position: tuple[float, float] | None = None,
        expiration_date: str | None = None,
        confidence: float | None = None,
        expiration_estimated: bool = False,
    ) -> int:
        px, py = position if position else (None, None)
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO items
                   (product_id, location, shelf, position_x, position_y, grams, status,
                    added_at, expiration_date, expiration_estimated, last_seen, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
                (product_id, location, shelf, px, py, grams, now_iso(),
                 expiration_date, int(expiration_estimated), now_iso(), confidence),
            )
            return cur.lastrowid

    def get_item(self, item_id: int) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM items WHERE id = ?", (item_id,))
            return cur.fetchone()

    def active_items(self, location: str | None = None, shelf: int | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM items WHERE status = 'active'"
        params: list[Any] = []
        if location:
            q += " AND location = ?"
            params.append(location)
        if shelf is not None:
            q += " AND shelf = ?"
            params.append(shelf)
        with self.cursor() as cur:
            cur.execute(q, params)
            return cur.fetchall()

    def update_item_grams(self, item_id: int, grams: float) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE items SET grams = ?, last_seen = ? WHERE id = ?",
                (max(grams, 0.0), now_iso(), item_id),
            )

    def update_item(self, item_id: int, grams: float | None = None, expiration_date: str | None = None) -> None:
        """A person's correction. A date they give is treated as printed, not estimated."""
        with self.cursor() as cur:
            if grams is not None:
                cur.execute(
                    "UPDATE items SET grams = ?, last_seen = ? WHERE id = ?", (max(grams, 0.0), now_iso(), item_id)
                )
            if expiration_date is not None:
                cur.execute(
                    "UPDATE items SET expiration_date = ?, expiration_estimated = 0 WHERE id = ?",
                    (expiration_date, item_id),
                )

    def set_item_storage(
        self, item_id: int, location: str, expiration_date: str | None, expiration_estimated: bool, leaving_shelf: bool,
    ) -> None:
        """Moved between fridge and freezer: a new place, a new date, and whether a shelf drop is expected."""
        with self.cursor() as cur:
            cur.execute(
                """UPDATE items SET location = ?, expiration_date = ?, expiration_estimated = ?, leaving_shelf = ?,
                   last_seen = ? WHERE id = ?""",
                (location, expiration_date, int(expiration_estimated), int(leaving_shelf), now_iso(), item_id),
            )

    def clear_leaving_shelf(self, item_id: int) -> None:
        """It has left the shelf: off the weighed shelf, and no longer tracked by the camera."""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE items SET leaving_shelf = 0, shelf = NULL, position_x = NULL, position_y = NULL WHERE id = ?",
                (item_id,),
            )

    def delete_item(self, item_id: int) -> None:
        """Forget an item entirely, with its history. Only for undoing an add."""
        with self.cursor() as cur:
            cur.execute("DELETE FROM events WHERE item_id = ?", (item_id,))
            cur.execute("DELETE FROM items WHERE id = ?", (item_id,))

    def update_item_location(
        self, item_id: int, shelf: int | None = None, position: tuple[float, float] | None = None
    ) -> None:
        px, py = position if position else (None, None)
        with self.cursor() as cur:
            cur.execute(
                "UPDATE items SET shelf = ?, position_x = ?, position_y = ?, last_seen = ? WHERE id = ?",
                (shelf, px, py, now_iso(), item_id),
            )

    def mark_item_removed(self, item_id: int) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE items SET status = 'removed', grams = 0, last_seen = ? WHERE id = ?",
                (now_iso(), item_id),
            )

    def reactivate_item(self, item_id: int, grams: float) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE items SET status = 'active', grams = ?, last_seen = ? WHERE id = ?",
                (grams, now_iso(), item_id),
            )

    # ------------------------------------------------------------------ events
    def log_event(
        self,
        event_type: str,
        product_id: int | None = None,
        item_id: int | None = None,
        grams_delta: float = 0.0,
        shelf: int | None = None,
        resolved: bool = True,
        meta: dict | None = None,
        occurred_at: str | None = None,
    ) -> int:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO events
                   (item_id, product_id, event_type, grams_delta, shelf, occurred_at, resolved, meta)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (item_id, product_id, event_type, grams_delta, shelf,
                 occurred_at or now_iso(), int(resolved), json.dumps(meta) if meta else None),
            )
            return cur.lastrowid

    def events_for_product(self, product_id: int, since: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM events WHERE product_id = ?"
        params: list[Any] = [product_id]
        if since:
            q += " AND occurred_at >= ?"
            params.append(since)
        q += " ORDER BY occurred_at ASC"
        with self.cursor() as cur:
            cur.execute(q, params)
            return cur.fetchall()

    def all_events(self, since: str | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM events"
        params: list[Any] = []
        if since:
            q += " WHERE occurred_at >= ?"
            params.append(since)
        q += " ORDER BY occurred_at ASC"
        with self.cursor() as cur:
            cur.execute(q, params)
            return cur.fetchall()

    def common_products(self, limit: int = 8) -> list[sqlite3.Row]:
        """Products added most often — quick-pick names for the fridge screen."""
        with self.cursor() as cur:
            cur.execute(
                """SELECT p.id, p.name, COUNT(e.id) AS adds
                   FROM products p LEFT JOIN events e ON e.product_id = p.id AND e.event_type = 'add'
                   GROUP BY p.id ORDER BY adds DESC, p.name LIMIT ?""",
                (limit,),
            )
            return cur.fetchall()

    def events_for_item(self, item_id: int) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM events WHERE item_id = ? ORDER BY id", (item_id,))
            return cur.fetchall()

    def events_for_meal(self, meal_id: int) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM events WHERE json_extract(meta, '$.meal_id') = ? ORDER BY id", (meal_id,))
            return cur.fetchall()

    def delete_event(self, event_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def get_event(self, event_id: int) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM events WHERE id = ?", (event_id,))
            return cur.fetchone()

    def needs_review(self) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT * FROM events WHERE event_type = 'needs_review' AND resolved = 0 "
                "ORDER BY occurred_at DESC"
            )
            return cur.fetchall()

    def resolve_event(self, event_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE events SET resolved = 1 WHERE id = ?", (event_id,))

    # ------------------------------------------------------------------- meals
    def log_meal(
        self,
        recipe_name: str | None,
        servings: float,
        calories: float | None,
        protein_g: float | None,
        carbs_g: float | None,
        fat_g: float | None,
        source: str = "manual",
        occurred_at: str | None = None,
    ) -> int:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO meals
                   (occurred_at, recipe_name, servings, calories, protein_g, carbs_g, fat_g, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (occurred_at or now_iso(), recipe_name, servings, calories, protein_g, carbs_g, fat_g, source),
            )
            return cur.lastrowid

    def get_meal(self, meal_id: int) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM meals WHERE id = ?", (meal_id,))
            return cur.fetchone()

    def delete_meal(self, meal_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM meals WHERE id = ?", (meal_id,))

    def meals_since(self, since: str) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM meals WHERE occurred_at >= ? ORDER BY occurred_at ASC", (since,))
            return cur.fetchall()

    # ----------------------------------------------------------------- profile
    def get_profile(self) -> sqlite3.Row:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM profile WHERE id = 1")
            return cur.fetchone()

    def update_profile(self, **fields: Any) -> None:
        if not fields:
            return
        if "allergies" in fields and not isinstance(fields["allergies"], str):
            fields["allergies"] = json.dumps(fields["allergies"])
        if "dislikes" in fields and not isinstance(fields["dislikes"], str):
            fields["dislikes"] = json.dumps(fields["dislikes"])
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self.cursor() as cur:
            cur.execute(f"UPDATE profile SET {cols} WHERE id = 1", list(fields.values()))

    # -------------------------------------------------------------- chat_memory
    def add_chat_message(self, role: str, content: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_memory (role, content, occurred_at) VALUES (?, ?, ?)",
                (role, content, now_iso()),
            )

    def recent_chat(self, limit: int = 20) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT * FROM chat_memory ORDER BY id DESC LIMIT ?", (limit,)
            )
            return list(reversed(cur.fetchall()))

    def clear_chat(self) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM chat_memory")

    def add_chat_turn(self, meal_ids: list[int], event_ids: list[int]) -> int:
        with self.cursor() as cur:
            cur.execute("INSERT INTO chat_turns (occurred_at, meal_ids, event_ids) VALUES (?, ?, ?)",
                        (now_iso(), json.dumps(meal_ids), json.dumps(event_ids)))
            return cur.lastrowid

    def get_chat_turn(self, turn_id: int) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM chat_turns WHERE id = ?", (turn_id,))
            return cur.fetchone()

    def mark_chat_turn_undone(self, turn_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE chat_turns SET undone = 1 WHERE id = ?", (turn_id,))

    # ------------------------------------------------------------ taste_events
    def log_taste(self, signal: str, features: list[tuple[str, float]], occurred_at: str | None = None) -> None:
        when = occurred_at or now_iso()
        with self.cursor() as cur:
            cur.executemany(
                "INSERT INTO taste_events (occurred_at, signal, feature, weight) VALUES (?, ?, ?, ?)",
                [(when, signal, feature, weight) for feature, weight in features],
            )

    def taste_events_since(self, since: str) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM taste_events WHERE occurred_at >= ?", (since,))
            return cur.fetchall()

    # -------------------------------------------------------- fridge_conditions
    def log_condition(
        self,
        temperature_c: float | None = None,
        pressure_hpa: float | None = None,
        humidity_pct: float | None = None,
        light_raw: float | None = None,
        occurred_at: str | None = None,
    ) -> int:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO fridge_conditions
                   (occurred_at, temperature_c, pressure_hpa, humidity_pct, light_raw)
                   VALUES (?, ?, ?, ?, ?)""",
                (occurred_at or now_iso(), temperature_c, pressure_hpa, humidity_pct, light_raw),
            )
            return cur.lastrowid

    def latest_condition(self) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM fridge_conditions ORDER BY id DESC LIMIT 1")
            return cur.fetchone()

    def conditions_since(self, since: str) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT * FROM fridge_conditions WHERE occurred_at >= ? ORDER BY occurred_at ASC", (since,)
            )
            return cur.fetchall()

    # ----------------------------------------------------------------- settings
    def get_setting(self, key: str) -> str | None:
        with self.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            return row["value"] if row else None

    def set_setting(self, key: str, value: str | None) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # ---------------------------------------------------------- grocery_entries
    def grocery_entries(self) -> list[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM grocery_entries ORDER BY id")
            return cur.fetchall()

    def get_grocery_entry(self, entry_id: int) -> Optional[sqlite3.Row]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM grocery_entries WHERE id = ?", (entry_id,))
            return cur.fetchone()

    def add_grocery_entry(
        self, name: str, norm: str, source: str, recipe_id: int | None = None,
        recipe_name: str | None = None, trip_date: str | None = None, amount: str | None = None,
    ) -> int:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO grocery_entries (name, norm, source, recipe_id, recipe_name, trip_date, added_at, amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, norm, source, recipe_id, recipe_name, trip_date, now_iso(), amount),
            )
            return cur.lastrowid

    def set_grocery_checked(self, entry_id: int, checked: bool) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE grocery_entries SET checked = ? WHERE id = ?", (int(checked), entry_id))

    def set_grocery_hidden(self, entry_id: int, hidden: bool) -> None:
        with self.cursor() as cur:
            cur.execute("UPDATE grocery_entries SET hidden = ? WHERE id = ?", (int(hidden), entry_id))

    def clear_checked_grocery(self) -> None:
        """Bought: your own entries go away; plan entries stay hidden for that trip
        so the plan doesn't put them straight back."""
        with self.cursor() as cur:
            cur.execute("DELETE FROM grocery_entries WHERE checked = 1 AND source != 'plan'")
            cur.execute("UPDATE grocery_entries SET hidden = 1 WHERE checked = 1 AND source = 'plan'")


_db: Database | None = None


def get_db(path: str | Path | None = None) -> Database:
    """Process-wide singleton so every module shares one connection. Without an
    explicit path it honors DATABASE_PATH, so nothing can quietly open the
    default database when another one was configured."""
    global _db
    if _db is None:
        _db = Database(path or os.getenv("DATABASE_PATH", "refridge.db"))
    return _db
