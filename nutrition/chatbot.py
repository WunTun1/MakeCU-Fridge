"""Nutritionist chatbot: the AI talks and suggests; code finds real recipes,
does the math, and checks facts. Section 11.

Recipes come from the local recipe library (recipes/) through `find_recipes`
— the model is told never to invent one. Ranking, swaps, nutrition, stock,
and allergy checks are plain Python; allergies are a hard filter the model
can't argue past.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from gemini import make_client, model_name, types
from inventory import events as inv_events
from inventory.database import Database
from intelligence import taste
from intelligence.alerts import low_stock_alerts
from intelligence.consumption import grams_on_hand
from intelligence.expiry import describe_expiry
from nutrition.intake import get_intake, log_meal_eaten
from nutrition.lookup import lookup_nutrition_usda
from recipes.engine import RecipeEngine, card
from recipes.ingredients import allergen_hits
from recipes.store import CUISINES, get_store

log = logging.getLogger("refridge.nutrition.chatbot")

MAX_TOOL_ROUNDS = 6
MAX_CARDS = 4
# Words that say how you're asking, not what you want to eat (offline keyword mode).
OFFLINE_STOPWORDS = {
    "i", "im", "want", "wanna", "feel", "feeling", "like", "some", "something", "food", "make", "cook",
    "can", "could", "what", "with", "need", "more", "a", "an", "the", "for", "me", "to", "and", "or",
    "today", "tonight", "dinner", "lunch", "breakfast", "please", "high", "protein", "quick", "fast",
    "easy", "recipe", "recipes", "idea", "ideas", "of", "in", "my", "fridge", "have", "do", "is", "it",
}

SYSTEM_PROMPT = """You are ReFridge, the friendly assistant on a smart fridge's touchscreen and phone app. \
Keep replies short (2-4 sentences) — people read them standing at the fridge. Write plain text only: \
no markdown, no asterisks or bold, no headings; for recipe steps use short lines starting with "1.", "2.".

Recipes: ONLY suggest recipes returned by find_recipes; never invent a recipe, ingredient list, or \
nutrition numbers. Turn the user's request into find_recipes arguments (e.g. "I want Italian" -> \
cuisine="italian"; "something with chicken, quick" -> query="chicken", max_minutes=30; "more protein" \
-> high_protein=true). Recipe cards are shown to the user automatically, so don't list every \
ingredient — say which one or two you'd pick and why (uses something expiring, matches their goals, \
swaps they can make, what they'd need to buy). Call get_recipe before walking through steps. If \
results have missing ingredients, say what to buy or which swap works. If the user narrows things \
down ("no, something lighter"), call find_recipes again with new arguments.

