"""Find real recipes that fit right now — plain code; Gemini only talks.

Ranking blends, per recipe:
  coverage   share of its (non-staple) ingredients you have enough of, counting swaps
  relevance  how well it matches what you asked for (full-text search score)
  expiring   uses things about to go bad
  taste      fits what you've cooked and liked (intelligence/taste.py)
  goal       protein per serving, when you ask for protein
Allergies are a hard filter everywhere. Dislikes are a hard filter in automatic
lists (Cook tonight, One item away) and a strong penalty in chat unless you ask
for that ingredient. Every match carries human-readable reasons so the UI can
say *why* it was suggested.

"Have" is quantity-aware: on hand must cover at least 90% of what the recipe
needs, otherwise the line is "short" and says how much you have.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from intelligence import taste
from intelligence.expiry import days_until
from inventory import events as inv_events
from inventory.database import Database
from inventory.units import format_amount
from recipes.ingredients import allergen_hits, canonical, dislike_pattern, matches, needs_no_badge
from recipes.store import Recipe, RecipeStore
from recipes.substitutions import Swap, find_swap

EXPIRING_WITHIN_DAYS = 3
CANDIDATES = 300
# Protein per serving mapped to 0..1 between these: a 15 g "high protein" dish scores ~0.
PROTEIN_FLOOR_G, PROTEIN_TARGET_G = 10.0, 40.0
WEIGHTS = {"coverage": 0.35, "relevance": 0.20, "expiring": 0.15, "taste": 0.15, "goal": 0.15}
# Asking for protein explicitly should outrank convenience.
HIGH_PROTEIN_WEIGHTS = {"coverage": 0.25, "relevance": 0.15, "expiring": 0.10, "taste": 0.15, "goal": 0.35}
FREE_MISSING, MISSING_PENALTY, MAX_MISSING_PENALTY = 2, 0.04, 0.24
PHOTO_TIEBREAK = 0.03  # between near-equal picks, a card with a photo is easier to choose from
DISLIKE_PENALTY = 0.4
HAVE_RATIO = 0.9  # on hand covers at least this share of what the recipe needs -> "have"

# Protein mode (a protein-led goal, or asked for): hide low-protein recipes, rank by protein.
PROTEIN_MODE_MIN_G, PROTEIN_MODE_RELAXED_G, PROTEIN_MODE_MIN_RESULTS = 25.0, 20.0, 3
PROTEIN_RICH_PER_100G = 15.0   # pantry items that seed a protein-mode search (chicken, Greek yogurt, eggs)
PROTEIN_SORT_POOL = 3          # protein mode re-sorts the best `limit * this` matches by protein
SEARCH_SEED_ITEMS = 12

# Cooked food left over: a fridge item counted in servings (USDA: cooked leftovers keep 3-4 days).
LEFTOVER_DAYS = 3
LEFTOVER_SERVING_G = 300.0

# Automatic lists (Cook tonight, One item away) fill a dinner slot.
DINNER_MINUTES, DINNER_MINUTES_RELAXED, DINNER_MIN_RESULTS = 45, 60, 3
DINNER_MIN_KCAL = 250
NOT_DINNER_TAGS = {"desserts", "breakfast", "beverages", "cookies-and-brownies", "condiments-etc", "sauces"}

# Rough grams per unit, for comparing and subtracting stock.
UNIT_GRAMS = {
    "cup": 200, "cups": 200, "c": 200, "tablespoon": 15, "tablespoons": 15, "tbsp": 15, "teaspoon": 5,
    "teaspoons": 5, "tsp": 5, "oz": 28, "ounce": 28, "ounces": 28, "lb": 454, "lbs": 454, "pound": 454,
    "pounds": 454, "g": 1, "gram": 1, "grams": 1, "kg": 1000, "ml": 1, "l": 1000, "liter": 1000,
    "can": 400, "cans": 400, "package": 300, "packages": 300, "clove": 5, "cloves": 5, "slice": 30,
    "slices": 30, "stick": 113, "sticks": 113, "pinch": 1, "dash": 1,
}
# "3 eggs", "1/2 large onion": counted in pieces.
PIECE_UNITS = {"", "large", "medium", "small", "whole", "piece", "pieces", "head", "heads", "ear", "ears"}
DEFAULT_PIECE_G = 100


@dataclass
class Match:
    recipe: Recipe
    have: list[str] = field(default_factory=list)       # enough on hand
    short: list[dict] = field(default_factory=list)     # {name, on_hand, use?}: some, not enough
    missing: list[str] = field(default_factory=list)    # none on hand, even after swaps
    swaps: list[Swap] = field(default_factory=list)     # enough of a substitute
    rewrites: list[Swap] = field(default_factory=list)  # every swap written into the steps, short or not
    uses_expiring: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def to_buy(self) -> list[str]:
        return self.missing + [s["name"] for s in self.short]


@dataclass
class Pantry:
    """What you have right now, keyed by canonical name."""
    items: dict[str, str]                 # canonical -> display name
    expiring: dict[str, int]              # canonical -> days until expiry (only soon ones)
    item_rows: dict[str, list] = field(default_factory=dict)  # canonical -> active rows, soonest expiry first
    products: dict[str, object] = field(default_factory=dict)  # canonical -> product row

    def grams(self, canon: str) -> float:
        return sum(r["grams"] for r in self.item_rows.get(canon, []))


def display_name(name: str) -> str:
    """'chicken stock (from pressure cooker recipe)' -> 'chicken stock'; 'onion, chopped' -> 'onion'."""
    tidy = re.sub(r"\s*\([^)]*\)?", "", name).split(",")[0].strip()
    return tidy or name


def _number(quantity: str | None) -> float:
    """'1 1/2' -> 1.5; '2-3' -> 2; unreadable -> 0."""
    total = 0.0
    for part in str(quantity or "").split("-")[0].split():
        try:
            if "/" in part:
                num, den = part.split("/", 1)
                total += float(num) / float(den)
            else:
                total += float(part)
        except (ValueError, ZeroDivisionError):
            continue
    return total


def parse_amount(quantity: str | None, unit: str | None) -> tuple[float, bool] | None:
    """(amount, in_pieces): grams for weights and volumes, a count for '3 eggs'. None when unreadable."""
    amount = _number(quantity)
    u = (unit or "").strip().lower().rstrip(".")
    if amount <= 0:
        return None
    if u in UNIT_GRAMS:
        return amount * UNIT_GRAMS[u], False
    if u in PIECE_UNITS:
        return amount, True
    return None


def quantity_to_grams(quantity: str | None, unit: str | None) -> float:
    """'1 1/2' cups -> 300 g. Rough on purpose: unreadable amounts count as one 100 g piece."""
    amount = _number(quantity) or 1.0
    return amount * UNIT_GRAMS.get((unit or "").strip().lower().rstrip("."), DEFAULT_PIECE_G)


def grams_needed(ing: dict, product) -> float | None:
    """What one recipe line needs, in grams of this product. None when the amount can't be read."""
    parsed = parse_amount(ing.get("quantity"), ing.get("unit"))
    if parsed is None:
        return None
    amount, pieces = parsed
    if not pieces:
        return amount
    return amount * (product["grams_per_unit"] if product["unit"] == "count" else DEFAULT_PIECE_G)


