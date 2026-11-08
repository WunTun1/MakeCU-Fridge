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
from intelligence.consumption import grams_on_hand
from intelligence.fridge_view import chat_inventory, day_word, fact_block, inventory_entries, leftovers_line
from nutrition.intake import eat_product, get_intake, log_meal_eaten, log_nutrition, protein_mode
from nutrition.lookup import lookup_nutrition_usda
from recipes.engine import RecipeEngine, card
from recipes.ingredients import TREE_NUTS, allergen_found, allergen_hits
from recipes.store import CUISINES, get_store

log = logging.getLogger("refridge.nutrition.chatbot")

MAX_TOOL_ROUNDS = 6
MAX_CARDS = 4
SAFE_CARDS = 3  # cards shown after an allergy block, from the same search without the allergen
# "40 g protein per serving" with nothing that high: look again this much lower and say so.
PROTEIN_RELAX_G = 10
# Words that say how you're asking, not what you want to eat (offline keyword mode).
OFFLINE_STOPWORDS = {
    "i", "im", "want", "wanna", "feel", "feeling", "like", "some", "something", "food", "make", "cook",
    "can", "could", "what", "with", "need", "more", "a", "an", "the", "for", "me", "to", "and", "or",
    "today", "tonight", "dinner", "lunch", "breakfast", "please", "high", "protein", "quick", "fast",
    "easy", "recipe", "recipes", "idea", "ideas", "of", "in", "my", "fridge", "have", "do", "is", "it",
}

# Eating is not cooking: these messages never take a recipe's ingredients out of the fridge.
LEFTOVER_WORDS = re.compile(r"\bleft\s*-?\s*overs?\b", re.I)
ATE_WORDS = re.compile(r"\b(had|ate|eaten)\b", re.I)
MADE_WORDS = re.compile(r"\b(made|cooked|baked|prepared|fixed)\b", re.I)
LOG_WORDS = re.compile(r"\b(log|had|ate|eaten|eat|eating)\b", re.I)
DINNER_WORDS = re.compile(r"\b(supper|dinner|tonight)\b", re.I)
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "a": 1, "an": 1}
NAME_FILLER = {"the", "my", "of", "leftovers", "leftover", "serving", "servings", "some", "one", "log", "had", "ate"}


def only_ate(message: str) -> bool:
    """'I had the leftovers', 'I ate the chicken': eaten, not cooked. 'I made it and ate two' is cooked."""
    return bool(LEFTOVER_WORDS.search(message)) or (bool(ATE_WORDS.search(message)) and not MADE_WORDS.search(message))

