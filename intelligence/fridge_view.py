"""The fridge the way Home shows it: one entry per product (freezer apart), with the same
amounts and day words, so the assistant and the app never disagree about what's there."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from intelligence import clock
from intelligence.consumption import days_left
from intelligence.expiry import days_until
from inventory.database import Database
from inventory.units import format_amount

FACT_DAYS = 7  # "going bad this week"
GUESS_DAYS = range(2, 7)  # an estimated date is said as "around Thursday" only for these
# Photos of items nobody could name, uploaded by the camera bench (vision/snap.py); shown on their tiles.
ITEM_IMAGE_DIR = Path(__file__).resolve().parent.parent / "data" / "item_images"


def inventory_entries(db: Database) -> list[dict]:
    """What /api/summary lists: per product (and apart in the freezer), the total, the soonest batch,
    the shelf holding most of it, and the usage forecast."""
    by_product: dict[tuple[int, bool], dict] = {}
    for item in db.active_items():
        product = db.get_product(item["product_id"])
        if product is None:
            continue
        frozen = item["location"] == "freezer"
        entry = by_product.setdefault((product["id"], frozen), {
            "product_id": product["id"], "name": product["name"], "category": product["category"],
            "grams": 0.0, "package_size_g": product["usual_package_size_g"],
            "unit": product["unit"], "grams_per_unit": product["grams_per_unit"],
            "expires_in_days": None, "expiry_estimated": False, "soonest_batch": None,
            "location": item["location"], "shelf": None if frozen else item["shelf"], "_shelf_grams": -1.0,
            "leftovers": product["recipe_id"] is not None, "image_url": None,
        })
        entry["grams"] += item["grams"]
        if (ITEM_IMAGE_DIR / f"{item['id']}.jpg").exists():
            entry["image_url"] = f"/api/items/{item['id']}/image"
        if item["location"] == "fridge":
            entry["location"] = "fridge"  # in the fridge at all -> show it on the fridge screen
        # A product split across shelves is shown on the shelf holding most of it.
        if not frozen and item["shelf"] is not None and item["grams"] > entry["_shelf_grams"]:
            entry["shelf"], entry["_shelf_grams"] = item["shelf"], item["grams"]
        if item["expiration_date"]:
            d = days_until(item["expiration_date"])
            batch = entry["soonest_batch"]
            if batch and batch["expiration_date"] == item["expiration_date"]:
                batch["grams"] += item["grams"]
            elif entry["expires_in_days"] is None or d < entry["expires_in_days"]:
                entry["expires_in_days"] = d
                entry["expiry_estimated"] = bool(item["expiration_estimated"])
                entry["soonest_batch"] = {"grams": item["grams"], "expiration_date": item["expiration_date"],
                                          "expires_in_days": d}

    inventory = []
    for entry in by_product.values():
        entry.pop("_shelf_grams")
        fill = (entry["grams"] / entry["package_size_g"]) if entry["package_size_g"] else None
        entry = {**entry, "days_left": days_left(db, entry["product_id"]), "fill_fraction": fill}
        inventory.append({**entry, "likely_wasted_g": wasted_grams(entry)})
    return inventory


def fridge_entry(db: Database, product_id: int) -> dict | None:
    """The product's Home row: the part outside the freezer if there is one."""
    entries = [e for e in inventory_entries(db) if e["product_id"] == product_id]
    return next((e for e in entries if e["location"] != "freezer"), entries[0] if entries else None)


def wasted_grams(entry: dict) -> float | None:
    """Grams you won't have used by the day it goes bad, at your usual rate. None when you'll finish it
    first, or there's no date or history. Leftovers are counted in servings, not forecast."""
    runs_out, goes_bad = entry["days_left"], entry["expires_in_days"]
    if entry["leftovers"] or runs_out is None or goes_bad is None or runs_out <= goes_bad:
        return None
    return entry["grams"] * (1 - max(goes_bad, 0) / runs_out)


