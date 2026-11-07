"""Swap a missing ingredient for a similar one you already have.

Plain-code lookup over groups of interchangeable ingredients. Each group has
a note shown to the user so a swap is never silent ("kale is sturdier — cook
it 2-3 minutes longer"). Gemini may reword the steps around a swap, but which
swaps are allowed is decided here.
"""
from __future__ import annotations

from dataclasses import dataclass

from recipes.ingredients import matches


@dataclass(frozen=True)
class Group:
    members: tuple[str, ...]  # canonical names, closest substitutes listed together
    note: str


GROUPS: list[Group] = [
    Group(("spinach", "kale", "swiss chard", "collard green", "arugula", "beet green"),
          "Sturdier greens like kale or chard need 2-3 extra minutes of cooking."),
    Group(("romaine lettuce", "lettuce", "iceberg lettuce", "mixed green", "spring mix", "arugula"),
          "Any salad green works; arugula is more peppery."),
    Group(("basil", "parsley", "cilantro", "dill", "mint"),
          "Changes the flavor — add soft herbs at the end."),
    Group(("parmesan cheese", "parmesan", "pecorino romano", "romano cheese", "grana padano", "asiago cheese"),
          "Pecorino is saltier — go easy on added salt."),
    Group(("mozzarella cheese", "mozzarella", "provolone cheese", "monterey jack cheese", "fontina cheese", "swiss cheese"),
          "All melt well; flavor will be a little different."),
    Group(("cheddar cheese", "cheddar", "colby cheese", "monterey jack cheese", "colby-jack cheese", "mexican blend cheese"),
          "Milder cheeses melt the same way."),
    Group(("ricotta cheese", "cottage cheese"), "Blend cottage cheese smooth for a ricotta texture."),
    Group(("feta cheese", "goat cheese", "queso fresco"), "All crumbly and tangy."),
    Group(("chicken breast", "chicken thigh", "chicken tender", "turkey breast"),
          "Thighs stay juicier and take a few minutes longer; cook to 165°F / 74°C."),
    Group(("ground beef", "ground turkey", "ground chicken", "ground pork", "ground lamb"),
          "Leaner meats may need a little oil; cook to 160°F / 71°C (165°F for poultry)."),
    Group(("pork chop", "pork tenderloin", "pork loin"), "Adjust cooking time to thickness; cook to 145°F / 63°C."),
    Group(("shrimp", "scallop", "prawn"), "Cook just until opaque."),
    Group(("salmon", "trout", "arctic char"), "Similar oily fish; cook to 145°F / 63°C."),
    Group(("cod", "tilapia", "halibut", "haddock", "pollock", "white fish"), "Mild white fish cook about the same."),
    Group(("onion", "yellow onion", "white onion", "red onion", "sweet onion", "shallot", "leek"),
          "Shallots are milder; use a bit more."),
    Group(("green onion", "scallion", "chive"), "Chives are milder; add at the end."),
    Group(("lemon juice", "lime juice", "lemon", "lime"), "Lime is a little more floral."),
    Group(("white wine vinegar", "red wine vinegar", "apple cider vinegar", "rice vinegar", "champagne vinegar"),
          "Any light vinegar works."),
    Group(("heavy cream", "whipping cream", "half-and-half", "light cream"),
          "Half-and-half won't whip and may split if boiled hard."),
    Group(("greek yogurt", "yogurt", "sour cream", "creme fraiche"), "Greek yogurt is tangier and leaner."),
    Group(("milk", "skim milk", "almond milk", "oat milk", "soy milk"), "Plant milks are a little less rich."),
    Group(("butter", "margarine"), "Works the same for cooking."),
    Group(("spaghetti", "linguine", "fettuccine", "angel hair pasta", "bucatini"), "Long pastas swap freely."),
    Group(("penne", "rigatoni", "ziti", "fusilli", "rotini", "farfalle", "macaroni", "pasta", "elbow macaroni"),
          "Short pastas swap freely; check the package cooking time."),
    Group(("rice", "white rice", "brown rice", "jasmine rice", "basmati rice", "long grain rice"),
          "Brown rice takes about twice as long."),
    Group(("chicken broth", "chicken stock", "vegetable broth", "vegetable stock", "beef broth", "beef stock"),
          "Changes the flavor slightly."),
    Group(("honey", "maple syrup", "agave nectar", "brown sugar"), "Honey and maple are sweeter — use a little less."),
    Group(("black bean", "kidney bean", "pinto bean", "cannellini bean", "great northern bean", "navy bean", "chickpea"),
          "Canned beans swap one for one."),
    Group(("diced tomato", "crushed tomato", "tomato", "stewed tomato", "tomato sauce", "plum tomato", "roma tomato"),
          "Crushed or sauce gives a smoother result."),
    Group(("bell pepper", "red bell pepper", "green bell pepper", "yellow bell pepper", "poblano pepper"),
          "Green is less sweet than red or yellow."),
    Group(("zucchini", "yellow squash", "summer squash"), "Cook the same way."),
    Group(("broccoli", "cauliflower", "broccolini"), "Cauliflower takes a minute or two longer."),
    Group(("potato", "russet potato", "red potato", "yukon gold potato", "sweet potato"),
          "Sweet potatoes cook faster and are sweeter."),
    Group(("tortilla", "flour tortilla", "corn tortilla"), "Corn tortillas are smaller and gluten-free."),
    Group(("mayonnaise", "greek yogurt"), "Yogurt is lighter and tangier."),
]


@dataclass(frozen=True)
class Swap:
    missing: str     # the recipe's ingredient (canonical)
    use: str         # what you have (display name)
    note: str


def _groups_for(name: str) -> list[Group]:
    return [g for g in GROUPS if any(matches(name, m) for m in g.members)]


def find_swap(missing: str, available: dict[str, str]) -> Swap | None:
    """`missing` is canonical; `available` maps canonical name -> display name of things you have."""
    for group in _groups_for(missing):
        for have_canon, have_display in available.items():
            if matches(missing, have_canon):
                continue  # not missing at all
            if any(matches(have_canon, m) for m in group.members):
                return Swap(missing, have_display, group.note)
    return None


def similar_to(name: str) -> list[str]:
    """Everything in the same groups — used to widen recipe searches."""
    out: list[str] = []
    for g in _groups_for(name):
        out.extend(m for m in g.members if m != name and m not in out)
    return out
