"""The local recipe library: a read-mostly SQLite file with full-text search.

Kept separate from refridge.db (inventory) because it's large, rebuilt from
source data by recipes/build.py, and identical on every device — copy
data/recipes.db to the Pi instead of rebuilding it there.
"""
from __future__ import annotations

import html
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from recipes.ingredients import canonical
from recipes.timing import inactive_time
from recipes.titles import clean_steps, clean_title

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "recipes.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    cuisine TEXT,
    minutes INTEGER,
    servings REAL,
    calories REAL,           -- per serving
    protein_g REAL,
    fat_g REAL,
    carbs_g REAL,
    fiber_g REAL,
    sugar_g REAL,
    sodium_mg REAL,
    image_url TEXT,
    description TEXT,
    tags TEXT NOT NULL,          -- json list
    ingredients TEXT NOT NULL,   -- json list of {name, canon, quantity, unit}
    steps TEXT NOT NULL          -- json list
);
CREATE VIRTUAL TABLE IF NOT EXISTS recipes_fts USING fts5(
    name, cuisine, tags, ingredients, content='', tokenize='porter unicode61'
);
"""

# Food.com cuisine tags we surface as "cuisine". Order matters: the first match wins,
# so specific cuisines come before broad regions.
CUISINES = [
    "italian", "mexican", "chinese", "japanese", "thai", "indian", "greek", "french", "spanish",
    "korean", "vietnamese", "middle-eastern", "moroccan", "turkish", "lebanese", "caribbean",
    "cajun", "creole", "southern-united-states", "tex-mex", "german", "irish", "british-columbian",
    "english", "polish", "russian", "brazilian", "african", "filipino", "hawaiian", "mediterranean",
    "asian", "european", "american",
]


@dataclass
class Recipe:
    id: int
    name: str
    cuisine: str | None
    minutes: int | None
    servings: float | None
    nutrition: dict[str, float | None]   # per serving
    image_url: str | None
    description: str | None
    tags: list[str]
    ingredients: list[dict]              # {name, canon, quantity, unit}
    steps: list[str]
    canon_ingredients: list[str] = field(default_factory=list)
    # Waiting the steps call for (marinating, chilling, rising), on top of `minutes`.
    inactive_min: int = 0
    inactive_verb: str | None = None

    def __post_init__(self):
        if not self.canon_ingredients:
            self.canon_ingredients = [i["canon"] for i in self.ingredients if i.get("canon")]
        if not self.inactive_min:
            self.inactive_min, self.inactive_verb = inactive_time(self.steps)

    @property
    def total_minutes(self) -> int | None:
        """Active plus waiting time: what 'under 30 minutes' is measured against."""
        return None if self.minutes is None else self.minutes + self.inactive_min


def _fts_terms(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]


def build_match(query: str | None, cuisine: str | None) -> str | None:
    """FTS5 MATCH expression: (cuisine filter) AND (any query word, prefix-matched)."""
    parts = []
    if cuisine:
        c = cuisine.strip().lower().replace(" ", "-")
        terms = _fts_terms(c)
        if terms:
            parts.append("{cuisine tags} : (" + " ".join(f'"{t}"' for t in terms) + ")")
    words = _fts_terms(query or "")
    if words:
        parts.append("(" + " OR ".join(f'"{w}"*' if len(w) >= 4 else f'"{w}"' for w in words) + ")")
    return " AND ".join(parts) or None


class RecipeStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("RECIPES_DB_PATH") or DEFAULT_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM recipes").fetchone()[0]

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------ writing
    def add(self, r: dict) -> None:
        """`r` has the Recipe fields with ingredients/tags/steps as lists."""
        cur = self._conn.execute(
            """INSERT INTO recipes (id, name, cuisine, minutes, servings, calories, protein_g, fat_g, carbs_g,
                   fiber_g, sugar_g, sodium_mg, image_url, description, tags, ingredients, steps)
               VALUES (:id, :name, :cuisine, :minutes, :servings, :calories, :protein_g, :fat_g, :carbs_g,
                   :fiber_g, :sugar_g, :sodium_mg, :image_url, :description, :tags, :ingredients, :steps)""",
            {**r, "tags": json.dumps(r["tags"]), "ingredients": json.dumps(r["ingredients"]),
             "steps": json.dumps(r["steps"])},
        )
        self._conn.execute(
            "INSERT INTO recipes_fts (rowid, name, cuisine, tags, ingredients) VALUES (?, ?, ?, ?, ?)",
            (cur.lastrowid, r["name"], r.get("cuisine") or "", " ".join(r["tags"]),
             " ".join(i["canon"] for i in r["ingredients"] if i.get("canon"))),
        )

    def commit(self) -> None:
        self._conn.commit()

    # ------------------------------------------------------------ reading
    def search(
        self,
        query: str | None = None,
        cuisine: str | None = None,
        max_minutes: int | None = None,
        limit: int = 300,
        main_dish_only: bool = False,
    ) -> list[tuple[int, float]]:
        """(recipe_id, relevance) best first; relevance is 0-1 within this result set."""
        match = build_match(query, cuisine)
        params: list = []
        if match:
            sql = "SELECT f.rowid AS id, bm25(recipes_fts, 10.0, 5.0, 2.0, 1.0) AS rank FROM recipes_fts f"
            sql += " JOIN recipes r ON r.id = f.rowid WHERE recipes_fts MATCH ?"
            params.append(match)
        else:
            sql = "SELECT r.id AS id, 0.0 AS rank FROM recipes r WHERE 1"
        if max_minutes:
            sql += " AND r.minutes <= ?"
            params.append(max_minutes)
        if main_dish_only:
            sql += " AND r.tags LIKE '%\"main-dish\"%'"
        if query and _fts_terms(query):
            sql += " ORDER BY rank LIMIT ?"
        else:
            # Cuisine-only ("I want Italian") or nothing: no text relevance to rank by, so prefer
            # real meals with photos over side sauces and desserts; shuffle within that for variety.
            sql += (" ORDER BY (r.tags LIKE '%\"main-dish\"%') DESC, (r.image_url IS NOT NULL) DESC,"
                    " (r.protein_g IS NOT NULL) DESC, RANDOM() LIMIT ?")
        params.append(limit)
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return []  # malformed MATCH from odd input -> no results rather than a crash
        if not rows:
            return []
        if not (query and _fts_terms(query)):
            return [(row["id"], 1.0) for row in rows]  # a cuisine filter matches or it doesn't
        ranks = [row["rank"] for row in rows]
        best, worst = min(ranks), max(ranks)
        span = (worst - best) or 1.0
        return [(row["id"], 1.0 - (row["rank"] - best) / span) for row in rows]

    def get_many(self, ids: list[int]) -> list[Recipe]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = {r["id"]: r for r in self._conn.execute(f"SELECT * FROM recipes WHERE id IN ({marks})", ids)}
        return [self._to_recipe(rows[i]) for i in ids if i in rows]

    def get(self, recipe_id: int) -> Recipe | None:
        found = self.get_many([recipe_id])
        return found[0] if found else None

    @staticmethod
    def _to_recipe(row: sqlite3.Row) -> Recipe:
        # Food.com text carries HTML entities ("Mac &amp; Cheese"), shouting and hashtags; tidied here so no screen
        # shows them (the search index keeps the raw title).
        ingredients = json.loads(row["ingredients"])
        for ing in ingredients:
            ing["name"] = html.unescape(ing["name"])
            # Recomputed on read so improvements to ingredient matching apply without a rebuild.
            ing["canon"] = canonical(ing["name"])
        return Recipe(
            id=row["id"], name=clean_title(html.unescape(row["name"])), cuisine=row["cuisine"], minutes=row["minutes"],
            servings=row["servings"],
            nutrition={k: row[k] for k in ("calories", "protein_g", "fat_g", "carbs_g", "fiber_g", "sugar_g", "sodium_mg")},
            image_url=row["image_url"],
            description=html.unescape(row["description"]) if row["description"] else None,
            tags=json.loads(row["tags"]), ingredients=ingredients,
            steps=clean_steps([html.unescape(s) for s in json.loads(row["steps"])]),
        )


_store: RecipeStore | None = None


def get_store() -> RecipeStore:
    """Shared store; builds the bundled starter set on first use if no library exists yet."""
    global _store
    if _store is None:
        _store = RecipeStore()
        if _store.count() == 0:
            from recipes.build import load_sample_into
            load_sample_into(_store)
    return _store
