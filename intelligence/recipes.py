"""Suggested recipes for the fridge screen: a small built-in recipe book
matched against what's on hand. Works offline and without an AI key; the
chatbot (nutrition/chatbot.py) is where open-ended recipe ideas come from.

A recipe is suggested only if every ingredient is on hand. Recipes that use
up food expiring soon rank first, then recipes that use more of what's there.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from inventory.database import Database

USE_SOON_DAYS = 3

# Each ingredient lists interchangeable keywords; a keyword matches the start
# of a word in a product name ("egg" matches "Eggs", "cheese" matches "Cheddar Cheese").
RECIPES: list[tuple[str, list[list[str]]]] = [
    ("Spinach Omelette", [["egg"], ["spinach"]]),
    ("Ham & Cheese Omelette", [["egg"], ["ham"], ["cheese", "cheddar"]]),
    ("Cheesy Scrambled Eggs", [["egg"], ["cheese", "cheddar"], ["butter"]]),
    ("Chicken Fried Rice", [["chicken"], ["rice"], ["egg"]]),
    ("Creamy Chicken & Spinach Pasta", [["chicken"], ["pasta", "spaghetti", "penne"], ["spinach"], ["milk", "cream"]]),
    ("Mac and Cheese", [["pasta", "macaroni"], ["cheese", "cheddar"], ["milk"], ["butter"]]),
    ("Chickpea Spinach Curry", [["chickpea"], ["spinach"], ["rice"]]),
    ("Chicken Salad", [["chicken"], ["lettuce", "spinach", "greens"]]),
    ("Yogurt Parfait", [["yogurt"], ["strawberr", "berr", "banana", "fruit"]]),
    ("Fruit Smoothie", [["yogurt"], ["strawberr", "berr", "banana"], ["juice", "milk"]]),
    ("Tofu Stir-fry", [["tofu"], ["rice"], ["carrot", "broccoli", "pepper"]]),
    ("Hummus Veggie Plate", [["hummus"], ["carrot", "cucumber", "pepper"]]),
    ("French Toast", [["egg"], ["milk"], ["bread"]]),
    ("Grilled Cheese", [["bread"], ["cheese", "cheddar"], ["butter"]]),
    ("Chicken Quesadilla", [["chicken"], ["cheese", "cheddar"], ["tortilla"]]),
    ("Pancakes", [["egg"], ["milk"], ["flour"]]),
]


@dataclass
class Suggestion:
    name: str
    uses: list[str]       # product names this recipe uses, use-soon ones first
    uses_soon: list[str]  # the subset expiring soon


def _matches(keyword: str, product_name: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}", product_name, re.IGNORECASE) is not None


def suggest(on_hand: list[str], use_soon: set[str], limit: int = 2) -> list[Suggestion]:
    """Pure matching: `on_hand` are product names with stock, `use_soon` the ones to use up first."""
    scored: list[tuple[int, int, int, Suggestion]] = []
    for order, (name, ingredients) in enumerate(RECIPES):
        uses: list[str] = []
        for alternatives in ingredients:
            # Prefer a use-soon product when several would do (spinach over lettuce if spinach is expiring).
            hits = [p for p in on_hand if p not in uses and any(_matches(k, p) for k in alternatives)]
            if not hits:
                break
            hits.sort(key=lambda p: p not in use_soon)
            uses.append(hits[0])
        else:
            soon = [p for p in uses if p in use_soon]
            uses.sort(key=lambda p: p not in use_soon)
            scored.append((-len(soon), -len(uses), order, Suggestion(name, uses, soon)))
    scored.sort(key=lambda t: t[:3])
    return [s for *_, s in scored[:limit]]


def suggested_recipes(db: Database, limit: int = 2) -> list[Suggestion]:
    cutoff = (datetime.now(timezone.utc) + timedelta(days=USE_SOON_DAYS)).date()
    on_hand: dict[str, None] = {}
    use_soon: set[str] = set()
    for item in db.active_items():
        if item["grams"] <= 0:
            continue
        product = db.get_product(item["product_id"])
        if product is None:
            continue
        on_hand[product["name"]] = None
        if item["expiration_date"] and datetime.fromisoformat(item["expiration_date"]).date() <= cutoff:
            use_soon.add(product["name"])
    return suggest(list(on_hand), use_soon, limit)
