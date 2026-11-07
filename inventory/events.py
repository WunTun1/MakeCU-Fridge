"""Turns a decided event (from fusion, chat, or a manual API call) into
database writes. This is the only place that mutates items + events together,
so the two tables never drift apart.
"""
from __future__ import annotations

import json

from .database import REMNANT_UNITS, Database

# A shelf drop within this much of a frozen item's weight is that item leaving, not a mystery.
PICKUP_TOLERANCE_G, PICKUP_TOLERANCE_PCT = 50.0, 0.15


def apply_add(
    db: Database,
    product_id: int,
    grams: float,
    location: str = "fridge",
    shelf: int | None = None,
    position: tuple[float, float] | None = None,
    expiration_date: str | None = None,
    confidence: float | None = None,
    expiration_estimated: bool = False,
    meta: dict | None = None,
) -> int:
    item_id = db.create_item(
        product_id, grams, location, shelf, position, expiration_date, confidence, expiration_estimated
    )
    db.log_event("add", product_id=product_id, item_id=item_id, grams_delta=grams, shelf=shelf, meta=meta)
    return item_id


def _picked_up(db: Database, item) -> bool:
    """The item was moved to the freezer in the app, so the fridge seeing it leave is expected:
    take it off the shelf and record nothing else."""
    if not item["leaving_shelf"]:
        return False
    db.clear_leaving_shelf(item["id"])
    return True


def _matches_weight(grams: float, item) -> bool:
    return abs(abs(grams) - item["grams"]) <= max(PICKUP_TOLERANCE_G, item["grams"] * PICKUP_TOLERANCE_PCT)


def apply_remove(db: Database, item_id: int) -> None:
    item = db.get_item(item_id)
    if item is None or item["status"] != "active" or _picked_up(db, item):
        return
    db.log_event(
        "remove", product_id=item["product_id"], item_id=item_id,
        grams_delta=-item["grams"], shelf=item["shelf"],
    )
    db.mark_item_removed(item_id)


def _with_remnant(db: Database, item, grams: float) -> float:
    """Counted items: what's taken, plus any remnant under half a unit it would leave behind."""
    product = db.get_product(item["product_id"])
    left = item["grams"] - grams
    if product is not None and product["unit"] == "count" and left < REMNANT_UNITS * product["grams_per_unit"]:
        return item["grams"]
    return grams


def apply_consume(db: Database, item_id: int, grams: float, meta: dict | None = None) -> int | None:
    """Some of an item was used up but it's still there (poured milk, took 2 eggs).
    Returns the event id, so the change can be undone. Calls from the app pass `meta`; a
    meta-less call is the fridge's own weight reading, which a frozen item's departure explains."""
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        return None
    if meta is None and _matches_weight(grams, item) and _picked_up(db, item):
        return None
    grams = _with_remnant(db, item, min(grams, item["grams"]))
    remaining = item["grams"] - grams
    event_id = db.log_event(
        "consume", product_id=item["product_id"], item_id=item_id,
        grams_delta=-grams, shelf=item["shelf"], meta=meta,
    )
    if remaining <= 0:
        db.mark_item_removed(item_id)
    else:
        db.update_item_grams(item_id, remaining)
    return event_id


def apply_move(
    db: Database, item_id: int, shelf: int | None = None, position: tuple[float, float] | None = None
) -> None:
    item = db.get_item(item_id)
    if item is None:
        return
    db.update_item_location(item_id, shelf, position)
    db.log_event("move", product_id=item["product_id"], item_id=item_id, grams_delta=0, shelf=shelf)


def apply_return(db: Database, item_id: int, grams: float) -> None:
    """An item that was removed earlier came back — don't count it as eaten."""
    db.reactivate_item(item_id, grams)
    item = db.get_item(item_id)
    db.log_event("return", product_id=item["product_id"], item_id=item_id, grams_delta=grams, shelf=item["shelf"])


def apply_waste(db: Database, item_id: int, grams: float | None = None) -> int | None:
    """Spoiled / thrown out food — logged separately so it isn't counted as eaten."""
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        return None
    wasted = grams if grams is not None else item["grams"]
    wasted = _with_remnant(db, item, min(wasted, item["grams"]))
    remaining = item["grams"] - wasted
    event_id = db.log_event(
        "waste", product_id=item["product_id"], item_id=item_id,
        grams_delta=-wasted, shelf=item["shelf"],
    )
    if remaining <= 0:
        db.mark_item_removed(item_id)
    else:
        db.update_item_grams(item_id, remaining)
    return event_id


UNDOABLE = {"consume", "waste", "store"}


def move_storage(db: Database, item_id: int, location: str, expiration_date: str | None) -> int | None:
    """Fridge -> freezer (or back) with a new date. The old place and date go in the event so it
    can be undone; a shelf item is marked as leaving, so its drop on the scale is expected."""
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        return None
    before = {"location": item["location"], "expiration_date": item["expiration_date"],
              "expiration_estimated": bool(item["expiration_estimated"])}
    db.set_item_storage(item_id, location, expiration_date, expiration_estimated=True,
                        leaving_shelf=item["shelf"] is not None and location != "fridge")
    return db.log_event("store", product_id=item["product_id"], item_id=item_id, shelf=item["shelf"],
                        meta={"before": before, "location": location})


def undo_events(db: Database, event_ids: list[int]) -> None:
    """Put back what consume/waste events took, as if they never happened:
    the grams return (reactivating emptied items) and the events are deleted,
    so usage rates don't change either. A storage move goes back to its old place and date."""
    for event_id in event_ids:
        event = db.get_event(event_id)
        if event is None or event["event_type"] not in UNDOABLE or event["item_id"] is None:
            continue
        item = db.get_item(event["item_id"])
        if item is not None and event["event_type"] == "store":
            before = json.loads(event["meta"])["before"]
            db.set_item_storage(item["id"], before["location"], before["expiration_date"],
                                before["expiration_estimated"], leaving_shelf=False)
        elif item is not None:
            db.reactivate_item(item["id"], item["grams"] - event["grams_delta"])
        db.delete_event(event_id)


def undo_add(db: Database, item_id: int) -> bool:
    """Take back an item that was just added. Refuses once anything else has
    happened to it, so history is never silently rewritten."""
    events = db.events_for_item(item_id)
    if [e["event_type"] for e in events] != ["add"]:
        return False
    db.delete_item(item_id)
    return True


def apply_needs_review(
    db: Database,
    product_id: int | None = None,
    item_id: int | None = None,
    shelf: int | None = None,
    meta: dict | None = None,
) -> int | None:
    """Ask the person about a change, unless it's the drop of an item they just moved to the freezer."""
    grams = (meta or {}).get("grams") or (meta or {}).get("unmatched_grams")
    if shelf is not None and grams:
        leaving = [i for i in db.active_items(shelf=shelf) if i["leaving_shelf"] and _matches_weight(grams, i)]
        if leaving and _picked_up(db, leaving[0]):
            return None
    return db.log_event(
        "needs_review", product_id=product_id, item_id=item_id,
        grams_delta=0, shelf=shelf, resolved=False, meta=meta,
    )
