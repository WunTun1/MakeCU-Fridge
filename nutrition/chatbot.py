"""Nutritionist chatbot: the AI talks and suggests, code does the math and
checks facts. Section 11.

The model proposes recipes; every tool call below is plain Python against
the real database — nutrition numbers, stock levels, and allergy checks are
never left to the model's judgment. `check_recipe` is the one tool that can
veto a suggestion (insufficient stock or an allergen match) and the system
prompt tells the model to treat that as final, not something to argue past.
"""
from __future__ import annotations

import json
import os

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

from inventory import events as inv_events
from inventory.database import Database
from intelligence.alerts import low_stock_alerts
from intelligence.consumption import grams_on_hand
from nutrition.intake import get_intake, log_meal_eaten
from nutrition.lookup import lookup_nutrition_usda, nutrition_for_grams

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """You are ReFridge's nutritionist assistant. You talk and suggest; the tools \
do the math and check facts — never compute nutrition or stock yourself, always call a tool. \
If check_recipe reports an allergen conflict or insufficient stock, that is final: adjust the \
recipe or ask the user, never claim it's fine anyway. This is general wellness information, not \
medical advice — suggest a doctor or dietitian for medical conditions, keep suggestions in \
healthy ranges, and never shame the user about what they eat or haven't eaten. When a recipe \
checks out, offer it with its macros and mention any expiring ingredients it uses."""

TOOLS = [
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
        "description": "Records a meal the user actually ate, updates today's intake, and subtracts "
                        "the ingredients from fridge/pantry stock.",
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
                entry["expiring"].append(item["expiration_date"])
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
        allergen_conflicts: list[str] = []

        for name, grams in ingredients_g.items():
            lname = name.lower()
            for allergen in goals["allergies"]:
                if allergen.lower() in lname:
                    allergen_conflicts.append(name)

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
    def chat(self, user_message: str) -> str:
        self.db.add_chat_message("user", user_message)
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or genai is None:
            reply = self._fallback_reply(user_message)
            self.db.add_chat_message("assistant", reply)
            return reply

        client = genai.Client(api_key=api_key)
        tool = types.Tool(function_declarations=TOOLS)
        config = types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, tools=[tool])

        history = self.db.recent_chat(limit=20)
        contents = [
            types.Content(role=("model" if m["role"] == "assistant" else "user"),
                           parts=[types.Part.from_text(text=m["content"])])
            for m in history
        ]

        for _ in range(MAX_TOOL_ROUNDS):
            response = client.models.generate_content(
                model=os.getenv("GEMINI_MODEL", DEFAULT_MODEL), contents=contents, config=config,
            )
            candidate_content = response.candidates[0].content
            function_calls = [p.function_call for p in candidate_content.parts if p.function_call]

            if not function_calls:
                final_text = response.text or ""
                self.db.add_chat_message("assistant", final_text)
                return final_text

            contents.append(candidate_content)
            response_parts = []
            for fc in function_calls:
                result = self._run_tool(fc.name, dict(fc.args or {}))
                response_parts.append(types.Part.from_function_response(name=fc.name, response={"result": result}))
            contents.append(types.Content(role="user", parts=response_parts))

        reply = "Sorry, I'm having trouble pulling that together right now — could you try rephrasing?"
        self.db.add_chat_message("assistant", reply)
        return reply

    def _fallback_reply(self, user_message: str) -> str:
        return (
            "AI chat isn't configured yet (set GEMINI_API_KEY to enable the nutritionist assistant). "
            "In the meantime, check the Home and Search screens for inventory and alerts."
        )
