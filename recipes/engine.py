"""Find real recipes that fit right now — plain code; Gemini only talks.

Ranking blends, per recipe:
  coverage   share of its (non-staple) ingredients you have, counting swaps
  relevance  how well it matches what you asked for (full-text search score)
  expiring   uses things about to go bad
  taste      fits what you've cooked and liked (intelligence/taste.py)
  goal       protein per serving, when you ask for protein
Allergies are a hard filter; dislikes are a penalty. Every match carries
human-readable reasons so the UI can say *why* it was suggested.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from intelligence import taste
from intelligence.expiry import days_until
from inventory import events as inv_events
from inventory.database import Database
from recipes.ingredients import allergen_hits, canonical, is_staple, matches
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

# Rough grams per unit, for subtracting what a recipe used from the fridge.
UNIT_GRAMS = {
    "cup": 200, "cups": 200, "c": 200, "tablespoon": 15, "tablespoons": 15, "tbsp": 15, "teaspoon": 5,
    "teaspoons": 5, "tsp": 5, "oz": 28, "ounce": 28, "ounces": 28, "lb": 454, "lbs": 454, "pound": 454,
    "pounds": 454, "g": 1, "gram": 1, "grams": 1, "kg": 1000, "ml": 1, "l": 1000, "liter": 1000,
    "can": 400, "cans": 400, "package": 300, "packages": 300, "clove": 5, "cloves": 5, "slice": 30,
    "slices": 30, "stick": 113, "sticks": 113, "pinch": 1, "dash": 1,
}
DEFAULT_PIECE_G = 100


@dataclass
class Match:
    recipe: Recipe
    have: list[str] = field(default_factory=list)       # recipe ingredient names you have
    missing: list[str] = field(default_factory=list)    # still missing after swaps
    swaps: list[Swap] = field(default_factory=list)
    uses_expiring: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class Pantry:
    """What you have right now, keyed by canonical name."""
    items: dict[str, str]                 # canonical -> display name
    expiring: dict[str, int]              # canonical -> days until expiry (only soon ones)
    item_rows: dict[str, list] = field(default_factory=dict)  # canonical -> active item rows


def display_name(name: str) -> str:
    """'chicken stock (from pressure cooker recipe)' -> 'chicken stock'; 'onion, chopped' -> 'onion'."""
    tidy = re.sub(r"\s*\([^)]*\)?", "", name).split(",")[0].strip()
    return tidy or name


def quantity_to_grams(quantity: str | None, unit: str | None) -> float:
    """'1 1/2' cups -> 300 g. Rough on purpose: only used to subtract stock."""
    amount = 1.0
    if quantity:
        q = str(quantity).split("-")[0].strip()  # "2-3" -> "2"
        total = 0.0
        for part in q.split():
            try:
                if "/" in part:
                    num, den = part.split("/", 1)
                    total += float(num) / float(den)
                else:
                    total += float(part)
            except (ValueError, ZeroDivisionError):
                continue
        amount = total or 1.0
    per = UNIT_GRAMS.get((unit or "").strip().lower().rstrip("."), DEFAULT_PIECE_G)
    return amount * per


class RecipeEngine:
    def __init__(self, db: Database, store: RecipeStore):
        self.db = db
        self.store = store

    # -------------------------------------------------------------- pantry
    def pantry(self) -> Pantry:
        items: dict[str, str] = {}
        expiring: dict[str, int] = {}
        rows: dict[str, list] = {}
        for item in self.db.active_items():
            product = self.db.get_product(item["product_id"])
            # An active item at 0 g was never weighed (camera-only, or off the scale) — it's still here.
            # Used-up items don't reach this loop: consuming to 0 marks them removed.
            if product is None:
                continue
            canon = canonical(product["name"])
            if not canon:
                continue
            items.setdefault(canon, product["name"])
            rows.setdefault(canon, []).append(item)
            if item["expiration_date"]:
                d = days_until(item["expiration_date"])
                if d <= EXPIRING_WITHIN_DAYS:
                    expiring[canon] = min(d, expiring.get(canon, d))
        return Pantry(items, expiring, rows)

    def _have(self, ingredient: str, pantry: Pantry) -> str | None:
        """Canonical pantry name that satisfies this recipe ingredient, if any."""
        for have in pantry.items:
            if matches(ingredient, have):
                return have
        return None

    def analyze(self, recipe: Recipe, pantry: Pantry) -> Match:
        m = Match(recipe)
        seen: set[str] = set()
        for ing in recipe.ingredients:
            canon = ing.get("canon") or canonical(ing["name"])
            if not canon or is_staple(canon) or canon in seen:  # some recipes list an ingredient twice
                continue
            seen.add(canon)
            have = self._have(canon, pantry)
            if have:
                m.have.append(display_name(ing["name"]))
                if have in pantry.expiring:
                    m.uses_expiring.append(pantry.items[have])
                continue
            swap = find_swap(canon, pantry.items)
            if swap:
                m.swaps.append(swap)
            else:
                m.missing.append(display_name(ing["name"]))
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
    ) -> list[Match]:
        pantry = self.pantry()
        profile = self.db.get_profile()
        allergies = json.loads(profile["allergies"] or "[]")
        dislikes = [d.lower() for d in json.loads(profile["dislikes"] or "[]")]
        prefs = taste.profile(self.db)

        search_text = query
        if not query and not cuisine:
            # "What can I make?" — search by what you have, things about to expire first.
            ordered = sorted(pantry.items, key=lambda c: (c not in pantry.expiring, c))
            search_text = " ".join(ordered[:12])

        hits = self.store.search(search_text, cuisine, max_minutes, CANDIDATES)
        if len(hits) < limit and query and cuisine:  # too narrow — keep the cuisine, drop the free text
            seen = {i for i, _ in hits}
            hits += [(i, r * 0.5) for i, r in self.store.search(None, cuisine, max_minutes, CANDIDATES) if i not in seen]
        relevance = dict(hits)

        matches_: list[Match] = []
        for recipe in self.store.get_many([i for i, _ in hits]):
            names = [i["name"] for i in recipe.ingredients]
            if allergen_hits(names, allergies):
                continue  # hard filter, never shown
            m = self.analyze(recipe, pantry)
            if must_have_all and m.missing:
                continue
            needed = max(len(m.have) + len(m.swaps) + len(m.missing), 1)
            coverage = (len(m.have) + 0.8 * len(m.swaps)) / needed
            expiring = min(len(m.uses_expiring), 2) / 2
            affinity = taste.recipe_affinity(prefs, recipe)
            protein = recipe.nutrition.get("protein_g")
            if high_protein:
                goal = min(max(((protein or 0) - PROTEIN_FLOOR_G) / (PROTEIN_TARGET_G - PROTEIN_FLOOR_G), 0.0), 1.0)
            else:
                goal = 0.5
            disliked = any(d and d in n.lower() for d in dislikes for n in names)

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
                - (0.25 if disliked else 0.0)
                + (PHOTO_TIEBREAK if recipe.image_url else 0.0)
            )
            m.reasons = self._reasons(m, coverage, affinity, protein, high_protein, pantry)
            matches_.append(m)

        matches_.sort(key=lambda m: m.score, reverse=True)
        return matches_[:limit]

    @staticmethod
    def _reasons(m: Match, coverage: float, affinity: float, protein: float | None,
                 high_protein: bool, pantry: Pantry) -> list[str]:
        reasons = []
        if m.uses_expiring:
            reasons.append("Uses your " + ", ".join(m.uses_expiring[:2]) + " before it goes bad")
        total = len(m.have) + len(m.swaps) + len(m.missing)
        if total:
            reasons.append(f"You have {len(m.have) + len(m.swaps)} of {total} ingredients")
        if high_protein and protein:
            reasons.append(f"{protein:.0f} g protein per serving")
        if affinity > 0.2 and m.recipe.cuisine:
            reasons.append(f"You've been enjoying {m.recipe.cuisine.replace('-', ' ')} food")
        return reasons

    # ------------------------------------------------------- one recipe
    def adapted(self, recipe_id: int) -> dict | None:
        """Full recipe with each ingredient marked have / swap / missing, and swaps
        applied to the steps — ready to cook from."""
        recipe = self.store.get(recipe_id)
        if recipe is None:
            return None
        pantry = self.pantry()
        m = self.analyze(recipe, pantry)
        swap_for = {s.missing: s for s in m.swaps}
        lines = []
        for ing in recipe.ingredients:
            canon = ing.get("canon") or canonical(ing["name"])
            amount = " ".join(str(x) for x in (ing.get("quantity"), ing.get("unit")) if x)
            line = {"name": display_name(ing["name"]), "amount": amount or None}
            if not canon or is_staple(canon):
                line["status"] = "staple"
            elif canon in swap_for:
                line.update(status="swap", use=swap_for[canon].use, note=swap_for[canon].note)
            elif line["name"] in m.missing:
                line["status"] = "missing"
            else:
                line["status"] = "have"
            lines.append(line)

        steps = list(recipe.steps)
        for s in m.swaps:
            pattern = re.compile(rf"\b{re.escape(s.missing)}\w*", re.I)
            steps = [pattern.sub(s.use.lower(), step) for step in steps]

        return {**card(m), "ingredients": lines, "steps": steps, "description": recipe.description}

    # ------------------------------------------------------- "I made this"
    def cooked(self, recipe_id: int, servings_eaten: float = 1.0) -> dict | None:
        """Subtract what the recipe used from the fridge/pantry, log the meal you ate,
        and teach the taste profile."""
        recipe = self.store.get(recipe_id)
        if recipe is None:
            return None
        pantry = self.pantry()
        used: list[dict] = []
        for ing in recipe.ingredients:
            canon = ing.get("canon") or canonical(ing["name"])
            if not canon or is_staple(canon):
                continue
            have = self._have(canon, pantry)
            if have is None:
                swap = find_swap(canon, pantry.items)
                have = next((c for c, d in pantry.items.items() if swap and d == swap.use), None)
            if have is None:
                continue
            remaining = quantity_to_grams(ing.get("quantity"), ing.get("unit"))
            for item in pantry.item_rows.get(have, []):
                take = min(item["grams"], remaining)
                if take > 0:
                    inv_events.apply_consume(self.db, item["id"], take)
                    used.append({"item": pantry.items[have], "grams": round(take)})
                    remaining -= take
                if remaining <= 0:
                    break

        n = recipe.nutrition
        self.db.log_meal(
            recipe.name, servings_eaten,
            *(n.get(k) * servings_eaten if n.get(k) is not None else None
              for k in ("calories", "protein_g", "carbs_g", "fat_g")),
            source="recipe",
        )
        taste.record_recipe(self.db, "cooked", recipe)
        return {"recipe": recipe.name, "used": used, "servings_eaten": servings_eaten}

    def rate(self, recipe_id: int, liked: bool) -> bool:
        recipe = self.store.get(recipe_id)
        if recipe is None:
            return False
        taste.record_recipe(self.db, "liked" if liked else "disliked", recipe)
        return True


def card(m: Match) -> dict:
    """Compact JSON for recipe cards in chat and on the fridge screen."""
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
        "missing": m.missing,
        "swaps": [{"missing": s.missing, "use": s.use, "note": s.note} for s in m.swaps],
        "uses_expiring": m.uses_expiring,
        "reasons": m.reasons,
    }
