"""Next trip date + shopping list. Section 10.

Two kinds of suggestions:
  restock  staples you're running out of (usage forecasting)
  unlock   a few ingredients that would let you cook several recipes you'd
           probably like (taste profile + recipe library)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from inventory.database import Database
from intelligence import taste
from intelligence.consumption import days_left, grams_on_hand, usage_rate_g_per_day
from recipes.engine import (DINNER_MINUTES_RELAXED, dislike_hits, fits_dinner, has_allergen, normalized_title,
                            protein_floor)
from recipes.ingredients import canonical

UNLOCK_POOL_PER_SOURCE = 300
UNLOCK_MAX_MISSING = 2

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

    soonest: date | None = None
    for staple in staples:
        dl = days_left(db, staple["id"])
        if dl is None:
            continue
        run_out = datetime.now(timezone.utc).date() + timedelta(days=dl)
        if soonest is None or run_out < soonest:
            soonest = run_out

    if soonest is None:
        return None
    today = datetime.now(timezone.utc).date()
    if (soonest - today).days > NO_TRIP_NEEDED_WITHIN_DAYS:
        return None
    # Something running out today means "shop today", not a date in the past.
    return max(soonest - timedelta(days=1), today)


def grocery_plan(
    db: Database, trip_in_days: int | None = None, cadence_days: int = DEFAULT_TRIP_CADENCE_DAYS
) -> list[GroceryItem]:
    trip_date = (
        datetime.now(timezone.utc).date() + timedelta(days=trip_in_days)
        if trip_in_days is not None
        else next_trip_date(db)
    )
    if trip_date is None:
        return []

    with db.cursor() as cur:
        cur.execute("SELECT * FROM products WHERE is_staple = 1")
        staples = cur.fetchall()

    plan: list[GroceryItem] = []
    for product in staples:
        rate = usage_rate_g_per_day(db, product["id"])
        if rate <= 0:
            continue
        on_hand = grams_on_hand(db, product["id"])
        days_until_trip = max((trip_date - datetime.now(timezone.utc).date()).days, 0)
        on_hand_at_trip = max(on_hand - rate * days_until_trip, 0.0)

        needed_for_period = rate * cadence_days * (1 + SAFETY_BUFFER_PCT)
        buy_grams = max(needed_for_period - on_hand_at_trip, 0.0)
        if buy_grams <= 0:
            continue

        package_size = product["usual_package_size_g"]
        buy_packages = math.ceil(buy_grams / package_size) if package_size else None
        if buy_packages:
            buy_grams = buy_packages * package_size

        plan.append(GroceryItem(
            product_id=product["id"],
            product_name=product["name"],
            buy_grams=buy_grams,
            buy_packages=buy_packages,
            reason=f"Runs out in about {round(on_hand / rate)} days. You use about {rate:.0f} g a day.",
            on_hand_g=on_hand,
            rate_g_per_day=rate,
            runs_out_in_days=on_hand / rate,
        ))
    return plan


@dataclass
class UnlockSuggestion:
    buy: list[str]                       # ingredient names to add to the list
    unlocks: int                         # recipes this makes cookable
    examples: list[str] = field(default_factory=list)
    recipe_ids: list[int] = field(default_factory=list)


def unlock_suggestions(db: Database, engine, limit: int = 3, high_protein: bool = False) -> list[UnlockSuggestion]:
    """Which purchases would let you cook the most recipes you'd likely enjoy?

    Pool: recipes from your favorite cuisines and ingredients (or, with no taste
    history yet, recipes built around what's already in the fridge), keeping those
    only 1-2 ingredients away after swaps. Purchases are chosen greedily, each one
    counting what earlier picks already completed: "parmesan unlocks 3; then
    lemons unlock 2 more". When no single item completes anything, the best pair
    is suggested together. Recipes count more the better they fit your taste. In protein mode
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
    for recipe in engine.store.get_many(list(pool)):
        if has_allergen(recipe, allergies) or dislike_hits(recipe, dislikes) or not fits_dinner(recipe):
            continue
        title = normalized_title(recipe.name)
        if title in seen_titles:
            continue
        m = engine.analyze(recipe, pantry)
        if not 1 <= len(m.to_buy) <= UNLOCK_MAX_MISSING:
            continue
        seen_titles.add(title)
        missing = frozenset(canonical(n) or n.lower() for n in m.to_buy)
        weight = 0.5 + 0.5 * (taste.recipe_affinity(prefs, recipe) + 1) / 2
        candidates.append((missing, weight, recipe))

    if high_protein:
        candidates = protein_floor(candidates, lambda c: c[2].nutrition.get("protein_g"))

    picks: list[UnlockSuggestion] = []
    bought: set[str] = set()
    remaining = list(candidates)
    while remaining and len(picks) < limit:
        items = {i for missing, _, _ in remaining for i in missing}

        def completes(buy: set[str]):
            return [(w, r) for missing, w, r in remaining if missing <= bought | buy]

        best_single = max(items, key=lambda i: sum(w for w, _ in completes({i})), default=None)
        best_buy = {best_single} if best_single else set()
        if not best_single or not completes(best_buy):
            # Nothing completes alone — find the pair that does the most.
            pairs = [missing for missing, _, _ in remaining if len(missing) == 2]
            if not pairs:
                break
            best_buy = set(max(pairs, key=lambda p: sum(w for w, _ in completes(set(p)))))

        done = sorted(completes(best_buy), key=lambda wr: wr[0], reverse=True)
        picks.append(UnlockSuggestion(
            buy=sorted(best_buy), unlocks=len(done),
            examples=[r.name for _, r in done[:3]], recipe_ids=[r.id for _, r in done[:10]],
        ))
        bought |= best_buy
        remaining = [c for c in remaining if not c[0] <= bought]
    return picks
