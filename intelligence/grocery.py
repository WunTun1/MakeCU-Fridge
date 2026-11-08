"""Next trip date + shopping list. Section 10.

Two kinds of suggestions:
  restock  staples you're running out of (usage forecasting)
  unlock   a few ingredients that would let you cook several recipes you'd
           probably like (taste profile + recipe library)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from inventory.database import Database
from intelligence import clock, taste
from intelligence.consumption import days_left, grams_on_hand, usage_rate_g_per_day
from intelligence.fridge_view import inventory_entries
from recipes.engine import DINNER_MINUTES_RELAXED, dislike_hits, fits_dinner, normalized_title, protein_floor, safe_recipes
from recipes.ingredients import canonical, is_specialty

UNLOCK_POOL_PER_SOURCE = 300

NO_TRIP_NEEDED_WITHIN_DAYS = 14
DEFAULT_TRIP_CADENCE_DAYS = 7
SAFETY_BUFFER_PCT = 0.15


@dataclass
class GroceryItem:
    product_id: int
    product_name: str
    buy_grams: float
    buy_packages: int | None
    reason: str
    on_hand_g: float = 0.0
    rate_g_per_day: float = 0.0
    runs_out_in_days: float | None = None


def next_trip_date(db: Database) -> date | None:
    """Earliest date a staple runs out, minus 1 day."""
    with db.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE is_staple = 1")
        staples = cur.fetchall()

    today = clock.local_today()
    soonest: date | None = None
    for staple in staples:
        dl = days_left(db, staple["id"])
        if dl is None:
            continue
        run_out = today + timedelta(days=dl)
        if soonest is None or run_out < soonest:
            soonest = run_out

    if soonest is None:
        return None
    if (soonest - today).days > NO_TRIP_NEEDED_WITHIN_DAYS:
        return None
    # Something running out today means "shop today", not a date in the past.
    return max(soonest - timedelta(days=1), today)


def _restock(db: Database, product, trip_date: date, cadence_days: int) -> GroceryItem | None:
    """Enough for `cadence_days` after the trip, in whole packages; None when you have that already."""
    rate = usage_rate_g_per_day(db, product["id"])
    if rate <= 0:
        return None
    on_hand = grams_on_hand(db, product["id"])
    days_until_trip = max((trip_date - clock.local_today()).days, 0)
    on_hand_at_trip = max(on_hand - rate * days_until_trip, 0.0)

    needed_for_period = rate * cadence_days * (1 + SAFETY_BUFFER_PCT)
    buy_grams = max(needed_for_period - on_hand_at_trip, 0.0)
    if buy_grams <= 0:
        return None

    package_size = product["usual_package_size_g"]
    buy_packages = math.ceil(buy_grams / package_size) if package_size else None
    if buy_packages:
        buy_grams = buy_packages * package_size
    return GroceryItem(
        product_id=product["id"],
        product_name=product["name"],
        buy_grams=buy_grams,
        buy_packages=buy_packages,
        reason=f"Runs out in about {round(on_hand / rate)} days. You use about {rate:.0f} g a day.",
        on_hand_g=on_hand,
        rate_g_per_day=rate,
        runs_out_in_days=on_hand / rate,
    )


def _staples(db: Database) -> list:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE is_staple = 1")
        return cur.fetchall()


def wasting(db: Database) -> dict[int, dict]:
    """Products Home says you'll likely throw some of away (outside the freezer), by product id."""
    return {e["product_id"]: e for e in inventory_entries(db)
            if e["location"] != "freezer" and (e["likely_wasted_g"] or 0) > 0}


def grocery_plan(
    db: Database, trip_in_days: int | None = None, cadence_days: int = DEFAULT_TRIP_CADENCE_DAYS
) -> list[GroceryItem]:
    """The restock list. Never restocks what's going to waste: that's in use_first instead."""
    trip_date = clock.date_in(trip_in_days) if trip_in_days is not None else next_trip_date(db)
    if trip_date is None:
        return []
    waste = wasting(db)
    plan = [_restock(db, p, trip_date, cadence_days) for p in _staples(db) if p["id"] not in waste]
    return [p for p in plan if p]


