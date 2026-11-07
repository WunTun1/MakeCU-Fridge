"""FastAPI backend. Section 12.

Serves the Expo mobile app (mobile/), accepts sensor pushes from the
Raspberry Pi (pi_node/agent.py, under /api/pi/*), and accepts events from the
fridge pipeline — or, when hardware isn't attached, from the demo seeder /
manual endpoints (section 15's "if hardware breaks" fallback).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from inventory import events as inv_events
from inventory.database import get_db
from intelligence.alerts import low_stock_alerts
from intelligence.consumption import daily_usage, days_left, grams_on_hand
from intelligence.grocery import grocery_plan, next_trip_date
from intelligence.recipes import suggested_recipes
from intelligence.search import search as fuzzy_search
from nutrition.chatbot import NutritionistChatbot
from nutrition.intake import get_intake
from nutrition.lookup import lookup_barcode_off
from sensors.scale import get_scale_reader

app = FastAPI(title="ReFridge API")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

db = get_db(os.getenv("DATABASE_PATH", "refridge.db"))
chatbot = NutritionistChatbot(db)
scale = get_scale_reader()


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


class ItemIn(BaseModel):
    name: str
    grams: float
    location: str = "pantry"
    category: str | None = None
    usual_package_size_g: float | None = None
    is_staple: bool = False
    expiration_date: str | None = None


class ConsumeIn(BaseModel):
    item_id: int
    grams: float


class ItemIdIn(BaseModel):
    item_id: int


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
    recipe_name: str | None = None
    servings: float = 1
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    source: str = "manual"


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


class ReviewResolutionIn(BaseModel):
    action: str  # "ignore" | "remove" | "consume" | "add_confirmed"
    item_id: int | None = None
    grams: float | None = None
    product_name: str | None = None


# -------------------------------------------------------------------- events
@app.post("/api/events")
def post_event(event: EventIn):
    if event.event_type == "add":
        product_id = db.get_or_create_product(event.product_name or "Unknown Item", category=event.category)
        item_id = inv_events.apply_add(
            db, product_id, event.grams, event.location, event.shelf, event.position, event.expiration_date,
            event.confidence,
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
@app.get("/api/summary")
def get_summary():
    items = db.active_items()
    by_product: dict[int, dict] = {}
    for item in items:
        product = db.get_product(item["product_id"])
        if product is None:
            continue
        entry = by_product.setdefault(product["id"], {
            "product_id": product["id"], "name": product["name"], "category": product["category"],
            "grams": 0.0, "package_size_g": product["usual_package_size_g"],
            "location": item["location"], "shelf": item["shelf"], "_shelf_grams": -1.0,
        })
        entry["grams"] += item["grams"]
        # A product split across shelves is shown on the shelf holding most of it.
        if item["shelf"] is not None and item["grams"] > entry["_shelf_grams"]:
            entry["shelf"], entry["_shelf_grams"] = item["shelf"], item["grams"]

    inventory = []
    for entry in by_product.values():
        entry.pop("_shelf_grams")
        dl = days_left(db, entry["product_id"])
        fill = (entry["grams"] / entry["package_size_g"]) if entry["package_size_g"] else None
        inventory.append({**entry, "days_left": dl, "fill_fraction": fill})

    trip_date = next_trip_date(db)
    today_intake = get_intake(db, "today")

    return {
        "alerts": [a.__dict__ for a in low_stock_alerts(db)],
        "next_trip_date": trip_date.isoformat() if trip_date else None,
        "today_intake": today_intake,
        "inventory": inventory,
        "review_queue_count": len(db.needs_review()),
        "conditions": _condition_dict(db.latest_condition()),
        "door_open": scale.door_is_open(),
    }


@app.get("/api/recipes/suggested")
def get_suggested_recipes(limit: int = 2):
    return [r.__dict__ for r in suggested_recipes(db, min(max(limit, 1), 5))]


@app.get("/api/activity")
def get_activity(limit: int = 10):
    return [dict(r) for r in db.recent_activity(min(limit, 50))]


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
    return {
        "product_id": product_id,
        "name": product["name"],
        "daily_usage_g": daily_usage(db, product_id, days=days),
        "on_hand_g": grams_on_hand(db, product_id),
        "days_left": days_left(db, product_id),
    }


@app.get("/api/grocery")
def get_grocery(trip_in_days: int | None = None):
    plan = grocery_plan(db, trip_in_days)
    return {"trip_date": next_trip_date(db).isoformat() if next_trip_date(db) else None,
            "items": [i.__dict__ for i in plan]}


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
        product_id = db.get_or_create_product(resolution.product_name.strip())
        inv_events.apply_add(db, product_id, grams, location=location, shelf=event["shelf"], position=position)
    else:
        raise HTTPException(400, f"can't apply {resolution.action!r} with the given fields")
    db.resolve_event(review_id)
    return {"ok": True}


# ---------------------------------------------------------- manual / pantry
@app.post("/api/items")
def create_item(item: ItemIn):
    product_id = db.get_or_create_product(
        item.name, category=item.category, usual_package_size_g=item.usual_package_size_g,
        is_staple=item.is_staple,
    )
    item_id = inv_events.apply_add(
        db, product_id, item.grams, location=item.location, expiration_date=item.expiration_date,
    )
    return {"item_id": item_id, "product_id": product_id}


@app.post("/api/items/consume")
def consume_item(body: ConsumeIn):
    inv_events.apply_consume(db, body.item_id, body.grams)
    return {"ok": True}


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
        "dislikes": json.loads(p["dislikes"] or "[]"),
    }


@app.put("/api/profile")
def update_profile(body: ProfileIn):
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    db.update_profile(**fields)
    return {"ok": True}


# ---------------------------------------------------------------------- chat
@app.post("/api/chat")
def post_chat(body: ChatIn):
    reply = chatbot.chat(body.message)
    return {"reply": reply}


@app.post("/api/meals")
def post_meal(body: MealIn):
    meal_id = db.log_meal(
        recipe_name=body.recipe_name, servings=body.servings, calories=body.calories,
        protein_g=body.protein_g, carbs_g=body.carbs_g, fat_g=body.fat_g, source=body.source,
    )
    return {"meal_id": meal_id}


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
