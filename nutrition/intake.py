"""What the user actually ate vs. what left the fridge. Section 11.

Fridge removals != eating (shared meals, other people) — meals are logged
explicitly, either as a recipe ("I made this" -> how many servings did YOU
eat) or a manual entry ("I had a yogurt").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from inventory.database import Database

PERIODS = {"today", "week"}


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
