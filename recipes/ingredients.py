"""Turn messy ingredient text into comparable names, and decide what you have.

Recipes say "2 cups chopped fresh baby spinach"; the fridge says "Baby Spinach".
Both canonicalize to "spinach" so they can be matched with plain code.
"""
from __future__ import annotations

import re

# Assumed to be in every kitchen — never counted as "missing".
PANTRY_STAPLES = {
    "salt", "pepper", "black pepper", "water", "oil", "olive oil", "vegetable oil", "canola oil",
    "cooking spray", "sugar", "flour", "all-purpose flour", "baking soda", "baking powder",
    "garlic powder", "onion powder", "paprika", "cumin", "chili powder", "oregano", "dried oregano",
    "cinnamon", "vanilla", "vanilla extract", "red pepper flake", "ice", "nutmeg", "bay",
    "dried basil", "dried thyme", "italian seasoning", "soy sauce", "vinegar", "cornstarch",
    # Aromatics nearly every kitchen keeps on the counter, and the fridge doesn't track.
    "garlic", "onion", "yellow onion", "white onion", "brown sugar", "honey", "ketchup", "mustard",
}
SEASONING_WORDS = {"salt", "pepper", "black", "white", "kosher", "sea", "seasoning", "season"}

# Words that describe preparation or size, not what the ingredient is.
DESCRIPTORS = {
    "fresh", "freshly", "chopped", "minced", "diced", "sliced", "grated", "shredded", "ground",
    "large", "small", "medium", "extra", "virgin", "boneless", "skinless", "finely", "coarsely",
    "thinly", "crushed", "dried", "frozen", "canned", "cooked", "uncooked", "raw", "whole", "baby",
    "lean", "low-fat", "lowfat", "fat-free", "nonfat", "reduced-fat", "light", "organic", "plain",
    "unsalted", "salted", "softened", "melted", "cold", "warm", "hot", "ripe", "peeled", "seeded",
    "halved", "quartered", "cubed", "trimmed", "rinsed", "drained", "packed", "heaping", "optional",
    "of", "and", "or", "to", "taste", "for", "garnish", "about", "into", "pieces", "piece", "inch",
    "inches", "wide", "thick", "long", "cut", "room", "temperature", "divided", "more", "needed",
    "plus", "preferably", "very", "good", "quality", "store", "bought", "homemade", "prepared",
    "leaf", "leaves", "sprig", "sprigs", "stalk", "stalks", "florets", "floret",
}
# "ground" is a descriptor for spices but identity for meat — keep it there.
KEEP_GROUND_FOR = {"beef", "turkey", "pork", "chicken", "lamb", "meat"}

UNITS = {
    "cup", "cups", "tablespoon", "tablespoons", "tbsp", "teaspoon", "teaspoons", "tsp", "oz",
    "ounce", "ounces", "lb", "lbs", "pound", "pounds", "g", "gram", "grams", "kg", "ml", "l",
    "liter", "can", "cans", "package", "packages", "pkg", "clove", "cloves", "pinch", "dash",
    "slice", "slices", "stick", "sticks", "bunch", "head", "jar", "bottle", "quart", "pint",
}

IRREGULAR_SINGULAR = {
    "tomatoes": "tomato", "potatoes": "potato", "leaves": "leaf", "berries": "berry",
    "cherries": "cherry", "anchovies": "anchovy", "chilies": "chili", "chiles": "chile",
    "radishes": "radish", "peaches": "peach", "knives": "knife",
}
NO_SINGULAR = {"hummus", "couscous", "asparagus", "molasses", "swiss", "brussels", "grass", "lettuce"}


def _singular(word: str) -> str:
    if word in IRREGULAR_SINGULAR:
        return IRREGULAR_SINGULAR[word]
    if word in NO_SINGULAR or len(word) <= 3:
        return word
    if word.endswith("ies"):
        return word[:-3] + "y"
    if word.endswith("oes"):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def canonical(text: str) -> str:
    """'2 cups chopped fresh baby spinach' -> 'spinach'; 'Ground Beef' -> 'ground beef'."""
    text = text.lower()
    text = re.sub(r"\(.*?(\)|$)", " ", text)       # "(15 ounce)" asides, even unclosed ones
    text = text.split(",")[0]                         # "onion, chopped" -> "onion"
    words = re.findall(r"[a-z][a-z\-']*", text)
    keep_ground = any(w in KEEP_GROUND_FOR for w in words)
    out = []
    for w in words:
        if w in UNITS:
            continue
        if w in DESCRIPTORS and not (w == "ground" and keep_ground):
            continue
        # "inch-wide", "extra-large": every part is a measurement/description word.
        # (Real hyphenated ingredients like "half-and-half" or "all-purpose" keep a non-descriptor part.)
        parts = [p for p in w.split("-") if p]
        if len(parts) > 1 and all(p in DESCRIPTORS or p in UNITS for p in parts):
            continue
        out.append(_singular(w))
    return " ".join(out).strip()


def head(name: str) -> str:
    """Last word — the noun in most ingredient names ('greek yogurt' -> 'yogurt')."""
    parts = name.split()
    return parts[-1] if parts else ""


def is_staple(name: str) -> bool:
    # Suffix rule catches "kosher salt", "sesame oil"; deliberately not "pepper" (bell pepper isn't a
    # staple) — but "salt pepper" (from "salt and pepper") is all seasoning words, so it is.
    words = name.split()
    return (name in PANTRY_STAPLES or head(name) in {"salt", "oil"}
            or bool(words) and set(words) <= SEASONING_WORDS and ("salt" in words or "pepper" in words))


