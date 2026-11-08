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
SEASONING_WORDS = {"salt", "pepper", "black", "white", "kosher", "sea", "seasoning", "season",
                   "coarse", "cracked", "fresh", "ground"}
# Dried spices and herbs: pantry when measured by the spoon, pinch or dash (or not measured at all).
# "2 cups fresh basil" is still something to buy.
SPICES = {
    "turmeric", "thyme", "rosemary", "sage", "basil", "oregano", "marjoram", "tarragon", "dill weed", "cayenne",
    "coriander", "cardamom", "cloves", "allspice", "curry powder", "garam masala", "chili flakes",
    "smoked paprika", "ground ginger", "mustard powder", "celery seed", "fennel seed",
}
SPICE_UNITS = {"tsp", "teaspoon", "teaspoons", "tbsp", "tablespoon", "tablespoons", "pinch", "pinches",
               "dash", "dashes"}

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


# Foods the assistant might name, to catch a sentence about an ingredient no shown card uses.
COMMON_FOODS = {
    "feta", "parmesan", "mozzarella", "cheddar", "ricotta", "goat cheese", "cream cheese", "sour cream", "cream",
    "yogurt", "milk", "butter", "egg", "tofu", "tempeh", "chicken", "beef", "pork", "lamb", "turkey", "bacon",
    "sausage", "ham", "salmon", "tuna", "cod", "shrimp", "scallop", "crab", "anchovy", "chickpea", "lentil",
    "black bean", "kidney bean", "bean", "rice", "quinoa", "pasta", "noodle", "couscous", "bread", "tortilla",
    "potato", "sweet potato", "tomato", "sun-dried tomato", "spinach", "kale", "lettuce", "arugula", "cabbage",
    "broccoli", "cauliflower", "carrot", "celery", "cucumber", "zucchini", "eggplant", "mushroom", "bell pepper",
    "jalapeno", "chile", "corn", "pea", "green bean", "asparagus", "avocado", "olive", "caper", "artichoke",
    "lemon", "lime", "orange", "apple", "pineapple", "mango", "banana", "berry", "strawberry", "blueberry",
    "raisin", "cranberry", "walnut", "almond", "pecan", "cashew", "peanut", "pine nut", "sesame", "coconut",
    "coconut milk", "ginger", "garlic", "shallot", "scallion", "green onion", "leek", "cilantro", "parsley",
    "mint", "dill", "chive", "adobo", "creole seasoning", "cajun seasoning", "salsa", "pesto", "hummus", "tahini",
    "miso", "honey", "maple syrup", "mustard", "mayonnaise", "ketchup", "hot sauce", "sriracha", "teriyaki sauce",
    "worcestershire sauce", "fish sauce", "oyster sauce", "hoisin sauce", "wine", "beer", "broth",
}


def sentence_words(text: str) -> str:
    """'Sun-dried Tomatoes, feta.' -> 'sun-dried tomato feta': lower case, singular, for phrase lookups."""
    return " ".join(_singular(w) for w in re.findall(r"[a-z][a-z\-']*", text.lower()))


def food_terms() -> set[str]:
    return COMMON_FOODS | _SPICE_FORMS | {s for s in PANTRY_STAPLES if s not in {"water", "ice"}}


def raw_words(name: str) -> str:
    """The ingredient as written, minus amounts and asides, descriptors kept: 'dried thyme leaves'."""
    text = re.sub(r"\(.*?(\)|$)", " ", name.lower()).split(",")[0]
    return " ".join(_singular(w) for w in re.findall(r"[a-z][a-z\-']*", text) if w not in UNITS)


def _has_phrase(phrase: str, text: str) -> bool:
    return bool(re.search(rf"\b{re.escape(phrase)}\b", text))


_SPICE_FORMS = {" ".join(_singular(w) for w in s.split()) for s in SPICES}
_STAPLE_PHRASES = [s for s in PANTRY_STAPLES if " " in s]


def is_spoon_spice(raw_name: str, canon: str, unit: str | None = None, quantity: str | None = None) -> bool:
    """'1 tsp turmeric', 'dried thyme' (no amount): pantry. '2 cups fresh basil': not."""
    raw = raw_words(raw_name)
    if not (canon in _SPICE_FORMS or any(_has_phrase(s, raw) for s in _SPICE_FORMS)):
        return False
    u = (unit or "").strip().lower().rstrip(".")
    return u in SPICE_UNITS or not (u or str(quantity or "").strip())