def use_first(db: Database, trip_in_days: int | None = None) -> list[dict]:
    """Food you'll likely throw some of away, soonest to go bad first, with what a normal restock
    would buy (restock_g, None when it wouldn't buy any) for someone who needs more anyway."""
    trip_date = clock.date_in(trip_in_days) if trip_in_days is not None else next_trip_date(db)
    staples = {p["id"]: p for p in _staples(db)}
    rows = []
    for e in sorted(wasting(db).values(), key=lambda e: (e["expires_in_days"], e["name"])):
        product = staples.get(e["product_id"])
        restock = product and _restock(db, product, trip_date or clock.local_today(), DEFAULT_TRIP_CADENCE_DAYS)
        rows.append({k: e[k] for k in ("product_id", "name", "unit", "grams_per_unit", "expires_in_days",
                                       "likely_wasted_g", "days_left")}
                    | {"restock_g": restock.buy_grams if restock else None})
    return rows


@dataclass
class UnlockSuggestion:
    buy: list[str]                       # ingredient names to add to the list
    unlocks: int                         # recipes this makes cookable
    examples: list[str] = field(default_factory=list)
    recipe_ids: list[int] = field(default_factory=list)


def unlock_suggestions(db: Database, engine, limit: int = 3, high_protein: bool = False) -> list[UnlockSuggestion]:
    """One item away: which single purchases would let you cook the most recipes you'd likely enjoy?

    Pool: recipes from your favorite cuisines and ingredients (or, with no taste
    history yet, recipes built around what's already in the fridge), keeping those
    exactly 1 ingredient away after swaps, and never one a specialty item (saffron,
    berbere) completes. Purchases are chosen greedily: "parmesan unlocks 3; then
    lemons unlock 2 more". Recipes count more the better they fit your taste. In protein mode
    only recipes with 25 g protein a serving count (20 g when fewer than 3 qualify).
    """
    prefs = taste.profile(db)
    pantry = engine.pantry()
    allergies, dislikes = engine.profile_filters()

    def search(query: str | None, cuisine: str | None):
        return engine.store.search(query, cuisine, DINNER_MINUTES_RELAXED, UNLOCK_POOL_PER_SOURCE, main_dish_only=True)

    pool: dict[int, float] = {}
    for cuisine in taste.top_preferences(prefs, "cuisine", 2):
        pool.update(search(None, cuisine))
    liked = taste.top_preferences(prefs, "ingredient", 4)
    seed = " ".join(liked) or " ".join(sorted(pantry.items)[:10])
    if seed:
        pool.update(search(seed, None))

    candidates: list[tuple[frozenset[str], float, object]] = []  # (missing set, weight, recipe)
    seen_titles: set[str] = set()
    for recipe in safe_recipes(engine.store.get_many(list(pool)), allergies):
        if dislike_hits(recipe, dislikes) or not fits_dinner(recipe):
            continue
        title = normalized_title(recipe.name)
        if title in seen_titles:
            continue
        m = engine.analyze(recipe, pantry)
        if len(m.to_buy) != 1 or is_specialty(m.to_buy[0]):
            continue
        seen_titles.add(title)
        missing = frozenset(canonical(n) or n.lower() for n in m.to_buy)
        weight = 0.5 + 0.5 * (taste.recipe_affinity(prefs, recipe) + 1) / 2
        candidates.append((missing, weight, recipe))

    if high_protein:
        candidates = protein_floor(candidates, lambda c: c[2].nutrition.get("protein_g"))

    picks: list[UnlockSuggestion] = []
    remaining = list(candidates)
    while remaining and len(picks) < limit:
        items = {i for missing, _, _ in remaining for i in missing}

        def completes(item: str):
            return [(w, r) for missing, w, r in remaining if item in missing]

        best = max(items, key=lambda i: sum(w for w, _ in completes(i)))
        done = sorted(completes(best), key=lambda wr: wr[0], reverse=True)
        picks.append(UnlockSuggestion(
            buy=[best], unlocks=len(done),
            examples=[r.name for _, r in done[:3]], recipe_ids=[r.id for _, r in done[:10]],
        ))
        remaining = [c for c in remaining if best not in c[0]]
    return picks