def leftovers_name(recipe_name: str) -> str:
    return f"{recipe_name} leftovers"


def normalized_title(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", name.lower()))


def fits_dinner(recipe: Recipe) -> bool:
    """A main dish, not a dessert/breakfast/drink/sauce, and a real meal's worth of calories."""
    tags = set(recipe.tags)
    kcal = recipe.nutrition.get("calories")
    return ("main-dish" in tags and not tags & NOT_DINNER_TAGS
            and (kcal is None or kcal >= DINNER_MIN_KCAL)
            and (recipe.minutes is None or recipe.minutes <= DINNER_MINUTES_RELAXED))


def dislike_hits(recipe: Recipe, patterns: list[re.Pattern]) -> list[re.Pattern]:
    """Dislikes found in ingredient names or step text ('cream of mushroom soup' counts as mushroom)."""
    text = " ".join([i["name"] for i in recipe.ingredients] + recipe.steps)
    return [p for p in patterns if p.search(text)]


def has_allergen(recipe: Recipe, allergies: list[str]) -> bool:
    """Ingredient lines, the title ('Chicken (Or Shrimp) Lo Mein') and the steps all count."""
    return bool(allergies) and bool(allergen_hits([i["name"] for i in recipe.ingredients] + [recipe.name] + recipe.steps,
                                                  allergies))


def _protein_of(m: Match) -> float | None:
    return m.recipe.nutrition.get("protein_g")


def protein_floor(items: list, protein_of=_protein_of) -> list:
    """Protein mode: only recipes with protein data and at least 25 g a serving (20 g when that leaves fewer than 3)."""
    def at_least(grams: float) -> list:
        return [x for x in items if (protein_of(x) or 0) >= grams]

    strict = at_least(PROTEIN_MODE_MIN_G)
    return strict if len(strict) >= PROTEIN_MODE_MIN_RESULTS else at_least(PROTEIN_MODE_RELAXED_G)


def protein_key(m: Match) -> tuple[float, float]:
    """Most protein per serving first; between equals, more protein per calorie."""
    protein = _protein_of(m) or 0.0
    kcal = m.recipe.nutrition.get("calories") or 0.0
    return protein, (protein / kcal if kcal else 0.0)


class RecipeEngine:
    def __init__(self, db: Database, store: RecipeStore):
        self.db = db
        self.store = store

    # -------------------------------------------------------------- pantry
    def pantry(self) -> Pantry:
        p = Pantry({}, {})
        for item in self.db.active_items():
            product = self.db.get_product(item["product_id"])
            if product is None or item["grams"] <= 0:
                continue
            canon = canonical(product["name"])
            if not canon:
                continue
            p.items.setdefault(canon, product["name"])
            p.products.setdefault(canon, product)
            p.item_rows.setdefault(canon, []).append(item)
            if item["expiration_date"]:
                d = days_until(item["expiration_date"])
                if d <= EXPIRING_WITHIN_DAYS:
                    p.expiring[canon] = min(d, p.expiring.get(canon, d))
        for rows in p.item_rows.values():  # use the package that goes bad first
            rows.sort(key=lambda r: (r["expiration_date"] is None, r["expiration_date"] or "", r["id"]))
        return p

    def profile_filters(self) -> tuple[list[str], list[re.Pattern]]:
        """(allergies, dislike patterns) from the saved profile."""
        profile = self.db.get_profile()
        allergies = json.loads(profile["allergies"] or "[]")
        patterns = [dislike_pattern(d) for d in json.loads(profile["dislikes"] or "[]")]
        return allergies, [p for p in patterns if p]

    def _have(self, ingredient: str, pantry: Pantry) -> str | None:
        """Canonical pantry name that satisfies this recipe ingredient, if any."""
        for have in pantry.items:
            if matches(ingredient, have):
                return have
        return None

    def lines(self, recipe: Recipe, pantry: Pantry) -> list[dict]:
        """One entry per ingredient line: name, canon, status (have|short|swap|missing|staple), the
        pantry item it draws from (source), on_hand for short lines, and use/note for swaps."""
        out: list[dict] = []
        for ing in recipe.ingredients:
            canon = ing.get("canon") or canonical(ing["name"])
            line: dict = {"name": display_name(ing["name"]), "canon": canon, "ing": ing, "source": None}
            if needs_no_badge(ing["name"], canon):
                line["status"] = "staple"
            elif have := self._have(canon, pantry):
                line["source"] = have
            elif swap := find_swap(canon, pantry.items):
                line["source"] = next(c for c, d in pantry.items.items() if d == swap.use)
                line.update(use=swap.use, note=swap.note, swap=swap)
            else:
                line["status"] = "missing"
            out.append(line)

        need: dict[str, float] = {}  # summed per pantry item: "3 eggs" + "1 egg" both draw on Eggs
        for line in out:
            if line["source"]:
                g = grams_needed(line["ing"], pantry.products[line["source"]])
                if g is not None:
                    need[line["source"]] = need.get(line["source"], 0.0) + g
        for line in out:
            src = line["source"]
            if not src:
                continue
            on_hand = pantry.grams(src)
            if src in need and on_hand < HAVE_RATIO * need[src]:
                product = pantry.products[src]
                line["status"] = "short"
                line["on_hand"] = format_amount(on_hand, product["unit"], product["grams_per_unit"], product["name"])
            else:
                line["status"] = "swap" if line.get("swap") else "have"
        return out

    def analyze(self, recipe: Recipe, pantry: Pantry) -> Match:
        m = Match(recipe)
        seen: set[str] = set()
        for line in self.lines(recipe, pantry):
            status, canon = line["status"], line["canon"]
            if line.get("swap"):
                m.rewrites.append(line["swap"])
            if status == "staple" or canon in seen:  # some recipes list an ingredient twice
                continue
            seen.add(canon)
            if status == "have":
                m.have.append(line["name"])
            elif status == "swap":
                m.swaps.append(line["swap"])
            elif status == "short":
                m.short.append({"name": line["name"], "on_hand": line["on_hand"],
                                **({"use": line["use"]} if line.get("use") else {})})
            else:
                m.missing.append(line["name"])
            if line["source"] in pantry.expiring and not line.get("swap"):
                m.uses_expiring.append(pantry.items[line["source"]])
        m.uses_expiring = sorted(set(m.uses_expiring))
        return m

    # ------------------------------------------------------------- suggest
    def suggest(
        self,
        query: str | None = None,
        cuisine: str | None = None,
        max_minutes: int | None = None,
        high_protein: bool = False,
        must_have_all: bool = False,
        limit: int = 5,
        automatic: bool = False,
        min_servings: float | None = None,
        min_protein_g: float | None = None,
    ) -> list[Match]:
        """`automatic` is for lists nobody asked for (Cook tonight): dinner-sized main dishes only,
        dislikes excluded outright. `high_protein` is protein mode: see protein_floor and protein_key."""
        pantry = self.pantry()
        allergies, dislikes = self.profile_filters()
        prefs = taste.profile(self.db)

        search_text = query
        if not query and not cuisine:
            # "What can I make?" — search by what you have, things about to expire first; in protein
            # mode, the protein-rich things first (and only those plus what's expiring, when there are any).
            rich = {c for c, p in pantry.products.items() if (p["protein_g_per_100g"] or 0) >= PROTEIN_RICH_PER_100G}
            ordered = sorted(pantry.items, key=lambda c: (c not in pantry.expiring, c))
            if high_protein and rich:
                ordered = sorted(rich) + [c for c in ordered if c in pantry.expiring and c not in rich]
            search_text = " ".join(ordered[:SEARCH_SEED_ITEMS])

        minutes = DINNER_MINUTES_RELAXED if automatic else max_minutes
        hits = self.store.search(search_text, cuisine, minutes, CANDIDATES, main_dish_only=automatic)
        if len(hits) < limit and query and cuisine:  # too narrow — keep the cuisine, drop the free text
            seen = {i for i, _ in hits}
            hits += [(i, r * 0.5) for i, r in self.store.search(None, cuisine, minutes, CANDIDATES) if i not in seen]
        relevance = dict(hits)

        matches_: list[Match] = []
        for recipe in self.store.get_many([i for i, _ in hits]):
            if has_allergen(recipe, allergies):
                continue  # hard filter, never shown
            if min_servings and (recipe.servings is None or recipe.servings < min_servings):
                continue
            if min_protein_g and (recipe.nutrition.get("protein_g") or 0) < min_protein_g:
                continue
            disliked = dislike_hits(recipe, dislikes)
            if automatic and (disliked or not fits_dinner(recipe)):
                continue
            # In chat, naming a disliked ingredient ("mushroom risotto") means you want it this time.
            disliked = [p for p in disliked if not p.search(query or "")]
            m = self.analyze(recipe, pantry)
            if must_have_all and m.to_buy:
                continue
            needed = max(len(m.have) + len(m.swaps) + len(m.short) + len(m.missing), 1)
            coverage = (len(m.have) + 0.8 * len(m.swaps) + 0.5 * len(m.short)) / needed
            expiring = min(len(m.uses_expiring), 2) / 2
            affinity = taste.recipe_affinity(prefs, recipe)
            protein = recipe.nutrition.get("protein_g")
            if high_protein:
                goal = min(max(((protein or 0) - PROTEIN_FLOOR_G) / (PROTEIN_TARGET_G - PROTEIN_FLOOR_G), 0.0), 1.0)
            else:
                goal = 0.5

            w = HIGH_PROTEIN_WEIGHTS if high_protein else WEIGHTS
            # Beyond a couple of items, every extra thing to buy makes a recipe a worse "right now" pick.
            shopping = min(max(len(m.missing) - FREE_MISSING, 0) * MISSING_PENALTY, MAX_MISSING_PENALTY)
            m.score = (
                w["coverage"] * coverage
                + w["relevance"] * relevance.get(recipe.id, 0.0)
                + w["expiring"] * expiring
                + w["taste"] * (affinity + 1) / 2
                + w["goal"] * goal
                - shopping
                - (DISLIKE_PENALTY if disliked else 0.0)
                + (PHOTO_TIEBREAK if recipe.image_url else 0.0)
            )
            m.reasons = self._reasons(m, affinity, protein, high_protein)
            matches_.append(m)

        matches_.sort(key=lambda m: m.score, reverse=True)
        ranked = _dedupe(matches_)
        if automatic:
            quick = [m for m in ranked if m.recipe.minutes is None or m.recipe.minutes <= DINNER_MINUTES]
            if len(quick) >= DINNER_MIN_RESULTS:
                ranked = quick
        if high_protein:
            # The best fits for right now, shown highest protein first.
            ranked = sorted(protein_floor(ranked)[:limit * PROTEIN_SORT_POOL], key=protein_key, reverse=True)
        return ranked[:limit]

    @staticmethod
    def _reasons(m: Match, affinity: float, protein: float | None, high_protein: bool) -> list[str]:
        reasons = []
        if m.uses_expiring:
            reasons.append("Uses your " + ", ".join(m.uses_expiring[:2]) + " before it goes bad")
        total = len(m.have) + len(m.swaps) + len(m.short) + len(m.missing)
        if total:
            reasons.append(f"You have {len(m.have) + len(m.swaps)} of {total} ingredients")
        if high_protein and protein:
            reasons.append(f"{protein:.0f} g protein per serving")
        if affinity > 0.2 and m.recipe.cuisine:
            reasons.append(f"You've been enjoying {m.recipe.cuisine.replace('-', ' ')} food")
        return reasons

    # ------------------------------------------------------- one recipe
    def adapted(self, recipe_id: int) -> dict | None:
        """Full recipe with each ingredient marked have / short / swap / missing / staple, and
        swaps applied to the steps — ready to cook from."""
        recipe = self.store.get(recipe_id)
        if recipe is None:
            return None
        pantry = self.pantry()
        m = self.analyze(recipe, pantry)
        out = []
        for line in self.lines(recipe, pantry):
            ing = line["ing"]
            amount = " ".join(str(x) for x in (ing.get("quantity"), ing.get("unit")) if x)
            entry = {"name": line["name"], "amount": amount or None, "status": line["status"]}
            entry.update({k: line[k] for k in ("on_hand", "use", "note") if line.get(k)})
            out.append(entry)

        steps = list(recipe.steps)
        for s in m.rewrites:
            pattern = re.compile(rf"\b{re.escape(s.missing)}\w*", re.I)
            steps = [pattern.sub(s.use.lower(), step) for step in steps]

        return {**card(m), "ingredients": out, "steps": steps, "description": recipe.description}

    # ------------------------------------------------------- "I made this"
    def planned_use(self, recipe_id: int, made: float = 1.0) -> list[dict] | None:
        """What cooking `made` of the recipe (1 = all of it, 0.5 = half) would take from the fridge
        and pantry, without changing anything. Never divided by servings: you cook the whole pot
        whether one person eats it or four. Soonest-expiring packages are used first.
        Each entry: item row, product display name, grams to take."""
        recipe = self.store.get(recipe_id)
        if recipe is None:
            return None
        pantry = self.pantry()
        taken: dict[int, float] = {}
        plan: list[dict] = []
        for line in self.lines(recipe, pantry):
            src = line["source"]
            if not src:
                continue
            needed = grams_needed(line["ing"], pantry.products[src])
            if needed is None:
                needed = quantity_to_grams(line["ing"].get("quantity"), line["ing"].get("unit"))
            remaining = needed * made
            for item in pantry.item_rows.get(src, []):
                left = item["grams"] - taken.get(item["id"], 0.0)
                take = min(left, remaining)
                if take > 0:
                    taken[item["id"]] = taken.get(item["id"], 0.0) + take
                    plan.append({"item": item, "name": pantry.items[src], "grams": take})
                    remaining -= take
                if remaining <= 0:
                    break
        return plan

    def preview_cooked(self, recipe_id: int, made: float = 1.0) -> list[dict] | None:
        """Per product: grams used and grams on hand, for the confirm sheet."""
        plan = self.planned_use(recipe_id, made)
        if plan is None:
            return None
        on_hand: dict[int, float] = {}
        for item in self.db.active_items():
            on_hand[item["product_id"]] = on_hand.get(item["product_id"], 0.0) + item["grams"]
        lines: dict[int, dict] = {}
        for p in plan:
            pid = p["item"]["product_id"]
            if pid not in lines:
                product = self.db.get_product(pid)
                lines[pid] = {
                    "product_id": pid, "item": p["name"], "grams_used": 0.0, "grams_on_hand": on_hand.get(pid, 0.0),
                    "unit": product["unit"], "grams_per_unit": product["grams_per_unit"],
                }
            lines[pid]["grams_used"] += p["grams"]
        return [{**line, "grams_used": round(line["grams_used"], 1)} for line in lines.values()]

    def cooked(self, recipe_id: int, made: float = 1.0, servings_eaten: float = 1.0) -> dict | None:
        """Subtract what you made from the fridge/pantry (`made`: 1 = the full recipe, 0.5 = half),
        log the servings you ate as a meal, and teach the taste profile. Every consumption is
        tagged with the meal id so the whole thing can be undone (undo_meal)."""
        recipe = self.store.get(recipe_id)
        if recipe is None:
            return None
        preview = self.preview_cooked(recipe_id, made)
        plan = self.planned_use(recipe_id, made)
        n = recipe.nutrition
        meal_id = self.db.log_meal(
            recipe.name, servings_eaten,
            *(n.get(k) * servings_eaten if n.get(k) is not None else None
              for k in ("calories", "protein_g", "carbs_g", "fat_g")),
            source="recipe",
        )
        for p in plan:
            inv_events.apply_consume(self.db, p["item"]["id"], p["grams"], meta={"meal_id": meal_id})
        leftovers = self._store_leftovers(recipe, made, servings_eaten, meal_id)
        taste.record_recipe(self.db, "cooked", recipe)
        return {
            "recipe": recipe.name, "meal_id": meal_id, "made": made, "servings_eaten": servings_eaten,
            "used": [{"item": line["item"], "grams": round(line["grams_used"])} for line in preview],
            "consumptions": preview, "leftovers": leftovers,
        }

    def _store_leftovers(self, recipe: Recipe, made: float, servings_eaten: float, meal_id: int) -> dict | None:
        """Servings made minus servings eaten go in the fridge as '<Recipe> leftovers', counted in
        servings, good for LEFTOVER_DAYS. A second cook of the same recipe adds another batch."""
        if not recipe.servings:
            return None
        left = round(recipe.servings * made - servings_eaten)
        if left < 1:
            return None
        per_100g = {k: v * 100 / LEFTOVER_SERVING_G for k, v in recipe.nutrition.items()
                    if v is not None and k in ("calories", "protein_g", "carbs_g", "fat_g")}
        product_id = self.db.get_or_create_product(
            leftovers_name(recipe.name), category="leftovers", unit="count", recipe_id=recipe.id,
            nutrition_per_100g=per_100g, nutrition_source="recipe", grams_per_unit=LEFTOVER_SERVING_G,
        )
        expires = (datetime.now(timezone.utc).date() + timedelta(days=LEFTOVER_DAYS)).isoformat()
        item_id = inv_events.apply_add(self.db, product_id, left * LEFTOVER_SERVING_G, expiration_date=expires,
                                       expiration_estimated=True, meta={"meal_id": meal_id})
        return {"product_id": product_id, "item_id": item_id, "servings": left, "expiration_date": expires}

    def leftovers_for(self, recipe_id: int) -> dict | None:
        """Leftover servings of this recipe in the fridge now."""
        product = self.db.product_for_recipe(recipe_id)
        if product is None:
            return None
        grams = sum(i["grams"] for i in self.db.active_items() if i["product_id"] == product["id"])
        servings = round(grams / product["grams_per_unit"])
        return {"product_id": product["id"], "servings": servings} if servings >= 1 else None

    def undo_meal(self, meal_id: int) -> bool:
        """Take back an "I made this" or an eaten serving: the grams go back, leftovers it made
        go away, and the meal is deleted."""
        if self.db.get_meal(meal_id) is None:
            return False
        events = self.db.events_for_meal(meal_id)
        for e in events:
            if e["event_type"] == "add":
                self.db.delete_item(e["item_id"])
        inv_events.undo_events(self.db, [e["id"] for e in events if e["event_type"] != "add"])
        self.db.delete_meal(meal_id)
        return True

    def rate(self, recipe_id: int, liked: bool) -> bool:
        recipe = self.store.get(recipe_id)
        if recipe is None:
            return False
        taste.record_recipe(self.db, "liked" if liked else "disliked", recipe)
        return True


def _dedupe(ranked: list[Match]) -> list[Match]:
    """Food.com has the same dish under several ids; keep the best-scored copy of each title."""
    seen: set[str] = set()
    out = []
    for m in ranked:
        key = normalized_title(m.recipe.name)
        if key not in seen:
            seen.add(key)
            out.append(m)
    return out


def card(m: Match) -> dict:
    """Compact JSON for recipe cards in chat and on the phone's home screen."""
    r = m.recipe
    return {
        "id": r.id,
        "name": r.name,
        "cuisine": r.cuisine,
        "minutes": r.minutes,
        "servings": r.servings,
        "image_url": r.image_url,
        "nutrition": r.nutrition,
        "have_count": len(m.have),
        "short": m.short,
        "missing": m.missing,
        "swaps": [{"missing": s.missing, "use": s.use, "note": s.note} for s in m.swaps],
        "uses_expiring": m.uses_expiring,
        "reasons": m.reasons,
    }