Facts: never compute nutrition or stock yourself — call a tool. Allergens are filtered out in code; \
if check_recipe reports a conflict, that is final. General wellness info only, not medical advice — \
suggest a doctor or dietitian for medical conditions. Never shame anyone about food."""

TOOLS = [
    {
        "name": "find_recipes",
        "description": "Search the real recipe library and rank results by what's in the fridge, what's "
                        "expiring, the user's goals and tastes. Allergens are already excluded. Returns "
                        "up to 5 recipes with have/missing ingredients and possible swaps.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Dish or ingredient words, e.g. 'pasta spinach', 'chicken curry'. Empty to search by what's in the fridge."},
                "cuisine": {"type": "string", "description": "e.g. italian, mexican, thai, indian, chinese, japanese, greek, french, korean, middle-eastern"},
                "max_minutes": {"type": "integer"},
                "high_protein": {"type": "boolean"},
                "must_have_all": {"type": "boolean", "description": "Only recipes makeable now without shopping (swaps allowed)."},
            },
        },
    },
    {
        "name": "get_recipe",
        "description": "Full recipe by id: ingredients marked have/swap/missing, steps with swaps applied, nutrition per serving.",
        "parameters": {
            "type": "object",
            "properties": {"recipe_id": {"type": "integer"}},
            "required": ["recipe_id"],
        },
    },
    {
        "name": "cooked_recipe",
        "description": "The user made a recipe from the library: subtracts its ingredients from stock, logs the "
                        "servings they ate, and learns their taste.",
        "parameters": {
            "type": "object",
            "properties": {"recipe_id": {"type": "integer"}, "servings_eaten": {"type": "number"}},
            "required": ["recipe_id"],
        },
    },
    {
        "name": "get_inventory",
        "description": "Everything on hand in the fridge and pantry, with amounts and what's expiring soon.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_goals",
        "description": "The user's nutrition targets, diet type, allergies, and dislikes.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "get_intake",
        "description": "What the user has eaten so far, for a period.",
        "parameters": {
            "type": "object",
            "properties": {"period": {"type": "string", "enum": ["today", "week"]}},
            "required": ["period"],
        },
    },
    {
        "name": "check_recipe",
        "description": "Computes real nutrition for a recipe from the food database and confirms "
                        "stock is sufficient and there are no allergen conflicts. Always call this "
                        "before presenting a recipe to the user.",
        "parameters": {
            "type": "object",
            "properties": {
                "servings": {"type": "number"},
                "ingredients_g": {
                    "type": "object",
                    "description": "Map of ingredient name -> grams needed for the whole recipe.",
                },
            },
            "required": ["ingredients_g"],
        },
    },
    {
        "name": "log_meal",
        "description": "Records something the user ate that is NOT a library recipe (e.g. 'I had a yogurt'), "
                        "updates today's intake, and subtracts the ingredients from stock.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipe_name": {"type": "string"},
                "servings": {"type": "number"},
                "ingredients_g": {"type": "object"},
            },
            "required": ["recipe_name", "servings", "ingredients_g"],
        },
    },
    {
        "name": "add_item",
        "description": "Adds a manually-reported pantry/freezer item, e.g. from chat ('I bought rice').",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "grams": {"type": "number"},
                "location": {"type": "string", "enum": ["pantry", "freezer", "fridge"]},
            },
            "required": ["name", "grams", "location"],
        },
    },
    {
        "name": "update_item",
        "description": "Adjusts how much of a pantry item is left, e.g. 'I used the last of the rice'.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "remaining_grams": {"type": "number"},
            },
            "required": ["name", "remaining_grams"],
        },
    },
]


class NutritionistChatbot:
    def __init__(self, db: Database):
        self.db = db
        self._engine: RecipeEngine | None = None
        self._turn_cards: list[dict] = []
        # Cards the person is looking at now. Chat history stores only text, so without
        # this the model forgets recipe ids between turns ("show me the first one").
        self._on_screen: list[dict] = []
        self._lock = threading.Lock()

    @property
    def engine(self) -> RecipeEngine:
        if self._engine is None:
            self._engine = RecipeEngine(self.db, get_store())
        return self._engine

    # ------------------------------------------------------------- recipes
    def _remember_cards(self, cards: list[dict], front: bool = False) -> None:
        fresh = [c for c in cards if all(c["id"] != k["id"] for k in self._turn_cards)]
        self._turn_cards = (fresh + self._turn_cards) if front else (self._turn_cards + fresh)

    def _find_recipes(self, args: dict) -> dict:
        cuisine = (args.get("cuisine") or "").strip() or None
        matches = self.engine.suggest(
            query=(args.get("query") or "").strip() or None,
            cuisine=cuisine,
            max_minutes=args.get("max_minutes") or None,
            high_protein=bool(args.get("high_protein")),
            must_have_all=bool(args.get("must_have_all")),
        )
        taste.record_request(self.db, cuisine=cuisine)
        # A new search replaces the cards on screen.
        self._turn_cards = []
        self._remember_cards([card(m) for m in matches])
        return {"recipes": [
            {"id": m.recipe.id, "name": m.recipe.name, "cuisine": m.recipe.cuisine, "minutes": m.recipe.minutes,
             "protein_g": m.recipe.nutrition.get("protein_g"), "calories": m.recipe.nutrition.get("calories"),
             "have": len(m.have), "missing": m.missing, "swaps": [f"{s.missing} -> {s.use}" for s in m.swaps],
             "uses_expiring": m.uses_expiring, "why": m.reasons}
            for m in matches
        ]}

    def _get_recipe(self, recipe_id: int) -> dict:
        recipe = self.engine.adapted(int(recipe_id))
        if recipe is None:
            return {"error": f"no recipe {recipe_id}"}
        self._remember_cards([{k: v for k, v in recipe.items() if k not in ("ingredients", "steps", "description")}], front=True)
        return recipe

    def _cooked_recipe(self, recipe_id: int, servings_eaten: float = 1.0) -> dict:
        return self.engine.cooked(int(recipe_id), servings_eaten) or {"error": f"no recipe {recipe_id}"}

    # --------------------------------------------------------------- tools
    def _get_inventory(self) -> dict:
        items = self.db.active_items()
        by_product: dict[int, dict] = {}
        for item in items:
            product = self.db.get_product(item["product_id"])
            if product is None:
                continue
            entry = by_product.setdefault(product["id"], {
                "name": product["name"], "category": product["category"], "grams": 0.0, "expiring": [],
            })
            entry["grams"] += item["grams"]
            if item["expiration_date"]:
                entry["expiring"].append(describe_expiry(item["expiration_date"], bool(item["expiration_estimated"])))
        alerts = [a.__dict__ for a in low_stock_alerts(self.db)]
        return {"items": list(by_product.values()), "alerts": alerts}

    def _get_goals(self) -> dict:
        profile = self.db.get_profile()
        return {
            "daily_calories": profile["daily_calories"],
            "daily_protein_g": profile["daily_protein_g"],
            "daily_carbs_g": profile["daily_carbs_g"],
            "daily_fat_g": profile["daily_fat_g"],
            "diet_type": profile["diet_type"],
            "allergies": json.loads(profile["allergies"] or "[]"),
            "dislikes": json.loads(profile["dislikes"] or "[]"),
        }

    def _get_intake(self, period: str) -> dict:
        return get_intake(self.db, period)

    def _resolve_ingredient_nutrition(self, name: str) -> dict:
        product = self.db.find_product_by_name(name)
        if product is not None and product["calories_per_100g"] is not None:
            return {
                "calories": product["calories_per_100g"], "protein_g": product["protein_g_per_100g"],
                "carbs_g": product["carbs_g_per_100g"], "fat_g": product["fat_g_per_100g"],
            }
        looked_up = lookup_nutrition_usda(name)
        return looked_up or {"calories": None, "protein_g": None, "carbs_g": None, "fat_g": None}

    def check_recipe(self, ingredients_g: dict[str, float], servings: float = 1) -> dict:
        goals = self._get_goals()
        totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        insufficient_stock: list[str] = []

        allergen_conflicts = allergen_hits(list(ingredients_g), goals["allergies"])
        for name, grams in ingredients_g.items():
            product = self.db.find_product_by_name(name)
            if product is not None:
                on_hand = grams_on_hand(self.db, product["id"])
                if on_hand < grams:
                    insufficient_stock.append(f"{name} (have {on_hand:.0f}g, need {grams:.0f}g)")

            per100 = self._resolve_ingredient_nutrition(name)
            factor = grams / 100.0
            for key in totals:
                if per100.get(key) is not None:
                    totals[key] += per100[key] * factor

        per_serving = {k: (v / servings if servings else v) for k, v in totals.items()}
        return {
            "ok": not insufficient_stock and not allergen_conflicts,
            "nutrition_total": totals,
            "nutrition_per_serving": per_serving,
            "insufficient_stock": insufficient_stock,
            "allergen_conflicts": allergen_conflicts,
        }

    def _log_meal_tool(self, recipe_name: str, servings: float, ingredients_g: dict[str, float]) -> dict:
        check = self.check_recipe(ingredients_g, servings)
        if check["allergen_conflicts"]:
            return {"logged": False, "reason": "allergen conflict", **check}

        for name, grams in ingredients_g.items():
            product = self.db.find_product_by_name(name)
            if product is None:
                continue
            remaining = grams
            for item in self.db.active_items():
                if item["product_id"] != product["id"] or remaining <= 0:
                    continue
                take = min(item["grams"], remaining)
                inv_events.apply_consume(self.db, item["id"], take)
                remaining -= take

        meal_id = log_meal_eaten(
            self.db, recipe_name, servings, check["nutrition_per_serving"], source="chat"
        )
        return {"logged": True, "meal_id": meal_id, **check}

    def _add_item_tool(self, name: str, grams: float, location: str) -> dict:
        per100 = self._resolve_ingredient_nutrition(name)
        product_id = self.db.get_or_create_product(name, nutrition_per_100g=per100, nutrition_source="usda")
        item_id = inv_events.apply_add(self.db, product_id, grams, location=location)
        return {"item_id": item_id, "product_id": product_id}

    def _update_item_tool(self, name: str, remaining_grams: float) -> dict:
        product = self.db.find_product_by_name(name)
        if product is None:
            return {"updated": False, "reason": f"no known product named {name!r}"}
        items = [i for i in self.db.active_items() if i["product_id"] == product["id"]]
        if not items:
            return {"updated": False, "reason": f"no active {name} items on hand"}
        current_total = sum(i["grams"] for i in items)
        delta = current_total - remaining_grams
        if delta > 0:
            inv_events.apply_consume(self.db, items[0]["id"], min(delta, items[0]["grams"]))
        else:
            self.db.update_item_grams(items[0]["id"], items[0]["grams"] - delta)
        return {"updated": True}

    def _run_tool(self, name: str, tool_input: dict) -> dict:
        if name == "find_recipes":
            return self._find_recipes(tool_input)
        if name == "get_recipe":
            return self._get_recipe(tool_input["recipe_id"])
        if name == "cooked_recipe":
            return self._cooked_recipe(tool_input["recipe_id"], tool_input.get("servings_eaten") or 1.0)
        if name == "get_inventory":
            return self._get_inventory()
        if name == "get_goals":
            return self._get_goals()
        if name == "get_intake":
            return self._get_intake(tool_input["period"])
        if name == "check_recipe":
            return self.check_recipe(tool_input["ingredients_g"], tool_input.get("servings", 1))
        if name == "log_meal":
            return self._log_meal_tool(tool_input["recipe_name"], tool_input["servings"], tool_input["ingredients_g"])
        if name == "add_item":
            return self._add_item_tool(tool_input["name"], tool_input["grams"], tool_input["location"])
        if name == "update_item":
            return self._update_item_tool(tool_input["name"], tool_input["remaining_grams"])
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------------ chat
    def chat(self, user_message: str) -> dict:
        """Returns {"reply": text, "recipes": [cards]} — cards are the recipes this turn surfaced."""
        # The fridge screen and the phone share one chatbot; one conversation turn at a time
        # keeps each turn's recipe cards from mixing.
        with self._lock:
            self._turn_cards = []
            self.db.add_chat_message("user", user_message)
            client = make_client()
            if client is None:
                reply = self._offline_reply(user_message)
            else:
                try:
                    reply = self._converse(client)
                except Exception:
                    log.exception("Gemini chat failed")
                    reply = "Sorry, I couldn't reach the assistant just now — here are some ideas anyway."
                    if not self._turn_cards:
                        self._offline_reply(user_message)
            reply = plain_text(reply)
            self.db.add_chat_message("assistant", reply)
            cards = order_by_mention(self._turn_cards, reply)[:MAX_CARDS]
            if cards:
                self._on_screen = cards
            return {"reply": reply, "recipes": cards}

    def _converse(self, client) -> str:
        """Gemini function-calling loop: the model asks for tools, we run them
        against the real database, until it answers in plain text."""
        config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT, tools=[types.Tool(function_declarations=TOOLS)],
        )
        contents = [
            types.Content(role=("model" if m["role"] == "assistant" else "user"),
                          parts=[types.Part.from_text(text=m["content"])])
            for m in self.db.recent_chat(limit=20)
        ]
        if self._on_screen and contents:
            shown = "; ".join(f"{i}. {c['name']} (recipe_id {c['id']})" for i, c in enumerate(self._on_screen, 1))
            contents[-1].parts.append(types.Part.from_text(
                text=f"[Recipe cards currently on the user's screen, in order: {shown}]"))

        for _ in range(MAX_TOOL_ROUNDS):
            response = client.models.generate_content(model=model_name(), contents=contents, config=config)
            candidate_content = response.candidates[0].content
            function_calls = [p.function_call for p in (candidate_content.parts or []) if p.function_call]
            if not function_calls:
                return response.text or "Sorry, I don't have an answer for that."

            contents.append(candidate_content)
            response_parts = [
                types.Part.from_function_response(name=fc.name, response={"result": self._run_tool(fc.name, dict(fc.args or {}))})
                for fc in function_calls
            ]
            contents.append(types.Content(role="user", parts=response_parts))

        return "Sorry, I'm having trouble pulling that together right now — could you try rephrasing?"

    def _offline_reply(self, user_message: str) -> str:
        """No Gemini: read the request with plain keywords and still search real recipes."""
        text = user_message.lower()
        cuisine = next((c for c in CUISINES if c.replace("-", " ") in text), None)
        words = [w for w in re.findall(r"[a-z]+", text)
                 if w not in OFFLINE_STOPWORDS and (cuisine is None or w not in cuisine.split("-"))]
        self._find_recipes({
            "query": " ".join(words[:6]),
            "cuisine": cuisine,
            "high_protein": "protein" in text,
            "max_minutes": 30 if any(w in text for w in ("quick", "fast", "easy")) else None,
        })
        if not self._turn_cards:
            return "I couldn't find a match for that — try a cuisine like Italian or an ingredient you have."
        lead = f"Here are some {cuisine.replace('-', ' ').title()} ideas" if cuisine else "Here are some ideas"
        return lead + " based on what's in your fridge. (Add a Gemini key for full conversation.)"


def plain_text(reply: str) -> str:
    """The screens show plain text; drop markdown emphasis/headings if the model adds them anyway."""
    reply = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), reply)
    reply = re.sub(r"(?m)^\s*#{1,6}\s*", "", reply)
    reply = re.sub(r"(?m)^(\s*)[*•-]\s+", r"\1• ", reply)
    return reply.strip()


def _name_variants(name: str) -> list[str]:
    """'Chicken Vino Bianco - Tastes Just Like Olive Garden' -> full name, 'chicken vino bianco', ..."""
    low = name.lower()
    variants = [low, re.split(r"\s[-–(:]\s?|\(", low)[0].strip()]
    words = variants[1].split()
    if len(words) > 3:
        variants.append(" ".join(words[:3]))
    return [v for v in variants if len(v) >= 4]


def order_by_mention(cards: list[dict], reply: str) -> list[dict]:
    """Cards in the order the reply talks about them, so "the first one" means the same
    thing to the person and to the model; unmentioned cards keep their rank after those."""
    low = reply.lower()

    def position(c: dict) -> int:
        hits = [i for v in _name_variants(c["name"]) if (i := low.find(v)) >= 0]
        return min(hits) if hits else len(low) + 1

    return sorted(cards, key=position)