def needs_no_badge(raw_name: str, canon: str, unit: str | None = None, quantity: str | None = None) -> bool:
    """Staples (matched on the name as written too, so 'dried basil' counts before 'dried' is
    stripped), spoon-measured spices, plus water, ice and cooking liquid ('water from the pasta'):
    nothing to have or buy. Rose water and coconut water are real ingredients and still count."""
    words = canon.split()
    plain_water = bool(words) and words[-1] == "water" and set(words[:-1]) <= PLAIN_WATER_WORDS
    raw = raw_words(raw_name)
    return (not canon or is_staple(canon) or plain_water or canon == "ice cube"
            or bool(COOKING_LIQUID.search(raw_name))
            or any(_has_phrase(s, raw) for s in _STAPLE_PHRASES)
            or is_spoon_spice(raw_name, canon, unit, quantity))


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
    "light", "heavy", "leftover", "quick-cooking",
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


# Foods made from an allergen, which don't say so in their name: teriyaki is soy sauce.
_SOY_FOODS = {"soya", "soy sauce", "soybean", "tamari", "shoyu", "teriyaki", "hoisin", "ponzu", "natto", "lecithin"}
_GLUTEN_FOODS = {"soy sauce", "teriyaki", "panko", "seitan", "beer", "bulgur", "semolina", "farro"}
_DAIRY_FOODS = {"half-and-half", "sour cream", "casein", "custard"}
MADE_FROM: dict[str, set[str]] = {
    "dairy": _DAIRY_FOODS,
    "milk": _DAIRY_FOODS,
    "egg": {"aioli", "meringue"},
    "gluten": _GLUTEN_FOODS | {"rye"},
    "wheat": _GLUTEN_FOODS,
    "fish": {"fish sauce", "worcestershire", "anchovy", "caesar"},
    "soy": _SOY_FOODS,
}

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
for _allergy, _foods in MADE_FROM.items():
    ALLERGEN_TERMS[_allergy] |= _foods


# Someone allergic to one tree nut can't eat "1 cup nuts" or "add the nuts" either.
TREE_NUTS = {"walnut", "pecan", "almond", "cashew", "hazelnut", "pistachio", "macadamia", "tree nut"}


def allergy_terms(allergy: str) -> set[str]:
    key = allergy.strip().lower().rstrip("s")
    terms = ALLERGEN_TERMS.get(key, set()) | {key}
    return terms | {"nut"} if key in TREE_NUTS else terms


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
        for term in sorted(allergy_terms(a), key=len, reverse=True):
            if term and (m := _word_pattern(term).search(text)):
                return a, m.group(0).lower()
    return None


def allergen_hits(texts: list[str], allergies: list[str]) -> list[str]:
    """Ingredient lines (or titles, steps) that conflict with any allergy."""
    return [t for t in texts if allergen_found(t, allergies)]


def made_from(food: str, allergy: str) -> bool:
    """'teriyaki' is made from soy; 'tofu' is soy itself, and 'shrimp' a kind of shellfish."""
    key = allergy.strip().lower().rstrip("s")
    return _singular(food.lower()) in MADE_FROM.get(key, set())


# Single-use or pricey things a "cheap" ask never sends you out to buy.
SPECIALTY = {"berbere", "saffron", "truffle", "pine nut", "dripping", "chorizo", "prosciutto", "lobster", "crab",
             "scallop", "vanilla bean", "sumac", "mascarpone"}


def is_specialty(name: str) -> bool:
    return any(_word_pattern(term).search(name) for term in SPECIALTY)


_ALTERNATIVE_SPLIT = re.compile(r"\s+or\s+|(?<=[a-z])\s*/\s*(?=[a-z])", re.I)


def _without_amount(text: str) -> str:
    """'4 cups leftover cooked rice' -> 'leftover cooked rice'."""
    words = text.split()
    while words and re.fullmatch(r"[\d/.\-]+", words[0]):
        words.pop(0)
    if len(words) > 1 and words[0].lower().rstrip(".") in UNITS:
        words.pop(0)
    return " ".join(words)


def alternatives(name: str) -> list[str]:
    """'margarine or 1/4 cup butter' -> ['margarine', 'butter']; just [name] when there's no choice."""
    text = re.sub(r"\(.*?(\)|$)", " ", name).split(",")[0]
    alts = [a for a in (_without_amount(p) for p in _ALTERNATIVE_SPLIT.split(text)) if canonical(a)]
    return alts if len(alts) > 1 else [name]
