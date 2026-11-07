import json

import pytest

from intelligence import taste
from intelligence.grocery import unlock_suggestions
from inventory import events as inv_events
from recipes.engine import RecipeEngine, quantity_to_grams
from recipes.ingredients import allergen_hits, canonical, is_staple, matches
from recipes.store import RecipeStore, build_match
from recipes.substitutions import find_swap


# ------------------------------------------------------------ ingredients
@pytest.mark.parametrize("raw, canon", [
    ("2 cups chopped fresh baby spinach", "spinach"),
    ("1 lb boneless skinless chicken breasts", "chicken breast"),
    ("1 lb ground beef", "ground beef"),
    ("1 tsp ground cumin", "cumin"),
    ("3 large eggs", "egg"),
    ("2 (15 ounce) cans black beans, drained", "black bean"),
    ("Roma tomatoes", "roma tomato"),
    ("2 cups fresh spinach leaves", "spinach"),
    ("6-inch-wide pita bread", "pita bread"),
])
def test_canonical(raw, canon):
    assert canonical(raw) == canon


@pytest.mark.parametrize("recipe, have, ok", [
    ("spinach", "spinach", True),
    ("yogurt", "greek yogurt", True),
    ("cheddar", "cheddar cheese", True),
    ("chicken", "chicken breast", True),
    ("chicken broth", "chicken breast", False),
    ("orange juice", "orange", False),
    ("bell pepper", "black pepper", False),
])
def test_matches(recipe, have, ok):
    assert matches(recipe, have) is ok


def test_staples_but_not_bell_pepper():
    assert is_staple("kosher salt") and is_staple("olive oil") and is_staple("black pepper")
    assert not is_staple("bell pepper")


def test_allergens_use_synonyms():
    assert allergen_hits(["sliced almonds", "spinach"], ["nuts"]) == ["sliced almonds"]
    assert allergen_hits(["parmesan cheese"], ["dairy"]) == ["parmesan cheese"]
    assert allergen_hits(["spinach"], ["dairy", "nuts"]) == []


def test_swaps_are_noted_and_never_for_things_you_have():
    swap = find_swap("basil", {"parsley": "Parsley", "milk": "Milk"})
    assert swap and swap.use == "Parsley" and swap.note
    assert find_swap("spinach", {"spinach": "Baby Spinach"}) is None
    assert find_swap("saffron", {"milk": "Milk"}) is None


@pytest.mark.parametrize("qty, unit, grams", [("1 1/2", "cups", 300), ("2", None, 200), ("1/4", "tsp", 1.25), ("2-3", "tbsp", 30)])
def test_quantity_to_grams(qty, unit, grams):
    assert quantity_to_grams(qty, unit) == pytest.approx(grams)


def test_match_expression_is_safe_for_odd_input():
    assert build_match('"; DROP TABLE recipes; --', None) == '("drop"* OR "table"* OR "recipes"*)'
    assert build_match(None, None) is None


# ----------------------------------------------------------------- engine
def _recipe(rid, name, cuisine, ingredients, protein=20, tags=("main-dish",)):
    return {
        "id": rid, "name": name, "cuisine": cuisine, "minutes": 30, "servings": 2, "calories": 400,
        "protein_g": protein, "fat_g": 10, "carbs_g": 40, "fiber_g": 3, "sugar_g": 5, "sodium_mg": 300,
        "image_url": None, "description": None, "tags": list(tags) + ([cuisine] if cuisine else []),
        "ingredients": [{"name": n, "canon": canonical(n), "quantity": "1", "unit": "cup"} for n in ingredients],
        "steps": [f"Cook the {ingredients[0]}.", "Serve."],
    }


@pytest.fixture
def engine(db, tmp_path):
    store = RecipeStore(tmp_path / "recipes.db")
    for r in [
        _recipe(1, "Spinach Pesto Pasta", "italian", ["spaghetti", "basil", "spinach", "parmesan cheese", "olive oil"], protein=18),
        _recipe(2, "Chicken Parmesan", "italian", ["chicken breast", "mozzarella cheese", "tomato sauce", "flour"], protein=45),
        _recipe(3, "Almond Cake", "italian", ["almonds", "flour", "sugar", "eggs"], protein=8, tags=("dessert",)),
        _recipe(4, "Chicken Tacos", "mexican", ["chicken breast", "tortilla", "salsa", "cilantro"], protein=35),
    ]:
        store.add(r)
    store.commit()
    for name, grams, exp in [("Baby Spinach", 150, "2026-01-01"), ("Spaghetti", 500, None),
                             ("Parsley", 30, None), ("Parmesan Cheese", 200, None), ("Chicken Breast", 600, None)]:
        pid = db.get_or_create_product(name)
        inv_events.apply_add(db, pid, grams, expiration_date=exp)
    return RecipeEngine(db, store)


def test_analyze_have_swap_missing(engine):
    m = engine.analyze(engine.store.get(1), engine.pantry())
    assert set(m.have) == {"spaghetti", "spinach", "parmesan cheese"}
    assert [s.missing for s in m.swaps] == ["basil"] and m.swaps[0].use == "Parsley"
    assert m.missing == []
    assert m.uses_expiring == ["Baby Spinach"]


def test_suggest_italian_ranks_what_you_can_make_and_filters_allergens(engine):
    engine.db.update_profile(allergies=["nuts"])
    results = engine.suggest(cuisine="italian")
    names = [m.recipe.name for m in results]
    assert "Almond Cake" not in names                    # allergy is a hard filter
    assert names[0] == "Spinach Pesto Pasta"             # everything on hand (with a swap) + uses expiring spinach
    assert any("before it goes bad" in r for r in results[0].reasons)


def test_high_protein_changes_the_order(engine):
    names = [m.recipe.name for m in engine.suggest(cuisine="italian", high_protein=True)]
    assert names[0] == "Chicken Parmesan"


def test_adapted_recipe_applies_swaps_to_steps(engine):
    r = engine.adapted(1)
    statuses = {line["name"]: line["status"] for line in r["ingredients"]}
    assert statuses == {"spaghetti": "have", "basil": "swap", "spinach": "have", "parmesan cheese": "have", "olive oil": "staple"}
    engine2 = engine.adapted(4)
    assert "salsa" in engine2["missing"] and "tortilla" in engine2["missing"]


def test_cooking_consumes_stock_logs_meal_and_learns_taste(engine):
    before = {i["product_id"]: i["grams"] for i in engine.db.active_items()}
    result = engine.cooked(2, servings_eaten=1)
    assert any(u["item"] == "Chicken Breast" for u in result["used"])
    chicken = engine.db.find_product_by_name("Chicken Breast")["id"]
    after = {i["product_id"]: i["grams"] for i in engine.db.active_items()}
    assert after[chicken] < before[chicken]
    assert engine.db.meals_since("2000-01-01")[-1]["protein_g"] == 45
    assert taste.profile(engine.db).get("recipe:2", 0) > 0


def test_taste_learning_reorders_suggestions(engine):
    for _ in range(3):
        engine.rate(4, liked=True)
        engine.rate(2, liked=False)
    names = [m.recipe.name for m in engine.suggest(query="chicken")]
    assert names[0] == "Chicken Tacos"


def test_unlock_suggestions_name_purchases_that_complete_recipes(engine):
    picks = unlock_suggestions(engine.db, engine)
    bought = [tuple(p.buy) for p in picks]
    assert ("mozzarella cheese", "tomato sauce") in bought or ("salsa", "tortilla") in bought
    assert all(p.unlocks >= 1 and p.examples for p in picks)