SYSTEM_PROMPT = """You are ReFridge's assistant in the phone app. Keep replies short (2-4 sentences). \
Write plain text only: no markdown, no asterisks or bold, no headings; for recipe steps use short lines \
starting with "1.", "2.".

The fridge: each message ends with "Fridge facts from the app". They are exact and current; use them \
and never guess. For what to eat (tonight, supper, lunch, "what should I have"), name the leftovers \
first, with their servings and the day they keep until. For what's going bad, list exactly the items in \
the facts, all of them, with their day words, and nothing else. Call get_inventory for anything else. \
Never mention the facts note itself.

Recipes: ONLY suggest recipes returned by find_recipes; never invent a recipe, ingredient list, or \
nutrition numbers. Turn the user's request into find_recipes arguments (e.g. "I want Italian" -> \
cuisine="italian"; "something with chicken, quick" -> query="chicken", max_minutes=30; "more protein" \
-> high_protein=true). Supper, dinner and tonight searches return only dinner-sized main dishes. Recipe \
cards are shown to the user automatically, so don't list every ingredient; say which one or two you'd \
pick and why (uses something expiring, matches their goals, swaps they can make, what they'd need to \
buy). Call get_recipe before walking through steps. If the user narrows things down ("no, something \
lighter"), call find_recipes again with new arguments.

Meal prep: "meal prep", "batch" or "for the week" -> min_servings=4. A protein number ("40 g protein \
per serving") -> min_protein_g=40. If a tool result has a "say" field, that sentence is already shown \
to the user; don't repeat or contradict it.

Eating is not cooking: call cooked_recipe only when the user says they made, cooked or baked a library \
recipe. Eating leftovers ("I had a serving of the leftovers") is ate_leftovers, never cooked_recipe or \
log_meal.

Facts: never compute nutrition or stock yourself — call a tool. Never say you logged, added or found \
something unless the tool result lists it; anything in "unresolved" was NOT logged. When logging, put \
every food the user named in one log_meal call, estimating usual portions (a scoop of protein powder is \
about 30 g, an egg 50 g) instead of asking. A "must_say" sentence is added to your reply automatically: \
don't write it or your own version of it. If the user gives protein and calories from a label \
("24 g protein, 120 kcal"), call log_meal with recipe_name, protein_g and calories and no ingredients_g. \
Allergens are filtered out in code; if a tool reports an \
allergy block or conflict, that is final: don't suggest that food, and never offer to look for it \
again. General wellness info only, not medical advice — suggest a doctor or dietitian for medical \
conditions. Never shame anyone about food. No exclamation marks."""

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
                "min_servings": {"type": "integer", "description": "Meal prep / batch cooking: 4."},
                "min_protein_g": {"type": "number", "description": "Protein per serving the user asked for."},
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
        "name": "ate_leftovers",
        "description": "The user ate leftovers that are in the fridge: takes the servings off the leftovers "
                        "and logs their nutrition. Never touches the recipe's ingredients.",
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "The dish, e.g. 'Greek Stuffed Chicken'."},
                           "servings": {"type": "number"}},
            "required": ["name"],
        },
    },
    {
        "name": "get_inventory",
        "description": "Everything on hand, soonest to go bad first: name, amount ('3 servings', '1 L'), "
                        "goes_bad words, days, leftovers flag and likely_throw_away; the freezer is listed apart.",
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
                        "updates today's intake, and subtracts the ingredients from stock. With protein_g and "
                        "calories instead of ingredients_g (numbers from a label), logs only the nutrition. "
                        "The result lists what was logged and what was unresolved (not counted).",
        "parameters": {
            "type": "object",
            "properties": {
                "recipe_name": {"type": "string"},
                "servings": {"type": "number"},
                "ingredients_g": {"type": "object", "description": "Map of ingredient name -> grams eaten."},
                "protein_g": {"type": "number"},
                "calories": {"type": "number"},
            },
            "required": ["recipe_name"],
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
        # Sentences code says itself this turn, whatever the model writes: tool notes (an allergy
        # block) first, anything a tool couldn't do last.
        self._turn_say: list[str] = []
        self._turn_must_say: list[str] = []
        self._turn_logged: list[str] = []
        self._turn_blocked = False
        self._turn_message = ""
        # What this turn changed, so the reply can offer one Undo for all of it.
        self._turn_meals: list[int] = []
        self._turn_events: list[int] = []
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

    def _say(self, sentence: str) -> None:
        if sentence not in self._turn_say:
            self._turn_say.append(sentence)

    def _find_recipes(self, args: dict) -> dict:
        cuisine = (args.get("cuisine") or "").strip() or None
        query = (args.get("query") or "").strip() or None
        blocked = allergen_found(f"{query or ''} {cuisine or ''}", self._get_goals()["allergies"])
        if blocked:
            return self._blocked(blocked, args, query)

        min_protein = args.get("min_protein_g") or None
        search = dict(
            query=query, cuisine=cuisine, max_minutes=args.get("max_minutes") or None,
            high_protein=bool(args.get("high_protein")) or protein_mode(self.db.get_profile()),
            must_have_all=bool(args.get("must_have_all")), min_servings=args.get("min_servings") or None,
            dinner=bool(DINNER_WORDS.search(self._turn_message)),
        )
        matches = self.engine.suggest(**search, min_protein_g=min_protein)
        result: dict = {}
        if min_protein and not matches:
            matches = self.engine.suggest(**search, min_protein_g=max(min_protein - PROTEIN_RELAX_G, 0))
            if matches:
                closest = max(m.recipe.nutrition.get("protein_g") or 0 for m in matches)
                result["say"] = f"Nothing has {min_protein:.0f} g protein per serving. Closest is {closest:.0f} g per serving."
                self._say(result["say"])
        taste.record_request(self.db, cuisine=cuisine)
        # A new search replaces the cards on screen.
        self._turn_cards = []
        self._remember_cards([card(m) for m in matches])
        result["recipes"] = [
            {"id": m.recipe.id, "name": m.recipe.name, "cuisine": m.recipe.cuisine, "minutes": m.recipe.minutes,
             "servings": m.recipe.servings,
             "protein_g": m.recipe.nutrition.get("protein_g"), "calories": m.recipe.nutrition.get("calories"),
             "have": len(m.have), "missing": m.missing,
             "short": [f"{s['name']} (you have {s['on_hand']})" for s in m.short], "swaps": [f"{s.missing} -> {s.use}" for s in m.swaps],
             "uses_expiring": m.uses_expiring, "why": m.reasons}
            for m in matches
        ]
        return result

    def _blocked(self, blocked: tuple[str, str], args: dict, query: str | None) -> dict:
        """The allergy sentence, then the same search without the allergen word when anything is left of
        it: 'You listed walnuts as an allergy, so I won't suggest recipes with them. Here are banana
        breads without nuts.'"""
        allergy, food = blocked
        say = f"You listed {allergy} as an allergy, so I won't suggest recipes with {'them' if allergy.endswith('s') else 'it'}."
        rest = re.sub(rf"\b{re.escape(food)}\b", " ", query or "", flags=re.I).split()
        self._turn_cards = []
        if rest and not allergen_found(" ".join(rest), [allergy]):
            self._find_recipes({**args, "query": " ".join(rest)})
            self._turn_cards = self._turn_cards[:SAFE_CARDS]
            if self._turn_cards:
                without = "nuts" if allergy.rstrip("s") in TREE_NUTS else allergy
                say += f" Here are {_plural(' '.join(rest))} without {without}."
        self._turn_blocked = True
        self._say(say)
        return {"recipes": [], "blocked": allergy, "say": say,
                "safe_recipes": [{"id": c["id"], "name": c["name"]} for c in self._turn_cards]}

    def _get_recipe(self, recipe_id: int) -> dict:
        recipe = self.engine.adapted(int(recipe_id))
        if recipe is None:
            return {"error": f"no recipe {recipe_id}"}
        self._remember_cards([{k: v for k, v in recipe.items() if k not in ("ingredients", "steps", "description")}], front=True)
        return recipe

    def _cooked_recipe(self, recipe_id: int, servings_eaten: float = 1.0) -> dict:
        """Only an explicit "I made / cooked it" takes ingredients. "I had the leftovers" eats leftovers;
        "I had it" with none left over logs the nutrition only. Code decides this, not the model."""
        recipe = self.engine.store.get(int(recipe_id))
        if recipe is None:
            return {"error": f"no recipe {recipe_id}"}
        if only_ate(self._turn_message):
            left = self.engine.leftovers_for(recipe.id)
            if left:
                return {**self._eat_leftovers(left["product_id"], servings_eaten), "routed": "ate_leftovers"}
            return {**self._log_recipe_eaten(recipe, servings_eaten), "routed": "logged_only"}
        result = self.engine.cooked(recipe.id, servings_eaten=servings_eaten)
        self._turn_meals.append(result["meal_id"])
        return result

    def _log_recipe_eaten(self, recipe, servings: float) -> dict:
        """Ate a recipe someone else cooked: the nutrition is logged, nothing leaves the fridge."""
        meal_id = log_meal_eaten(self.db, recipe.name, servings, recipe.nutrition, source="chat")
        self._turn_meals.append(meal_id)
        n = recipe.nutrition
        self._turn_logged.append(_logged_text({
            "name": f"{_servings(servings)} of {recipe.name}", "keep_case": True,
            **{k: n[k] * servings for k in ("protein_g", "calories") if n.get(k) is not None}}))
        self._turn_must_say.append("Nothing was taken from the fridge.")
        return {"logged": True, "meal_id": meal_id}

    def _leftovers_entries(self) -> list[dict]:
        return [e for e in inventory_entries(self.db) if e["leftovers"]]

    def _ate_leftovers(self, name: str, servings: float = 1.0) -> dict:
        """Finds the leftovers by name (whichever there are, when there's only one kind) and eats them."""
        entries = self._leftovers_entries()
        if not entries:
            self._turn_must_say.append("You don't have any leftovers, so I didn't log anything.")
            return {"logged": False, "reason": "no leftovers"}
        words = {w for w in re.findall(r"[a-z]+", name.lower()) if len(w) > 2 and w not in NAME_FILLER}

        def overlap(e: dict) -> int:
            return len(words & set(re.findall(r"[a-z]+", e["name"].lower())))

        best = max(entries, key=overlap)
        if overlap(best) == 0 and len({e["product_id"] for e in entries}) > 1:
            names = _join(sorted({e["name"] for e in entries}))
            self._turn_must_say.append(f"Which leftovers? You have {names}. I didn't log anything yet.")
            return {"logged": False, "reason": "which leftovers", "leftovers": [e["name"] for e in entries]}
        return self._eat_leftovers(best["product_id"], servings)

    def _eat_leftovers(self, product_id: int, servings: float) -> dict:
        """Same code as the app's "Ate one serving": servings come off the leftovers, nutrition is logged."""
        product = self.db.get_product(product_id)
        eaten = eat_product(self.db, product_id, servings * product["grams_per_unit"])
        if eaten is None:
            self._turn_must_say.append("You don't have any leftovers, so I didn't log anything.")
            return {"logged": False, "reason": "no leftovers"}
        self._turn_meals.append(eaten["meal_id"])
        ate = eaten["grams"] / product["grams_per_unit"]
        self._turn_logged.append(_logged_text({"name": f"{_servings(ate)} of {product['name']}", "keep_case": True,
                                               "protein_g": eaten["protein_g"], "calories": eaten["calories"]}))
        left = next((e for e in self._leftovers_entries() if e["product_id"] == product_id), None)
        if left is None:
            self._turn_must_say.append("That was the last of them.")
        else:
            keeps = left["expires_in_days"]
            until = "" if keeps is None or keeps < 0 else f", good until {day_word(keeps)}"
            self._turn_must_say.append(f"{_servings(round(left['grams'] / product['grams_per_unit']))} left{until}.")
        return {"logged": True, "meal_id": eaten["meal_id"], "servings_eaten": ate}

    # --------------------------------------------------------------- tools
    def _get_inventory(self) -> dict:
        return chat_inventory(self.db)

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

    def _log_meal_tool(self, recipe_name: str, servings: float = 1, ingredients_g: dict[str, float] | None = None,
                       protein_g: float | None = None, calories: float | None = None) -> dict:
        """Logs only what it can put a number on. Anything without nutrition data comes back as
        unresolved, with a sentence (must_say) the reply carries word for word. The reply's
        "Logged ..." sentence is written from what was actually logged."""
        if LEFTOVER_WORDS.search(self._turn_message) and self._leftovers_entries():
            return {**self._ate_leftovers(recipe_name, servings), "routed": "ate_leftovers"}
        if not ingredients_g:
            if protein_g is None and calories is None:
                return {"logged": False, "reason": "give ingredients_g, or protein_g and calories"}
            meal_id = log_nutrition(self.db, recipe_name, protein_g, calories, source="chat")
            self._turn_meals.append(meal_id)
            item = {"name": recipe_name, "protein_g": protein_g, "calories": calories}
            self._turn_logged.append(_logged_text(item))
            return {"logged": True, "meal_id": meal_id, "unresolved": [], "logged_items": [item]}

        if conflicts := allergen_hits(list(ingredients_g), self._get_goals()["allergies"]):
            return {"logged": False, "reason": "allergen conflict", "allergen_conflicts": conflicts}

        logged_items, unresolved = [], []
        totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
        for name, grams in ingredients_g.items():
            per100 = self._resolve_ingredient_nutrition(name)
            if per100.get("calories") is None and per100.get("protein_g") is None:
                unresolved.append(name)
                continue
            item: dict = {"name": name, "grams": grams}
            for key in totals:
                value = (per100.get(key) or 0.0) * grams / 100
                totals[key] += value
                if key in ("calories", "protein_g"):
                    item[key] = round(value)
            logged_items.append(item)

        result: dict = {"logged": bool(logged_items), "logged_items": logged_items, "unresolved": unresolved}
        if unresolved:
            result["must_say"] = (f"I couldn't find nutrition for {_join(unresolved)}, so it isn't counted. "
                                  "Tell me the protein and calories on the label.")
            self._turn_must_say.append(result["must_say"])
        if not logged_items:
            return result
        self._turn_logged += [_logged_text(item) for item in logged_items]

        per_serving = {k: v / servings for k, v in totals.items()} if servings else totals
        meal_id = log_meal_eaten(self.db, recipe_name, servings, per_serving, source="chat")
        self._turn_meals.append(meal_id)
        for item in logged_items:
            self._take_from_stock(item["name"], item["grams"], meal_id)
        return {**result, "meal_id": meal_id}

    def _take_from_stock(self, name: str, grams: float, meal_id: int) -> None:
        product = self.db.find_product_by_name(name)
        if product is None:
            return
        remaining = grams
        for item in self.db.active_items():
            if item["product_id"] != product["id"] or remaining <= 0:
                continue
            take = min(item["grams"], remaining)
            inv_events.apply_consume(self.db, item["id"], take, meta={"meal_id": meal_id})
            remaining -= take

    def _add_item_tool(self, name: str, grams: float, location: str) -> dict:
        per100 = self._resolve_ingredient_nutrition(name)
        product_id = self.db.get_or_create_product(name, nutrition_per_100g=per100, nutrition_source="usda")
        item_id = inv_events.apply_add(self.db, product_id, grams, location=location)
        self._turn_events += [e["id"] for e in self.db.events_for_item(item_id)]
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
            event_id = inv_events.apply_consume(self.db, items[0]["id"], min(delta, items[0]["grams"]), meta={"source": "chat"})
        else:
            event_id = inv_events.apply_adjust(self.db, items[0]["id"], -delta, meta={"source": "chat"})
        if event_id is not None:
            self._turn_events.append(event_id)
        return {"updated": True}

    def _run_tool(self, name: str, tool_input: dict) -> dict:
        if name == "find_recipes":
            return self._find_recipes(tool_input)
        if name == "get_recipe":
            return self._get_recipe(tool_input["recipe_id"])
        if name == "cooked_recipe":
            return self._cooked_recipe(tool_input["recipe_id"], tool_input.get("servings_eaten") or 1.0)
        if name == "ate_leftovers":
            return self._ate_leftovers(tool_input["name"], tool_input.get("servings") or 1.0)
        if name == "get_inventory":
            return self._get_inventory()
        if name == "get_goals":
            return self._get_goals()
        if name == "get_intake":
            return self._get_intake(tool_input["period"])
        if name == "check_recipe":
            return self.check_recipe(tool_input["ingredients_g"], tool_input.get("servings", 1))
        if name == "log_meal":
            return self._log_meal_tool(
                tool_input["recipe_name"], tool_input.get("servings") or 1, tool_input.get("ingredients_g"),
                tool_input.get("protein_g"), tool_input.get("calories"),
            )
        if name == "add_item":
            return self._add_item_tool(tool_input["name"], tool_input["grams"], tool_input["location"])
        if name == "update_item":
            return self._update_item_tool(tool_input["name"], tool_input["remaining_grams"])
        return {"error": f"unknown tool {name}"}

    # ------------------------------------------------------------------ chat
    def chat(self, user_message: str) -> dict:
        """Returns {"reply", "recipes", "turn_id", "undo"}: the cards this turn surfaced, and for a turn that
        changed stock, its id and an Undo label ("Undo: puts back 400 g chicken breast, 30 g butter")."""
        # One conversation turn at a time keeps each turn's cards and changes from mixing.
        with self._lock:
            self._turn_cards, self._turn_say, self._turn_must_say, self._turn_logged = [], [], [], []
            self._turn_meals, self._turn_events = [], []
            self._turn_blocked = False
            self._turn_message = user_message
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
                    if not (self._turn_cards or self._turn_meals or self._turn_events):
                        self._offline_reply(user_message)
            reply = self._with_code_sentences(plain_text(reply))
            self.db.add_chat_message("assistant", reply)
            cards = order_by_mention(self._turn_cards, reply)[:SAFE_CARDS if self._turn_blocked else MAX_CARDS]
            if cards:
                self._on_screen = cards
            return {"reply": reply, "recipes": cards, **self._record_turn()}

    def _record_turn(self) -> dict:
        """Saves what this turn changed. Only a turn that changed stock offers an Undo."""
        if not (self._turn_meals or self._turn_events):
            return {"turn_id": None, "undo": None}
        events = [e for m in self._turn_meals for e in self.db.events_for_meal(m)]
        events += [e for e in map(self.db.get_event, self._turn_events) if e is not None]
        summary = inv_events.undo_summary(self.db, events)
        turn_id = self.db.add_chat_turn(self._turn_meals, self._turn_events)
        return {"turn_id": turn_id if summary else None, "undo": f"Undo: {summary}" if summary else None}

    def undo_turn(self, turn_id: int) -> bool | None:
        """Reverses everything one reply did: its meals (with what they took from or put in the fridge)
        and its other stock changes. None when there's no such turn, False when it's already undone."""
        with self._lock:
            turn = self.db.get_chat_turn(turn_id)
            if turn is None:
                return None
            if turn["undone"]:
                return False
            for meal_id in json.loads(turn["meal_ids"]):
                self.engine.undo_meal(meal_id)
            events = [e for e in map(self.db.get_event, json.loads(turn["event_ids"])) if e is not None]
            for e in events:
                if e["event_type"] == "add":
                    self.db.delete_item(e["item_id"])
            inv_events.undo_events(self.db, [e["id"] for e in events if e["event_type"] != "add"])
            self.db.mark_chat_turn_undone(turn_id)
            return True

    def _with_code_sentences(self, reply: str) -> str:
        """What tools did is said by code, not paraphrased by the model: an allergy block replaces
        the reply (the model may still offer the blocked food), and a logging turn is answered with
        exactly what was logged and what wasn't. Other tool sentences go before the model's text."""
        if self._turn_blocked:
            return " ".join(self._turn_say)
        if self._turn_logged or self._turn_must_say:
            logged = [f"Logged {'; '.join(self._turn_logged)}."] if self._turn_logged else []
            return " ".join([*self._turn_say, *logged, *self._turn_must_say])
        body = reply
        for sentence in self._turn_say:
            body = body.replace(sentence, "").strip()
        return " ".join(s for s in [*self._turn_say, body] if s)

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
        if contents:
            contents[-1].parts.append(types.Part.from_text(text=fact_block(self.db)))
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
        if LEFTOVER_WORDS.search(text):
            if LOG_WORDS.search(text) and not text.rstrip().endswith("?"):
                count = re.search(r"\b(\d+|one|two|three|four|a|an)\s+servings?\b", text)
                servings = (NUMBER_WORDS.get(count.group(1)) or float(count.group(1))) if count else 1
                self._ate_leftovers(user_message, servings)
                return ""
            left = [leftovers_line(e) for e in self._leftovers_entries() if e["location"] != "freezer"]
            return f"You have {_join(left)}." if left else "You don't have any leftovers right now."
        cuisine = next((c for c in CUISINES if c.replace("-", " ") in text), None)
        words = [w for w in re.findall(r"[a-z]+", text)
                 if w not in OFFLINE_STOPWORDS and (cuisine is None or w not in cuisine.split("-"))]
        self._find_recipes({
            "query": " ".join(words[:6]),
            "cuisine": cuisine,
            "high_protein": "protein" in text,
            "max_minutes": 30 if any(w in text for w in ("quick", "fast", "easy")) else None,
        })
        if self._turn_blocked:
            return ""
        if not self._turn_cards:
            return "I couldn't find a match for that — try a cuisine like Italian or an ingredient you have."
        lead = f"Here are some {cuisine.replace('-', ' ').title()} ideas" if cuisine else "Here are some ideas"
        return lead + " based on what's in your fridge. (Add a Gemini key for full conversation.)"


def _logged_text(item: dict) -> str:
    """'Greek yogurt 200 g (20 g protein, 118 kcal)', 'Whey (24 g protein, 120 kcal)'."""
    amount = f" {item['grams']:.0f} g" if item.get("grams") else ""
    facts = [f"{item['protein_g']:.0f} g protein" if item.get("protein_g") is not None else None,
             f"{item['calories']:.0f} kcal" if item.get("calories") is not None else None]
    details = ", ".join(f for f in facts if f)
    # A recipe or leftovers name keeps its own case: "1 serving of Greek Stuffed Chicken leftovers".
    name = item["name"] if item.get("keep_case") else f"{item['name'][:1].upper()}{item['name'][1:].lower()}"
    return f"{name}{amount}" + (f" ({details})" if details else "")


def _servings(n: float) -> str:
    """'1 serving', '2 servings', '1.5 servings'."""
    n = round(n, 1)
    text = f"{n:g}"
    return f"{text} serving" if n == 1 else f"{text} servings"


def _plural(phrase: str) -> str:
    """'banana bread' -> 'banana breads', 'stir fry' -> 'stir fries'."""
    if re.search(r"[^aeiou]y$", phrase):
        return phrase[:-1] + "ies"
    if re.search(r"(s|x|z|ch|sh)$", phrase):
        return phrase + "es"
    return phrase + "s"


def _join(names: list[str]) -> str:
    """'whey', 'whey and oats', 'whey, oats and chia'."""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def plain_text(reply: str) -> str:
    """The screens show plain text; drop markdown emphasis/headings if the model adds them anyway."""
    reply = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), reply)
    reply = re.sub(r"(?m)^\s*#{1,6}\s*", "", reply)
    reply = re.sub(r"(?m)^(\s*)[*•-]\s+", r"\1• ", reply)
    reply = re.sub(r"\s*\[?Fridge facts from the app[^\]\n]*\]?\.?", "", reply)  # the model citing its own note
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
