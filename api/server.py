"""FastAPI backend. Section 12.

Serves the Expo mobile app (mobile/), accepts sensor pushes from the
Raspberry Pi (pi_node/agent.py, under /api/pi/*), and accepts events from the
fridge pipeline — or, when hardware isn't attached, from the demo seeder /
manual endpoints (section 15's "if hardware breaks" fallback).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from inventory import events as inv_events
from inventory.database import get_db
from inventory.units import default_grams_per_unit, to_grams
from intelligence import clock, grocery_list, taste
from intelligence.alerts import low_stock_alerts
from intelligence.consumption import daily_usage, days_left, grams_on_hand, usage_rate_g_per_day
from intelligence.expiry import days_until, freezer_days, resolve_expiration
from intelligence.fridge_view import ITEM_IMAGE_DIR, fridge_entry, inventory_entries
from intelligence.grocery import unlock_suggestions
from intelligence.search import search as fuzzy_search
from nutrition import intake
from nutrition.chatbot import NutritionistChatbot
from nutrition.intake import get_intake, log_nutrition, meals, protein_mode
from nutrition.lookup import lookup_barcode_off
from recipes.engine import allergens_in, card
from sensors.scale import get_scale_reader
from vision.debug import view as vision_view

log = logging.getLogger("refridge.api")
MAX_CHAT_CHARS = 1000
UNLOCK_CACHE_SECONDS = 60
TONIGHT_CACHE_SECONDS = 600
TONIGHT_LIMIT = 6
# "Add food" on Today: fridge items worth logging for protein, as one usual portion each.
QUICK_ADD_MIN_PROTEIN_G, QUICK_ADD_LIMIT = 10.0, 4
QUICK_ADD_PORTION_G, QUICK_ADD_PORTION_COUNT = 200.0, 2
RAW_CATEGORIES = {"meat", "seafood", "poultry"}

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _rebuild_tonight_soon()  # Home's first visit finds Cook tonight ready
    yield


app = FastAPI(title="ReFridge API", lifespan=_lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.middleware("http")
async def _rebuild_after_writes(request: Request, call_next):
    """Any change through the API may change what you can cook: rebuild Cook tonight off the request path."""
    response = await call_next(request)
    if request.method != "GET" and request.url.path.startswith("/api/"):
        _rebuild_tonight_soon()
    return response

db = get_db(os.getenv("DATABASE_PATH", "refridge.db"))
chatbot = NutritionistChatbot(db)
scale = get_scale_reader()


def _expiry_for(location: str, *, printed_date=None, estimated_days=None, name=None, category=None):
    """(expiration_date, is_estimate). Shelf-life estimates are fridge numbers,
    so pantry/freezer items only get a date if one was actually provided."""
    if location != "fridge":
        return printed_date, False
    return resolve_expiration(printed_date=printed_date, estimated_days=estimated_days, name=name, category=category)


def _condition_dict(row) -> dict | None:
    if row is None:
        return None
    return {k: row[k] for k in ("occurred_at", "temperature_c", "pressure_hpa", "humidity_pct", "light_raw")}


# ------------------------------------------------------------------- schemas
class EventIn(BaseModel):
    event_type: str  # add|remove|consume|move|return|waste|needs_review
    product_name: str | None = None
    item_id: int | None = None
    grams: float = 0.0
    location: str = "fridge"
    shelf: int | None = None
    position: tuple[float, float] | None = None
    expiration_date: str | None = None
    confidence: float | None = None
    category: str | None = None


Unit = Literal["g", "count", "ml", "lb", "oz"]
# Weights people buy meat and cheese in; stored as grams like everything else.
GRAMS_PER = {"lb": 453.6, "oz": 28.35}


class ItemIn(BaseModel):
    """An amount as grams, or as quantity + unit (12, "count")."""
    name: str
    grams: float | None = Field(None, ge=0)  # 0 = seen by the camera but not weighed (vision/snap.py)
    quantity: float | None = Field(None, gt=0)
    unit: Unit | None = None
    location: str = "pantry"
    shelf: int | None = None          # which shelf, for fridge items; None = elsewhere in the fridge
    category: str | None = None
    usual_package_size_g: float | None = None
    is_staple: bool = False
    expiration_date: str | None = None


class ItemPatchIn(BaseModel):
    grams: float | None = Field(None, ge=0)
    expiration_date: date | None = None


class ConsumeIn(BaseModel):
    item_id: int
    grams: float


class ItemIdIn(BaseModel):
    item_id: int


class ItemIdsIn(BaseModel):
    item_ids: list[int]


class EventIdsIn(BaseModel):
    event_ids: list[int]


class GroceryAddIn(BaseModel):
    names: list[str] = Field(min_length=1)
    source: Literal["manual", "recipe"] = "manual"
    recipe_id: int | None = None
    recipe_name: str | None = None


class GroceryPatchIn(BaseModel):
    checked: bool | None = None
    hidden: bool | None = None


class HorizonIn(BaseModel):
    trip_in_days: Literal[1, 3, 7] | None = None


class BarcodeIn(BaseModel):
    barcode: str
    location: str = "pantry"


class ProfileIn(BaseModel):
    daily_calories: float | None = None
    daily_protein_g: float | None = None
    daily_carbs_g: float | None = None
    daily_fat_g: float | None = None
    diet_type: str | None = None
    allergies: list[str] | None = None
    dislikes: list[str] | None = None


class ChatIn(BaseModel):
    message: str


class MealIn(BaseModel):
    """Nutrition only ({name, protein_g, calories} off a label); nothing leaves the fridge."""
    name: str | None = None
    recipe_name: str | None = None
    servings: float = 1
    calories: float | None = Field(None, ge=0)
    protein_g: float | None = Field(None, ge=0)
    carbs_g: float | None = None
    fat_g: float | None = None
    source: str = "manual"
    occurred_at: datetime | None = None


class EatIn(BaseModel):
    """Grams to eat; one unit (a serving of leftovers, an egg) when left out."""
    grams: float | None = Field(None, ge=0)  # 0 = seen by the camera but not weighed (vision/snap.py)


class PiWeightIn(BaseModel):
    shelf: int
    grams: float


class PiWeightBatchIn(BaseModel):
    readings: list[PiWeightIn]


class PiDoorIn(BaseModel):
    open: bool


class PiConditionsIn(BaseModel):
    temperature_c: float | None = None
    pressure_hpa: float | None = None
    humidity_pct: float | None = None
    light_raw: float | None = None


Made = Literal[0.5, 1.0]


class CookedIn(BaseModel):
    made: Made = 1.0
    servings_eaten: float = Field(1.0, gt=0, le=20)


class RateIn(BaseModel):
    liked: bool


class ReviewResolutionIn(BaseModel):
    action: str  # "ignore" | "remove" | "consume" | "add_confirmed"
    item_id: int | None = None
    grams: float | None = None
    product_name: str | None = None


# -------------------------------------------------------------------- events
@app.post("/api/events")
def post_event(event: EventIn):
    if event.event_type == "add":
        name = event.product_name or "Unknown Item"
        expires, estimated = _expiry_for(event.location, printed_date=event.expiration_date, name=name, category=event.category)
        product_id = db.get_or_create_product(name, category=event.category)
        item_id = inv_events.apply_add(
            db, product_id, event.grams, event.location, event.shelf, event.position, expires,
            event.confidence, expiration_estimated=estimated,
        )
        return {"item_id": item_id}

    if event.item_id is None:
        raise HTTPException(400, "item_id is required for this event_type")

    if event.event_type == "remove":
        inv_events.apply_remove(db, event.item_id)
    elif event.event_type == "consume":
        inv_events.apply_consume(db, event.item_id, event.grams)
    elif event.event_type == "move":
        inv_events.apply_move(db, event.item_id, event.shelf, event.position)
    elif event.event_type == "return":
        inv_events.apply_return(db, event.item_id, event.grams)
    elif event.event_type == "waste":
        inv_events.apply_waste(db, event.item_id, event.grams)
    elif event.event_type == "needs_review":
        item = db.get_item(event.item_id)
        inv_events.apply_needs_review(db, item["product_id"] if item else None, event.item_id, event.shelf)
    else:
        raise HTTPException(400, f"unknown event_type {event.event_type!r}")
    return {"ok": True}


# ------------------------------------------------------------------- summary
def _with_allergens(inventory: list[dict]) -> list[dict]:
    """Leftovers cooked from a recipe with a profile allergen say so: contains ["soy"]."""
    allergies = json.loads(db.get_profile()["allergies"] or "[]")
    for e in inventory:
        recipe_id = e["leftovers"] and allergies and db.get_product(e["product_id"])["recipe_id"]
        recipe = chatbot.engine.store.get(recipe_id) if recipe_id else None
        e["contains"] = [a["allergy"] for a in allergens_in(recipe, allergies)] if recipe else []
    return inventory


@app.get("/api/summary")
def get_summary():
    inventory = _with_allergens(inventory_entries(db))
    trip_date = grocery_list.trip_date_for(db, grocery_list.get_horizon(db))
    today_intake = get_intake(db, "today")

    return {
        "alerts": [a.__dict__ for a in low_stock_alerts(db)],
        "next_trip_date": trip_date.isoformat() if trip_date else None,
        "next_trip_in_days": grocery_list.days_away(trip_date),
        "covers_until": grocery_list.covers_until(trip_date),
        "today_intake": today_intake,
        "inventory": inventory,
        "review_queue_count": len(db.needs_review()),
        "conditions": _condition_dict(db.latest_condition()),
        "door_open": scale.door_is_open(),
    }


@app.get("/api/products/common")
def get_common_products(limit: int = 8):
    return [{"id": r["id"], "name": r["name"]} for r in db.common_products(min(limit, 30))]


@app.get("/api/search")
def get_search(q: str):
    return [r.__dict__ for r in fuzzy_search(db, q)]


@app.get("/api/products/{product_id}/usage")
def get_product_usage(product_id: int, days: int = 28):
    product = db.get_product(product_id)
    if product is None:
        raise HTTPException(404, "product not found")
    # One row per package, the one that goes bad first on top (and used first).
    items = sorted((i for i in db.active_items() if i["product_id"] == product_id),
                   key=lambda i: (i["expiration_date"] is None, i["expiration_date"] or "", i["id"]))
    entry = fridge_entry(db, product_id)
    soonest = entry and entry["soonest_batch"]
    return {
        "product_id": product_id,
        "name": product["name"],
        "category": product["category"],
        "recipe_id": product["recipe_id"],
        "protein_g_per_100g": product["protein_g_per_100g"],
        "unit": product["unit"],
        "grams_per_unit": product["grams_per_unit"],
        "daily_usage_g": daily_usage(db, product_id, days=days),
        "on_hand_g": grams_on_hand(db, product_id),
        "days_left": days_left(db, product_id),
        "rate_g_per_day": usage_rate_g_per_day(db, product_id),
        "expiration_date": soonest["expiration_date"] if soonest else None,
        "expiry_estimated": entry["expiry_estimated"] if soonest else False,
        "expires_in_days": soonest["expires_in_days"] if soonest else None,
        "likely_wasted_g": entry["likely_wasted_g"] if entry else None,
        "items": [
            {"id": i["id"], "grams": i["grams"], "location": i["location"],
             "expiration_date": i["expiration_date"], "expiry_estimated": bool(i["expiration_estimated"]),
             "expires_in_days": days_until(i["expiration_date"]) if i["expiration_date"] else None}
            for i in items
        ],
    }


# ------------------------------------------------------------------- grocery
@app.get("/api/grocery")
def get_grocery():
    return grocery_list.build_list(db)


@app.put("/api/grocery/horizon")
def put_grocery_horizon(body: HorizonIn):
    grocery_list.set_horizon(db, body.trip_in_days)
    return grocery_list.build_list(db)


@app.post("/api/grocery/items")
def add_grocery_items(body: GroceryAddIn):
    """`new` per name: false when it went into a row already on the list (so Undo leaves that row)."""
    before = {e["id"] for e in db.grocery_entries()}
    ids = grocery_list.add_entries(db, body.names, body.source, body.recipe_id, body.recipe_name)
    return {"ids": ids, "new": [i not in before for i in ids]}


@app.patch("/api/grocery/items/{entry_id}")
def patch_grocery_item(entry_id: int, body: GroceryPatchIn):
    """Check off, or remove (hidden) / bring back. A removed plan row stays off for that trip."""
    if db.get_grocery_entry(entry_id) is None:
        raise HTTPException(404, "not on the list")
    if body.checked is not None:
        db.set_grocery_checked(entry_id, body.checked)
    if body.hidden is not None:
        db.set_grocery_hidden(entry_id, body.hidden)
    return {"ok": True}


@app.post("/api/grocery/clear-checked")
def clear_checked_grocery():
    db.clear_checked_grocery()
    return {"ok": True}


def _fridge_version() -> tuple:
    """Changes whenever the inventory or the profile filters change."""
    profile = db.get_profile()
    return (
        tuple((i["id"], round(i["grams"]), i["location"]) for i in db.active_items()),
        profile["allergies"], profile["dislikes"], protein_mode(profile),
    )


def _cached(cache: dict, ttl: float, compute):
    key = _fridge_version()
    if cache.get("key") != key or time.monotonic() - cache.get("at", 0.0) > ttl:
        cache.update(key=key, at=time.monotonic(), value=compute())
    return cache["value"]


_unlock_cache: dict = {}


@app.get("/api/grocery/unlock")
def get_grocery_unlock():
    """Slow (searches the recipe library), so it's cached until the fridge or
    profile changes, or for a minute."""
    return _cached(_unlock_cache, UNLOCK_CACHE_SECONDS,
                   lambda: [u.__dict__ for u in unlock_suggestions(
                       db, chatbot.engine, high_protein=protein_mode(db.get_profile()))])


# -------------------------------------------------------------------- review
@app.get("/api/review")
def get_review_queue():
    rows = db.needs_review()
    return [
        {
            "id": r["id"], "item_id": r["item_id"], "product_id": r["product_id"],
            "shelf": r["shelf"], "occurred_at": r["occurred_at"],
            "meta": json.loads(r["meta"]) if r["meta"] else None,
        }
        for r in rows
    ]


@app.post("/api/review/{review_id}")
def resolve_review(review_id: int, resolution: ReviewResolutionIn):
    event = db.get_event(review_id)
    if event is None or event["event_type"] != "needs_review":
        raise HTTPException(404, "review item not found")
    meta = json.loads(event["meta"]) if event["meta"] else {}

    if resolution.action == "ignore":
        pass
    elif resolution.action == "remove" and resolution.item_id:
        inv_events.apply_remove(db, resolution.item_id)
    elif resolution.action == "consume" and resolution.item_id and resolution.grams:
        inv_events.apply_consume(db, resolution.item_id, resolution.grams)
    elif resolution.action == "add_confirmed" and resolution.product_name:
        grams = resolution.grams or meta.get("grams")
        if not grams:
            raise HTTPException(400, "grams required")
        position = tuple(meta["position"]) if meta.get("position") else None
        location = "fridge" if event["shelf"] is not None else "pantry"
        name = resolution.product_name.strip()
        # The model's freshness estimate only applies if the user agreed with its guess.
        candidate = meta.get("candidate") or {}
        same_item = (candidate.get("item_name") or "").strip().lower() == name.lower()
        expires, estimated = _expiry_for(
            location,
            printed_date=candidate.get("visible_expiration_date") if same_item else None,
            estimated_days=candidate.get("days_until_expired") if same_item else None,
            name=name, category=candidate.get("category") if same_item else None,
        )
        product_id = db.get_or_create_product(name)
        inv_events.apply_add(
            db, product_id, grams, location=location, shelf=event["shelf"], position=position,
            expiration_date=expires, expiration_estimated=estimated,
        )
    else:
        raise HTTPException(400, f"can't apply {resolution.action!r} with the given fields")
    db.resolve_event(review_id)
    return {"ok": True}


# -------------------------------------------------------------- item photos
# A photo of an item, for when nobody could name it: the camera bench (vision/snap.py)
# uploads its crop, and the fridge screen shows it on that item's tile.
MAX_ITEM_IMAGE_BYTES = 5_000_000


@app.post("/api/items/{item_id}/image")
async def put_item_image(item_id: int, request: Request):
    if db.get_item(item_id) is None:
        raise HTTPException(404, "item not found")
    body = await request.body()
    if not body.startswith(b"\xff\xd8") or len(body) > MAX_ITEM_IMAGE_BYTES:
        raise HTTPException(400, "send a JPEG (raw request body, under 5 MB)")
    ITEM_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    (ITEM_IMAGE_DIR / f"{item_id}.jpg").write_bytes(body)
    return {"ok": True, "image_url": f"/api/items/{item_id}/image"}


@app.get("/api/items/{item_id}/image")
def get_item_image(item_id: int):
    path = ITEM_IMAGE_DIR / f"{item_id}.jpg"
    if not path.exists():
        raise HTTPException(404, "no photo for this item")
    return FileResponse(path, media_type="image/jpeg")


# ---------------------------------------------------------- manual / pantry
@app.post("/api/items")
def create_item(item: ItemIn):
    if item.grams is None and item.quantity is None:
        raise HTTPException(422, "give grams, or quantity and unit")
    weight = GRAMS_PER.get(item.unit or "")
    product_id = db.get_or_create_product(
        item.name, category=item.category, usual_package_size_g=item.usual_package_size_g,
        is_staple=item.is_staple, unit="g" if weight else item.unit,
    )
    product = db.get_product(product_id)
    if item.quantity is not None and weight:
        grams = item.quantity * weight
    elif item.quantity is not None:
        unit = item.unit or product["unit"]
        per = product["grams_per_unit"] if unit == product["unit"] else default_grams_per_unit(item.name, unit)
        grams = to_grams(item.quantity, unit, per)
    else:
        grams = item.grams
    expires, estimated = _expiry_for(item.location, printed_date=item.expiration_date, name=item.name, category=item.category)
    item_id = inv_events.apply_add(
        db, product_id, grams, location=item.location, shelf=item.shelf,
        expiration_date=expires, expiration_estimated=estimated,
    )
    return {"item_id": item_id, "product_id": product_id, "grams": grams,
            "unit": product["unit"], "grams_per_unit": product["grams_per_unit"],
            "checked_off": grocery_list.check_off(db, product["name"])}


@app.post("/api/items/{item_id}/undo-add")
def undo_add_item(item_id: int):
    if not inv_events.undo_add(db, item_id):
        raise HTTPException(409, "this item has changed since it was added")
    return {"ok": True}


@app.patch("/api/items/{item_id}")
def patch_item(item_id: int, body: ItemPatchIn):
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        raise HTTPException(404, "item not found")
    expires = body.expiration_date.isoformat() if body.expiration_date else None
    db.update_item(item_id, grams=body.grams, expiration_date=expires)
    return {"ok": True}


@app.post("/api/items/consume")
def consume_item(body: ConsumeIn):
    return {"ok": True, "event_id": inv_events.apply_consume(db, body.item_id, body.grams)}


@app.post("/api/items/waste")
def waste_items(body: ItemIdsIn):
    """Thrown out: logged as waste, so it never counts toward how fast you use it."""
    ids = [inv_events.apply_waste(db, item_id) for item_id in body.item_ids]
    return {"event_ids": [i for i in ids if i is not None]}


@app.post("/api/events/undo")
def undo_events(body: EventIdsIn):
    inv_events.undo_events(db, body.event_ids)
    return {"ok": True}


@app.post("/api/products/{product_id}/eat")
def eat_product(product_id: int, body: EatIn):
    """Ate some as it is: a serving of leftovers, a yogurt. Logs its nutrition and takes it from the
    fridge, nothing else. Undo with /api/meals/{meal_id}/undo."""
    if db.get_product(product_id) is None:
        raise HTTPException(404, "product not found")
    eaten = intake.eat_product(db, product_id, body.grams)
    if eaten is None:
        raise HTTPException(409, "none left")
    return eaten


@app.post("/api/products/{product_id}/freeze")
def freeze_product(product_id: int):
    """Every fridge package of it goes to the freezer, with a freezer date. Undo with /api/events/undo."""
    product = db.get_product(product_id)
    items = [i for i in db.active_items(location="fridge") if i["product_id"] == product_id]
    if product is None or not items:
        raise HTTPException(404, "nothing of this in the fridge")
    days = freezer_days(product["name"], product["category"])
    expires = clock.date_in(days).isoformat()
    event_ids = [inv_events.move_storage(db, i["id"], "freezer", expires) for i in items]
    return {"event_ids": [e for e in event_ids if e is not None], "grams": sum(i["grams"] for i in items),
            "expiration_date": expires}


@app.post("/api/items/remove")
def remove_item(body: ItemIdIn):
    inv_events.apply_remove(db, body.item_id)
    return {"ok": True}


@app.post("/api/barcode")
def lookup_barcode(body: BarcodeIn):
    existing = db.find_product_by_barcode(body.barcode)
    if existing:
        product_id = existing["id"]
        grams = existing["usual_package_size_g"] or 0
    else:
        info = lookup_barcode_off(body.barcode)
        if info is None:
            raise HTTPException(404, "barcode not found")
        product_id = db.create_product(
            info["name"], category=info["category"], usual_package_size_g=info["package_size_g"],
            barcode=body.barcode, nutrition_per_100g=info["nutrition"], nutrition_source="open_food_facts",
        )
        grams = info["package_size_g"] or 0

    item_id = inv_events.apply_add(db, product_id, grams, location=body.location)
    return {"item_id": item_id, "product_id": product_id}


# ------------------------------------------------------------------- profile
@app.get("/api/profile")
def get_profile():
    p = db.get_profile()
    return {
        "daily_calories": p["daily_calories"], "daily_protein_g": p["daily_protein_g"],
        "daily_carbs_g": p["daily_carbs_g"], "daily_fat_g": p["daily_fat_g"],
        "diet_type": p["diet_type"], "allergies": json.loads(p["allergies"] or "[]"),
        "dislikes": json.loads(p["dislikes"] or "[]"), "protein_mode": protein_mode(p),
    }


@app.put("/api/profile")
def update_profile(body: ProfileIn):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    db.update_profile(**fields)
    return {"ok": True}


# ---------------------------------------------------------------------- chat
@app.post("/api/chat")
def post_chat(body: ChatIn):
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "empty message")
    return chatbot.chat(message[:MAX_CHAT_CHARS])


@app.post("/api/chat/turns/{turn_id}/undo")
def undo_chat_turn(turn_id: int):
    """Everything one chat reply changed goes back: grams, leftovers and the meals it logged."""
    undone = chatbot.undo_turn(turn_id)
    if undone is None:
        raise HTTPException(404, "no such chat turn")
    if not undone:
        raise HTTPException(409, "already undone")
    return {"ok": True}


@app.delete("/api/chat/history")
def clear_chat_history():
    db.clear_chat()
    return {"ok": True}


# ------------------------------------------------------------------- recipes
@app.get("/api/recipes/suggest")
def suggest_recipes(q: str | None = None, cuisine: str | None = None, max_minutes: int | None = None,
                    high_protein: bool = False, must_have_all: bool = False, limit: int = 6):
    matches = chatbot.engine.suggest(q, cuisine, max_minutes, high_protein, must_have_all, min(limit, 20))
    return [card(m) for m in matches]


_tonight: dict = {"key": None, "at": 0.0, "value": None, "building": False}
_tonight_lock = threading.Lock()


def _tonight_fresh() -> bool:
    return _tonight["key"] == _fridge_version() and time.monotonic() - _tonight["at"] <= TONIGHT_CACHE_SECONDS


def _build_tonight() -> None:
    """Builds until the list matches the fridge (it may change while a build runs)."""
    while not _tonight_fresh():
        key = _fridge_version()
        value = [card(m) for m in chatbot.engine.suggest(
            limit=TONIGHT_LIMIT, automatic=True, high_protein=protein_mode(db.get_profile()))]
        _tonight.update(key=key, at=time.monotonic(), value=value)


def _build_in_background() -> None:
    try:
        _build_tonight()
    except Exception:
        log.exception("Cook tonight rebuild failed")
    finally:
        _tonight["building"] = False


def _rebuild_tonight_soon() -> None:
    with _tonight_lock:
        if _tonight["building"]:
            return
        _tonight["building"] = True
    threading.Thread(target=_build_in_background, daemon=True).start()


@app.get("/api/recipes/tonight")
def recipes_tonight():
    """Cook tonight: dinner-sized main dishes from what you have. Built in the background after every
    change, so this answers at once with the latest list (rebuilding when it's out of date)."""
    if _tonight["value"] is None:
        _build_tonight()
    elif not _tonight_fresh():
        _rebuild_tonight_soon()
    return _tonight["value"]


@app.get("/api/recipes/{recipe_id}")
def get_recipe(recipe_id: int):
    recipe = chatbot.engine.adapted(recipe_id)
    if recipe is None:
        raise HTTPException(404, "recipe not found")
    listed = grocery_list.listed_norms(db)
    to_buy = recipe["missing"] + [s["name"] for s in recipe["short"]]
    recipe["on_grocery_list"] = [n for n in to_buy if grocery_list.normalize(n) in listed]
    recipe["leftovers"] = chatbot.engine.leftovers_for(recipe_id)
    cooked_today = [m for m in meals(db, "today") if m["source"] == "recipe" and m["name"] == recipe["name"]]
    recipe["logged_meal_id"] = cooked_today[-1]["id"] if cooked_today else None
    return recipe


@app.get("/api/recipes/{recipe_id}/cooked/preview")
def recipe_cooked_preview(recipe_id: int, made: float = 1.0):
    """Dry run of "I made this": what would be taken, before anything changes."""
    if made not in (0.5, 1.0):
        raise HTTPException(422, "made is 0.5 (half the recipe) or 1 (all of it)")
    lines = chatbot.engine.preview_cooked(recipe_id, made)
    if lines is None:
        raise HTTPException(404, "recipe not found")
    return lines


@app.post("/api/recipes/{recipe_id}/cooked")
def recipe_cooked(recipe_id: int, body: CookedIn):
    result = chatbot.engine.cooked(recipe_id, body.made, body.servings_eaten)
    if result is None:
        raise HTTPException(404, "recipe not found")
    return result


@app.post("/api/recipes/{recipe_id}/rate")
def recipe_rate(recipe_id: int, body: RateIn):
    if not chatbot.engine.rate(recipe_id, body.liked):
        raise HTTPException(404, "recipe not found")
    return {"ok": True}


@app.get("/api/taste")
def get_taste():
    """What ReFridge has learned about your cooking, for the profile screen."""
    prof = taste.profile(db)
    return {
        "cuisines": taste.top_preferences(prof, "cuisine", 4),
        "ingredients": taste.top_preferences(prof, "ingredient", 6),
    }


@app.get("/api/meals")
def get_meals(period: Literal["today", "week"] = "today"):
    """Each meal cooked with "I made this" says what undoing the cooking would do
    ("puts back 400 g chicken breast and removes 3 leftover servings")."""
    return [{**m, "cook_undo": inv_events.undo_summary(db, db.events_for_meal(m["id"])) if m["source"] == "recipe" else None}
            for m in meals(db, period)]


@app.post("/api/meals")
def post_meal(body: MealIn):
    name = (body.name or body.recipe_name or "").strip()
    if not name:
        raise HTTPException(422, "name is required")
    if body.occurred_at:  # putting back a meal removed from today, at its own time
        meal_id = db.log_meal(name, body.servings, body.calories, body.protein_g, body.carbs_g, body.fat_g,
                              source=body.source, occurred_at=body.occurred_at.isoformat())
    else:
        meal_id = log_nutrition(db, name, body.protein_g, body.calories, source=body.source,
                                carbs_g=body.carbs_g, fat_g=body.fat_g)
    return {"meal_id": meal_id}


@app.delete("/api/meals/{meal_id}")
def delete_meal(meal_id: int):
    """Off the nutrition log only; what left the fridge stays gone. Returns the meal so it can be put back."""
    meal = db.get_meal(meal_id)
    if meal is None:
        raise HTTPException(404, "meal not found")
    db.delete_meal(meal_id)
    return {"name": meal["recipe_name"], "servings": meal["servings"], "occurred_at": meal["occurred_at"],
            "source": meal["source"], **{k: meal[k] for k in ("calories", "protein_g", "carbs_g", "fat_g")}}


@app.get("/api/meals/quick-adds")
def get_quick_adds():
    """Fridge items with at least 10 g protein in a usual portion (2 eggs, 200 g of yogurt, one
    serving of leftovers), most protein first. Raw meat is left out: nobody eats it as it is."""
    out = []
    for entry in get_summary()["inventory"]:
        product = db.get_product(entry["product_id"])
        per_100g = product["protein_g_per_100g"]
        if entry["location"] != "fridge" or per_100g is None or (product["category"] or "").lower() in RAW_CATEGORIES:
            continue
        if product["unit"] == "count":
            grams = (1 if entry["leftovers"] else QUICK_ADD_PORTION_COUNT) * product["grams_per_unit"]
        else:
            grams = QUICK_ADD_PORTION_G
        protein = per_100g * grams / 100
        if protein >= QUICK_ADD_MIN_PROTEIN_G and entry["grams"] >= grams - 0.5:
            kcal = product["calories_per_100g"]
            out.append({"product_id": product["id"], "name": product["name"], "unit": product["unit"],
                        "grams_per_unit": product["grams_per_unit"], "grams": grams, "protein_g": round(protein),
                        "calories": round(kcal * grams / 100) if kcal is not None else None})
    return sorted(out, key=lambda q: -q["protein_g"])[:QUICK_ADD_LIMIT]


@app.post("/api/meals/{meal_id}/undo")
def undo_meal(meal_id: int):
    if not chatbot.engine.undo_meal(meal_id):
        raise HTTPException(404, "meal not found")
    return {"ok": True}


# ------------------------------------------------------- Raspberry Pi pushes
# The Pi owns the load cells, Grove microswitch, barometer, and light sensor,
# and pushes readings here; all heavy compute stays on this backend.
@app.post("/api/pi/weight")
def pi_weight(body: PiWeightBatchIn):
    for r in body.readings:
        scale.ingest_weight(r.shelf, r.grams)
    return {"ok": True}


@app.post("/api/pi/door")
def pi_door(body: PiDoorIn):
    scale.ingest_door(body.open)
    return {"ok": True}


@app.post("/api/pi/conditions")
def pi_conditions(body: PiConditionsIn):
    db.log_condition(body.temperature_c, body.pressure_hpa, body.humidity_pct, body.light_raw)
    return {"ok": True}


@app.get("/api/conditions")
def get_conditions():
    return {"latest": _condition_dict(db.latest_condition()), "door_open": scale.door_is_open()}


@app.get("/api/health")
def health():
    return {"ok": True, "scale_source": scale.source}


@app.get("/api/vision/frame.jpg")
def vision_frame():
    """Latest camera frame annotated with what the vision pipeline sees (vision/debug.py)."""
    jpeg = vision_view.jpeg()
    if jpeg is None:
        raise HTTPException(404, "no vision frames yet — is the fridge loop running?")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------------------------------- web build (fridge screen)
# `npx expo export --platform web` in mobile/ writes mobile/dist. Serving it
# here gives the fridge's touchscreen one URL: http://<backend>:8000/kiosk.
# Must stay the last route so it never shadows an API path.
WEB_DIST = (Path(__file__).resolve().parent.parent / "mobile" / "dist").resolve()


@app.get("/{path:path}", include_in_schema=False)
def web_app(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "unknown API route")
    if not WEB_DIST.is_dir():
        raise HTTPException(404, "web build not found — run `npx expo export --platform web` in mobile/")
    file = (WEB_DIST / path).resolve()
    if path and file.is_file() and WEB_DIST in file.parents:
        return FileResponse(file)
    return FileResponse(WEB_DIST / "index.html")  # client-side routes like /kiosk