def day_word(days: int, today: date | None = None) -> str:
    """Like the app's whenWord: 'today', 'tomorrow', 'Thursday', 'in about a week', 'in about 3 weeks'."""
    if days < 1:
        return "today"
    if days == 1:
        return "tomorrow"
    if days <= 6:
        return ((today or clock.local_today()) + timedelta(days=days)).strftime("%A")
    weeks = round(days / 7)
    return "in about a week" if weeks <= 1 else f"in about {weeks} weeks"


def goes_bad_text(entry: dict) -> str | None:
    """The Home row's words, lower case: 'goes bad tomorrow', 'goes bad around Thursday', 'expired'.
    Leftovers keep a fixed 3 days, so they're never 'around'."""
    days = entry["expires_in_days"]
    if days is None:
        return None
    if days < 0:
        return "expired"
    around = "around " if entry["expiry_estimated"] and not entry["leftovers"] and days in GUESS_DAYS else ""
    return f"goes bad {around}{day_word(days)}"


def amount_text(entry: dict) -> str:
    return format_amount(entry["grams"], entry["unit"], entry["grams_per_unit"], entry["name"])


def likely_wasted(entry: dict) -> str | None:
    """'about 122 g' you won't have used by the day it goes bad, at your usual rate (same as the app)."""
    left = entry["likely_wasted_g"]
    if left is None:
        return None
    amount = format_amount(left, entry["unit"], entry["grams_per_unit"], entry["name"])
    return amount if amount.startswith("about ") else f"about {amount}"


def _soonest_first(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e["expires_in_days"] is None, e["expires_in_days"] or 0, e["name"]))


def chat_inventory(db: Database) -> dict:
    """get_inventory for the assistant: human amounts and day words, soonest first, freezer apart."""
    entries = inventory_entries(db)
    items = [
        {"name": e["name"], "amount": amount_text(e), "goes_bad": goes_bad_text(e), "days": e["expires_in_days"],
         "leftovers": e["leftovers"], "likely_throw_away": likely_wasted(e), "location": e["location"]}
        for e in _soonest_first([e for e in entries if e["location"] != "freezer"])
    ]
    freezer = [{"name": e["name"], "amount": amount_text(e)}
               for e in _soonest_first([e for e in entries if e["location"] == "freezer"])]
    return {"items": items, "freezer": freezer}


def leftovers_line(entry: dict) -> str:
    """'Greek Stuffed Chicken leftovers: 3 servings, keeps until Tuesday'."""
    keeps = entry["expires_in_days"]
    until = "" if keeps is None else (", expired" if keeps < 0 else f", keeps until {day_word(keeps)}")
    return f"{entry['name']}: {amount_text(entry)}{until}"


def going_bad_soon(db: Database, within_days: int = FACT_DAYS) -> list[dict]:
    """Fridge and pantry entries (not the freezer) that go bad within a week, soonest first."""
    return _soonest_first([e for e in inventory_entries(db) if e["location"] != "freezer"
                           and e["expires_in_days"] is not None and e["expires_in_days"] <= within_days])


def fact_block(db: Database) -> str:
    """Facts added to every chat turn, so the assistant answers from what Home shows."""
    entries = inventory_entries(db)
    leftovers = [e for e in _soonest_first(entries) if e["leftovers"] and e["location"] != "freezer"]
    soon = going_bad_soon(db)
    lines = ["[Fridge facts from the app, exact and current."]
    lines.append("Leftovers: " + ("; ".join(leftovers_line(e) for e in leftovers) if leftovers else "none") + ".")
    lines.append(f"Going bad within {FACT_DAYS} days, soonest first: "
                 + ("; ".join(f"{e['name']} ({amount_text(e)}) {goes_bad_text(e)}" for e in soon) if soon else "nothing")
                 + ".]")
    return "\n".join(lines)