COOKING_LIQUID = re.compile(r"\b(reserved|cooking liquid|cooking water|from the pasta|pasta water)\b", re.I)
PLAIN_WATER_WORDS = {"boiling", "lukewarm", "filtered", "tap", "cool", "fluid", "pure", "bottled", "ice"}


def needs_no_badge(raw_name: str, canon: str) -> bool:
    """Staples, plus water, ice and cooking liquid ('water from the pasta'): nothing to have or buy.
    Rose water and coconut water are real ingredients and still count."""
    words = canon.split()
    plain_water = bool(words) and words[-1] == "water" and set(words[:-1]) <= PLAIN_WATER_WORDS
    return (not canon or is_staple(canon) or plain_water or canon == "ice cube"
            or bool(COOKING_LIQUID.search(raw_name)))


def dislike_pattern(dislike: str) -> re.Pattern | None:
    """'mushrooms' -> matches 'mushroom', 'mushrooms', 'cream of mushroom soup'."""
    words = re.findall(r"[a-z][a-z\-']*", dislike.lower())
    if not words:
        return None
    last = _singular(words[-1])
    ending = "(s|es)?"
    if re.search(r"[^aeiou]y$", last):
        last, ending = last[:-1], "(y|ies)"
    phrase = r"\s+".join(re.escape(w) for w in [*words[:-1], last])
    return re.compile(rf"\b{phrase}{ending}\b", re.I)


# A one-word ingredient also matches these more specific forms: 'chicken' ~ 'chicken thigh',
# 'cheddar' ~ 'cheddar cheese'. Anything else ('chicken broth') is a different ingredient.
SPECIFIC_FORMS = {"breast", "thigh", "leg", "drumstick", "wing", "tenderloin", "fillet", "steak", "cheese"}

# Same head noun, and the only extra words describe it: 'greek yogurt' is yogurt. Any other
# extra word is a different food: 'peanut butter' is not butter, 'almond milk' is not milk.
MATCH_DESCRIPTORS = {
    "greek", "plain", "whole", "skim", "low-fat", "nonfat", "fat-free", "unsalted", "salted", "sweet",
    "fresh", "frozen", "large", "small", "boneless", "skinless", "shredded", "grated", "sharp", "mild",
    "light", "heavy",
}


def matches(recipe_ingredient: str, inventory_name: str) -> bool:
    """Does an item you have satisfy a recipe ingredient? Both already canonical."""
    if not recipe_ingredient or not inventory_name:
        return False
    if recipe_ingredient == inventory_name:
        return True
    r, i = recipe_ingredient.split(), inventory_name.split()
    small, large = (r, i) if len(r) <= len(i) else (i, r)
    if not set(small) <= set(large):
        return False
    extra = set(large) - set(small)
    if head(recipe_ingredient) == head(inventory_name):
        return extra <= MATCH_DESCRIPTORS
    return len(small) == 1 and len(extra) == 1 and extra <= SPECIFIC_FORMS


# Allergy keywords -> ingredient words that contain that allergen. Allergies are a
# hard filter in code, never left to the AI.
ALLERGEN_TERMS: dict[str, set[str]] = {
    "peanut": {"peanut", "peanuts", "peanut butter"},
    "tree nut": {"almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut", "macadamia", "pine nut"},
    "nut": {"peanut", "almond", "walnut", "pecan", "cashew", "pistachio", "hazelnut", "macadamia", "pine nut"},
    "dairy": {"milk", "buttermilk", "cheese", "butter", "cream", "yogurt", "parmesan", "mozzarella", "cheddar", "ricotta", "whey", "ghee"},
    "milk": {"milk", "buttermilk", "cheese", "butter", "cream", "yogurt", "parmesan", "mozzarella", "cheddar", "ricotta", "whey", "ghee"},
    "egg": {"egg", "mayonnaise"},
    "gluten": {"flour", "bread", "pasta", "spaghetti", "noodle", "wheat", "barley", "breadcrumb", "tortilla", "couscous", "cracker"},
    "wheat": {"flour", "bread", "pasta", "spaghetti", "noodle", "wheat", "breadcrumb", "tortilla", "couscous", "cracker"},
    "shellfish": {"shrimp", "crab", "lobster", "prawn", "scallop", "clam", "mussel", "oyster"},
    "fish": {"salmon", "tuna", "cod", "tilapia", "anchovy", "halibut", "trout", "fish"},
    "soy": {"soy", "tofu", "edamame", "tempeh", "miso"},
    "sesame": {"sesame", "tahini"},
}


def _word_pattern(term: str) -> re.Pattern:
    """Whole words, plurals included: 'egg' finds 'eggs' but not 'eggplant'."""
    if re.search(r"[^aeiou]y$", term):
        stem, ending = re.escape(term[:-1]), "(y|ies)"
    else:
        stem, ending = re.escape(term), "(s|es)?"
    return re.compile(rf"\b{stem}{ending}\b", re.I)


def allergen_found(text: str, allergies: list[str]) -> tuple[str, str] | None:
    """(allergy as the person wrote it, the word in `text` that conflicts), or None."""
    for allergy in allergies:
        a = allergy.strip().lower()
        key = a.rstrip("s")
        terms = ALLERGEN_TERMS.get(key, set()) | {key}
        for term in sorted(terms, key=len, reverse=True):
            if term and (m := _word_pattern(term).search(text)):
                return a, m.group(0).lower()
    return None


def allergen_hits(texts: list[str], allergies: list[str]) -> list[str]:
    """Ingredient lines (or titles, steps) that conflict with any allergy."""
    return [t for t in texts if allergen_found(t, allergies)]
