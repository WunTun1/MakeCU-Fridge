"""Learns what you like to eat — plain math over your own history, no ML.

Signals, strongest first:
  cooked a recipe  (you made it: its recipe, cuisine and main ingredients)
  liked / disliked (thumbs on a recipe card)
  asked            (you asked for "Italian", "something with chicken")
  habits           (what you keep buying and using, from the fridge's event log)
Every signal fades with a 30-day half-life, like the usage forecasts, so the
profile follows changing tastes instead of locking in last month's phase.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from inventory.database import Database
from recipes.ingredients import canonical, is_staple
from recipes.store import Recipe

HALF_LIFE_DAYS = 30.0
LOOKBACK_DAYS = 180
SIGNAL_WEIGHT = {"cooked": 3.0, "liked": 2.0, "disliked": -3.0, "asked": 0.6}
HABIT_WEIGHT_PER_EVENT = 0.15
LIKE_WEIGHT = 2.0   # a like in Settings counts about as much as a thumbs-up
MAIN_INGREDIENTS = 6  # the first few non-staple ingredients characterize a recipe


def recipe_features(recipe: Recipe) -> list[str]:
    feats = [f"recipe:{recipe.id}"]
    if recipe.cuisine:
        feats.append(f"cuisine:{recipe.cuisine}")
    mains = [c for c in recipe.canon_ingredients if c and not is_staple(c)][:MAIN_INGREDIENTS]
    feats.extend(f"ingredient:{c}" for c in mains)
    return feats


def record_recipe(db: Database, signal: str, recipe: Recipe) -> None:
    weight = SIGNAL_WEIGHT[signal]
    feats = recipe_features(recipe)
    # The recipe itself carries the full weight; its cuisine/ingredients generalize at half.
    db.log_taste(signal, [(f, weight if f.startswith("recipe:") else weight / 2) for f in feats])


def record_request(db: Database, cuisine: str | None = None, ingredients: list[str] | None = None) -> None:
    feats = []
    if cuisine:
        feats.append((f"cuisine:{cuisine.strip().lower().replace(' ', '-')}", SIGNAL_WEIGHT["asked"]))
    feats.extend((f"ingredient:{canonical(i)}", SIGNAL_WEIGHT["asked"]) for i in ingredients or [] if canonical(i))
    if feats:
        db.log_taste("asked", feats)


def _decay(ts: str, now: datetime) -> float:
    age_days = (now - datetime.fromisoformat(ts)).total_seconds() / 86400
    return 0.5 ** (max(age_days, 0) / HALF_LIFE_DAYS)


def profile(db: Database) -> dict[str, float]:
    """feature -> affinity in (-1, 1)."""
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=LOOKBACK_DAYS)).isoformat()
    raw: dict[str, float] = defaultdict(float)

    for e in db.taste_events_since(since):
        raw[e["feature"]] += e["weight"] * _decay(e["occurred_at"], now)

    # Habits: products you keep adding and using are things you like.
    names: dict[int, str] = {}
    for e in db.all_events(since=since):
        if e["event_type"] not in ("add", "consume") or e["product_id"] is None:
            continue
        if e["product_id"] not in names:
            p = db.get_product(e["product_id"])
            names[e["product_id"]] = canonical(p["name"]) if p else ""
        if names[e["product_id"]]:
            raw[f"ingredient:{names[e['product_id']]}"] += HABIT_WEIGHT_PER_EVENT * _decay(e["occurred_at"], now)

    # Likes from Settings: a steady pull toward those foods and cuisines.
    row = db.get_profile()
    for like in json.loads((row["likes"] if row is not None else None) or "[]"):
        key = like.strip().lower()
        if key:
            raw[f"cuisine:{key}"] += LIKE_WEIGHT
            raw[f"ingredient:{canonical(key) or key}"] += LIKE_WEIGHT

    return {f: math.tanh(v / 3.0) for f, v in raw.items() if abs(v) > 1e-6}


def recipe_affinity(prof: dict[str, float], recipe: Recipe) -> float:
    """-1..1: how much this recipe fits what you've liked."""
    if not prof:
        return 0.0
    feats = recipe_features(recipe)
    direct = prof.get(feats[0], 0.0)
    cuisine = prof.get(f"cuisine:{recipe.cuisine}", 0.0) if recipe.cuisine else 0.0
    ingredient_scores = [prof.get(f, 0.0) for f in feats if f.startswith("ingredient:")]
    ingredients = sum(ingredient_scores) / len(ingredient_scores) if ingredient_scores else 0.0
    if direct:
        return max(-1.0, min(1.0, 0.6 * direct + 0.25 * cuisine + 0.15 * ingredients))
    return max(-1.0, min(1.0, 0.5 * cuisine + 0.5 * ingredients))


def top_preferences(prof: dict[str, float], kind: str, n: int = 3) -> list[str]:
    """Most-liked cuisines or ingredients, e.g. top_preferences(p, 'cuisine') -> ['italian', 'thai']."""
    prefix = f"{kind}:"
    ranked = sorted(((v, f[len(prefix):]) for f, v in prof.items() if f.startswith(prefix) and v > 0.05), reverse=True)
    return [name for _, name in ranked[:n]]
