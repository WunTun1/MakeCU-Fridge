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
    created_at TEXT NOT NULL
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
    confidence REAL
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

CREATE INDEX IF NOT EXISTS idx_items_product ON items(product_id);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE INDEX IF NOT EXISTS idx_events_product ON events(product_id);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON events(occurred_at);
"""


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
    ) -> int:
        n = nutrition_per_100g or {}
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO products
                   (name, category, usual_package_size_g, is_staple, barcode,
                    calories_per_100g, protein_g_per_100g, carbs_g_per_100g, fat_g_per_100g,
                    fiber_g_per_100g, sugar_g_per_100g, sodium_mg_per_100g,
                    nutrition_source, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    name, category, usual_package_size_g, int(is_staple), barcode,
                    n.get("calories"), n.get("protein_g"), n.get("carbs_g"), n.get("fat_g"),
                    n.get("fiber_g"), n.get("sugar_g"), n.get("sodium_mg"),
                    nutrition_source, now_iso(),
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
    ) -> int:
        existing = self.find_product_by_name(name)
        if existing:
            return existing["id"]
        return self.create_product(
            name, category, usual_package_size_g, is_staple, barcode,
            nutrition_per_100g, nutrition_source,
        )

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


_db: Database | None = None


def get_db(path: str | Path | None = None) -> Database:
    """Process-wide singleton so every module shares one connection. Without an
    explicit path it honors DATABASE_PATH, so nothing can quietly open the
    default database when another one was configured."""
    global _db
    if _db is None:
        _db = Database(path or os.getenv("DATABASE_PATH", "refridge.db"))
    return _db
