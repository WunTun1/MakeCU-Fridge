"""The shopping list you actually shop from: the restock plan merged with
things you added yourself or for a recipe. Checks, removals and the trip
horizon live in the database, so nothing resets on reload.

Plan rows are keyed by normalized name + trip date: checking or removing
"Milk" for Saturday's trip sticks until the plan moves to a different trip.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from intelligence import clock
from inventory.database import Database
from intelligence.grocery import DEFAULT_TRIP_CADENCE_DAYS, grocery_plan, next_trip_date, use_first
from recipes.ingredients import canonical, matches
from recipes.titles import clean_title

HORIZON_KEY = "grocery.horizon"
TRIP_KEY = "grocery.trip_date"
HORIZONS = (1, 3, 7)
USE_FIRST_ROWS = 3

_UNIT = r"(?:kg|g|l|ml|lb|lbs|oz)"
_LEADING = re.compile(rf"^(\d+(?:\.\d+)?)\s*({_UNIT})?\s+(.+)$", re.I)     # "6 apples", "2 L milk"
_TRAILING = re.compile(rf"^(.+?)\s+(\d+(?:\.\d+)?)\s*({_UNIT})?$", re.I)   # "apples 6", "milk 2 L"
# "a dozen eggs" is 12 eggs; longest phrase first.
AMOUNT_WORDS = [("half a dozen", 6), ("a dozen", 12), ("a couple of", 2), ("a couple", 2), ("an", 1), ("a", 1)]


def normalize(name: str) -> str:
    return canonical(name) or name.strip().lower()


def parse_entry(text: str) -> tuple[str, str | None]:
    """'apples 6' / '6 apples' -> ('apples', '6'); '2 L milk' -> ('milk', '2 L'); 'a dozen eggs' -> ('eggs', '12')."""
    text = " ".join(text.split())
    for words, count in AMOUNT_WORDS:
        if text.lower().startswith(words + " ") and len(text) > len(words) + 1:
            return text[len(words) + 1:], str(count)
    lead = _LEADING.match(text)
    if lead:
        number, unit, name = lead.groups()
    else:
        trail = _TRAILING.match(text)
        if not trail:
            return text, None
        name, number, unit = trail.groups()
    unit = (unit or "").lower()
    unit = "L" if unit == "l" else unit
    return name.strip(), f"{number} {unit}".strip()


def get_horizon(db: Database) -> int | None:
    value = db.get_setting(HORIZON_KEY)
    return int(value) if value and value.isdigit() and int(value) in HORIZONS else None


def set_horizon(db: Database, trip_in_days: int | None) -> None:
    db.set_setting(HORIZON_KEY, str(trip_in_days) if trip_in_days in HORIZONS else None)


def trip_date_for(db: Database, trip_in_days: int | None) -> date | None:
    if trip_in_days is not None:
        return clock.date_in(trip_in_days)
    return next_trip_date(db)


def days_away(day: date | None) -> int | None:
    return (day - clock.local_today()).days if day else None


def covers_until(trip: date | None) -> str | None:
    """The plan buys enough for a week after the trip."""
    return (trip + timedelta(days=DEFAULT_TRIP_CADENCE_DAYS)).isoformat() if trip else None


def _visible(entry, trip: str | None) -> bool:
    if entry["hidden"]:
        return False
    return entry["source"] != "plan" or entry["trip_date"] == trip


def _product_units(db: Database) -> dict[int, tuple[str, float]]:
    with db.cursor() as cur:
        cur.execute("SELECT id, unit, grams_per_unit FROM products")
        return {r["id"]: (r["unit"], r["grams_per_unit"]) for r in cur.fetchall()}


def build_list(db: Database) -> dict:
    """{trip_in_days, trip_date, covers_until, items}; each item has an id you can check off or remove."""
    horizon = get_horizon(db)
    trip = trip_date_for(db, horizon)
    trip_iso = trip.isoformat() if trip else None
    db.set_setting(TRIP_KEY, trip_iso)

    entries = db.grocery_entries()
    plan = grocery_plan(db, horizon) if trip else []
    units = _product_units(db)
    plan_by_norm = {normalize(p.product_name): p for p in plan}

    own_norms = {e["norm"] for e in entries if e["source"] != "plan" and not e["hidden"]}
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
        if e["source"] == "plan" and (p is None or e["norm"] in own_norms):
            continue  # the plan no longer needs it, or your own row for that food stands for it
        unit, per = units.get(p.product_id, ("g", 1.0)) if p else ("g", 1.0)
        items.append({
            "id": e["id"], "name": e["name"], "amount": e["amount"], "source": e["source"],
            "recipe_id": e["recipe_id"], "checked": bool(e["checked"]),
            "recipe_name": clean_title(e["recipe_name"]) if e["recipe_name"] else None,
            "unit": unit, "grams_per_unit": per,
            "plan": p.__dict__ if p else None,
        })
    listed = {normalize(i["name"]) for i in items if not i["checked"]}
    return {"trip_in_days": horizon, "trip_date": trip_iso, "trip_days_away": days_away(trip),
            "covers_until": covers_until(trip), "items": items,
            "use_first": [u for u in use_first(db, horizon) if normalize(u["name"]) not in listed][:USE_FIRST_ROWS]}


def add_entry(
    db: Database, name: str, source: str, recipe_id: int | None = None, recipe_name: str | None = None,
    amount: str | None = None,
) -> tuple[int, bool]:
    """(row id, whether it's new). A food already on the list isn't added again: the row is un-checked
    and a manual amount is added to its own ('Eggs · 6' plus 'a dozen eggs' is 'Eggs · 18')."""
    name = " ".join(name.split())
    if amount is None:
        name, amount = parse_entry(name)
    norm = normalize(name)
    trip = db.get_setting(TRIP_KEY)
    rows = [e for e in db.grocery_entries() if e["norm"] == norm and _visible(e, trip)]
    # Adding a food yourself (or from a recipe) makes it your own row, even when the restock plan
    # already lists it: the plan's row then steps aside (see grocery()). Only the plan reuses plan rows.
    own = next((e for e in rows if e["source"] != "plan"), None)
    existing = own if source != "plan" else (own or (rows[0] if rows else None))
    if existing:
        db.set_grocery_checked(existing["id"], False)
        if amount and existing["source"] != "plan":
            db.set_grocery_amount(existing["id"], _sum_amounts(existing["amount"], amount))
        return existing["id"], False
    return db.add_grocery_entry(name, norm, source, recipe_id, recipe_name, amount=amount), True


def _sum_amounts(have: str | None, more: str) -> str:
    """'6' + '12' -> '18'; '1 L' + '2 L' -> '3 L'; different units keep the newer amount."""
    if not have:
        return more
    a, b = have.split(maxsplit=1), more.split(maxsplit=1)
    try:
        if a[1:] == b[1:]:
            return " ".join([f"{float(a[0]) + float(b[0]):g}", *a[1:]])
    except ValueError:
        pass
    return more


def add_entries(
    db: Database, names: list[str], source: str, recipe_id: int | None = None, recipe_name: str | None = None,
    amounts: list[str | None] | None = None,
) -> list[int]:
    """Grocery's + button: 'apples 6' is stored as apples, amount 6. A recipe (or the restock row) gives
    the amount separately, in `amounts`."""
    ids = []
    for i, text in enumerate(n.strip() for n in names):
        if text:
            name, amount = parse_entry(text)
            given = amounts[i] if amounts and i < len(amounts) else None
            ids.append(add_entry(db, name, source, recipe_id, recipe_name, given or amount)[0])
    return ids


def check_off(db: Database, product_name: str) -> dict | None:
    """You put it in the fridge, so you bought it: check off every open row for that food. Returns the
    first one, for the 'Checked off Eggs' note."""
    trip = db.get_setting(TRIP_KEY)
    norm = normalize(product_name)
    rows = [e for e in db.grocery_entries()
            if not e["checked"] and _visible(e, trip) and (e["norm"] == norm or matches(e["norm"], norm))]
    for e in rows:
        db.set_grocery_checked(e["id"], True)
    return {"id": rows[0]["id"], "name": rows[0]["name"]} if rows else None


def listed_norms(db: Database) -> set[str]:
    """Foods you put on the list yourself (by hand or from a recipe). The planner's own
    suggestions don't count: you haven't said yes to them."""
    trip = db.get_setting(TRIP_KEY)
    return {e["norm"] for e in db.grocery_entries() if _visible(e, trip) and e["source"] != "plan"}
