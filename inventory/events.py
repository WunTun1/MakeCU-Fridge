"""Turns a decided event (from fusion, chat, or a manual API call) into
database writes. This is the only place that mutates items + events together,
so the two tables never drift apart.
"""
from __future__ import annotations

from .database import Database


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
) -> int:
    item_id = db.create_item(
        product_id, grams, location, shelf, position, expiration_date, confidence, expiration_estimated
    )
    db.log_event("add", product_id=product_id, item_id=item_id, grams_delta=grams, shelf=shelf)
    return item_id


def apply_remove(db: Database, item_id: int) -> None:
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        return
    db.log_event(
        "remove", product_id=item["product_id"], item_id=item_id,
        grams_delta=-item["grams"], shelf=item["shelf"],
    )
    db.mark_item_removed(item_id)


def apply_consume(db: Database, item_id: int, grams: float) -> None:
    """Some of an item was used up but it's still there (poured milk, took 2 eggs)."""
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        return
    grams = min(grams, item["grams"])
    remaining = item["grams"] - grams
    db.log_event(
        "consume", product_id=item["product_id"], item_id=item_id,
        grams_delta=-grams, shelf=item["shelf"],
    )
    if remaining <= 0:
        db.mark_item_removed(item_id)
    else:
        db.update_item_grams(item_id, remaining)


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


def apply_waste(db: Database, item_id: int, grams: float | None = None) -> None:
    """Spoiled / thrown out food — logged separately so it isn't counted as eaten."""
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        return
    wasted = grams if grams is not None else item["grams"]
    wasted = min(wasted, item["grams"])
    remaining = item["grams"] - wasted
    db.log_event(
        "waste", product_id=item["product_id"], item_id=item_id,
        grams_delta=-wasted, shelf=item["shelf"],
    )
    if remaining <= 0:
        db.mark_item_removed(item_id)
    else:
        db.update_item_grams(item_id, remaining)


def apply_needs_review(
    db: Database,
    product_id: int | None = None,
    item_id: int | None = None,
    shelf: int | None = None,
    meta: dict | None = None,
) -> int:
    return db.log_event(
        "needs_review", product_id=product_id, item_id=item_id,
        grams_delta=0, shelf=shelf, resolved=False, meta=meta,
    )
