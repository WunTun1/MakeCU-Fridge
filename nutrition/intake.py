"""What the user actually ate vs. what left the fridge. Section 11.

Fridge removals != eating (shared meals, other people) — meals are logged
explicitly, either as a recipe ("I made this" -> how many servings did YOU
eat) or a manual entry ("I had a yogurt").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from inventory import events as inv_events
from inventory.database import Database

PERIODS = {"today", "week"}
# Protein supplies at least this share of the calorie goal: the goal is protein-led.
PROTEIN_MODE_SHARE = 0.25
KCAL_PER_G_PROTEIN = 4
MACROS = ("calories", "protein_g", "carbs_g", "fat_g")


def protein_mode(profile) -> bool:
    """Protein-led goals (More protein: 160 g of 2200 kcal is 29%) rank recipes by protein."""
    protein, calories = profile["daily_protein_g"], profile["daily_calories"]
    return bool(protein and calories) and protein * KCAL_PER_G_PROTEIN / calories >= PROTEIN_MODE_SHARE


def _period_start(period: str) -> str:
    now = datetime.now(timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        start = (now - timedelta(days=7))
    else:
        raise ValueError(f"unknown period: {period}")
    return start.isoformat()


def get_intake(db: Database, period: str = "today") -> dict:
    meals = db.meals_since(_period_start(period))
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for m in meals:
        for key in totals:
            if m[key] is not None:
                totals[key] += m[key]
    return {"period": period, "totals": totals, "meal_count": len(meals)}


def meals(db: Database, period: str = "today") -> list[dict]:
    """Every meal logged in the period, oldest first."""
    return [
        {"id": m["id"], "name": m["recipe_name"], "servings": m["servings"], "occurred_at": m["occurred_at"],
         "source": m["source"], **{k: m[k] for k in MACROS}}
        for m in db.meals_since(_period_start(period))
    ]


def log_meal_eaten(
    db: Database,
    recipe_name: str | None,
    servings: float,
    nutrition_per_serving: dict,
    source: str = "manual",
) -> int:
    return db.log_meal(
        recipe_name=recipe_name,
        servings=servings,
        calories=nutrition_per_serving.get("calories", 0) * servings if nutrition_per_serving.get("calories") else None,
        protein_g=nutrition_per_serving.get("protein_g", 0) * servings if nutrition_per_serving.get("protein_g") else None,
        carbs_g=nutrition_per_serving.get("carbs_g", 0) * servings if nutrition_per_serving.get("carbs_g") else None,
        fat_g=nutrition_per_serving.get("fat_g", 0) * servings if nutrition_per_serving.get("fat_g") else None,
        source=source,
    )


def log_nutrition(db: Database, name: str, protein_g: float | None, calories: float | None,
                  source: str = "manual", **macros: float | None) -> int:
    """Numbers off a label ('24 g protein, 120 kcal'): counted in today's intake, nothing leaves the fridge."""
    return db.log_meal(recipe_name=name, servings=1, calories=calories, protein_g=protein_g,
                       carbs_g=macros.get("carbs_g"), fat_g=macros.get("fat_g"), source=source)


def eat_from_fridge(db: Database, product_id: int, grams: float, name: str, source: str = "manual") -> dict | None:
    """Ate some of a fridge item as it is (a yogurt, a serving of leftovers): it comes out of the
    fridge, soonest to go bad first, and its nutrition is logged. Undo with RecipeEngine.undo_meal."""
    product = db.get_product(product_id)
    items = sorted((i for i in db.active_items() if i["product_id"] == product_id),
                   key=lambda i: (i["expiration_date"] is None, i["expiration_date"] or "", i["id"]))
    if product is None or not items:
        return None
    grams = min(grams, sum(i["grams"] for i in items))
    meal = {k: (product[f"{k}_per_100g"] * grams / 100 if product[f"{k}_per_100g"] is not None else None)
            for k in MACROS}
    servings = grams / product["grams_per_unit"] if product["unit"] == "count" else 1
    meal_id = db.log_meal(recipe_name=name, servings=servings, source=source, **meal)
    left = grams
    for item in items:
        if left <= 0:
            break
        take = min(item["grams"], left)
        inv_events.apply_consume(db, item["id"], take, meta={"meal_id": meal_id})
        left -= take
    return {"meal_id": meal_id, "grams": grams, **meal}


def eat_product(db: Database, product_id: int, grams: float | None = None) -> dict | None:
    """Ate some of a product as it is; one unit (a serving of leftovers, an egg) when `grams` is left out.
    Leftovers are logged under the recipe's name. None when there's none left."""
    product = db.get_product(product_id)
    if product is None:
        return None
    leftovers = product["recipe_id"] is not None
    name = product["name"].removesuffix(" leftovers") if leftovers else product["name"]
    return eat_from_fridge(db, product_id, grams or product["grams_per_unit"], name,
                           source="leftovers" if leftovers else "fridge")
