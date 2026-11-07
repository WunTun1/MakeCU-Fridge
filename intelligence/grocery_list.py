"""The shopping list you actually shop from: the restock plan merged with
things you added yourself or for a recipe. Checks and the trip horizon live
in the database, so nothing resets on reload.

Plan rows are keyed by normalized name + trip date: checking "Milk" for
Saturday's trip stays checked until the plan moves to a different trip.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from inventory.database import Database
from intelligence.grocery import grocery_plan, next_trip_date
from recipes.ingredients import canonical

HORIZON_KEY = "grocery.horizon"
TRIP_KEY = "grocery.trip_date"
HORIZONS = (1, 3, 7)


def normalize(name: str) -> str:
    return canonical(name) or name.strip().lower()


def get_horizon(db: Database) -> int | None:
    value = db.get_setting(HORIZON_KEY)
    return int(value) if value and value.isdigit() and int(value) in HORIZONS else None


def set_horizon(db: Database, trip_in_days: int | None) -> None:
    db.set_setting(HORIZON_KEY, str(trip_in_days) if trip_in_days in HORIZONS else None)


def trip_date_for(db: Database, trip_in_days: int | None) -> date | None:
    if trip_in_days is not None:
        return datetime.now(timezone.utc).date() + timedelta(days=trip_in_days)
    return next_trip_date(db)


def _visible(entry, trip: str | None) -> bool:
    if entry["source"] != "plan":
        return True
    return not entry["hidden"] and entry["trip_date"] == trip


def _product_units(db: Database) -> dict[int, tuple[str, float]]:
    with db.cursor() as cur:
        cur.execute("SELECT id, unit, grams_per_unit FROM products")
        return {r["id"]: (r["unit"], r["grams_per_unit"]) for r in cur.fetchall()}


def build_list(db: Database) -> dict:
    """{trip_in_days, trip_date, items}; each item has an id you can check off."""
    horizon = get_horizon(db)
    trip = trip_date_for(db, horizon)
    trip_iso = trip.isoformat() if trip else None
    db.set_setting(TRIP_KEY, trip_iso)

    entries = db.grocery_entries()
    plan = grocery_plan(db, horizon) if trip else []
    units = _product_units(db)
    plan_by_norm = {normalize(p.product_name): p for p in plan}

    own_norms = {e["norm"] for e in entries if e["source"] != "plan"}
    plan_entries = {e["norm"]: e for e in entries if e["source"] == "plan" and e["trip_date"] == trip_iso}
    for norm, p in plan_by_norm.items():
        if norm not in own_norms and norm not in plan_entries:
            entry_id = db.add_grocery_entry(p.product_name, norm, "plan", trip_date=trip_iso)
            plan_entries[norm] = db.get_grocery_entry(entry_id)

    items = []
    for e in db.grocery_entries():
        if not _visible(e, trip_iso):
            continue
        p = plan_by_norm.get(e["norm"])
        if e["source"] == "plan" and p is None:
            continue  # the plan no longer needs it
        unit, per = units.get(p.product_id, ("g", 1.0)) if p else ("g", 1.0)
        items.append({
            "id": e["id"], "name": e["name"], "source": e["source"], "recipe_id": e["recipe_id"],
            "recipe_name": e["recipe_name"], "checked": bool(e["checked"]),
            "unit": unit, "grams_per_unit": per,
            "plan": p.__dict__ if p else None,
        })
    return {"trip_in_days": horizon, "trip_date": trip_iso, "items": items}


def add_entries(
    db: Database, names: list[str], source: str, recipe_id: int | None = None, recipe_name: str | None = None
) -> list[int]:
    """Adds each name unless it's already on the list (then it's just un-checked)."""
    trip = db.get_setting(TRIP_KEY)
    ids = []
    for name in (n.strip() for n in names):
        if not name:
            continue
        norm = normalize(name)
        existing = next((e for e in db.grocery_entries() if e["norm"] == norm and _visible(e, trip)), None)
        if existing:
            db.set_grocery_checked(existing["id"], False)
            ids.append(existing["id"])
        else:
            ids.append(db.add_grocery_entry(name, norm, source, recipe_id, recipe_name))
    return ids


def listed_norms(db: Database) -> set[str]:
    trip = db.get_setting(TRIP_KEY)
    return {e["norm"] for e in db.grocery_entries() if _visible(e, trip)}
