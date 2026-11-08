"""Round 6: allergies cover foods made from the allergen on every recipe path, a true no-shopping
answer, "X or Y" ingredients, search by word stems, one grocery row per food, no restocking food
that will be wasted, and budget words as filters."""
from datetime import datetime, timedelta, timezone

import pytest

from intelligence import clock, grocery_list
from intelligence.grocery import grocery_plan, unlock_suggestions, use_first
from intelligence.search import search
from inventory import events as inv_events
from nutrition import chatbot as chatbot_module
from nutrition.chatbot import NutritionistChatbot
from recipes.engine import RecipeEngine, allergens_in
from recipes.ingredients import alternatives, is_specialty
from recipes.store import source_text
from tests.test_goals_and_truth import _add, _dish, _store


def _offline(monkeypatch):
    monkeypatch.setattr(chatbot_module, "make_client", lambda: None)


def _bot(db, engine) -> NutritionistChatbot:
    bot = NutritionistChatbot(db)
    bot._engine = engine
    return bot


def _card_ids(out) -> set[int]:
    return {c["id"] for c in out["recipes"]}


# ------------------------------------------------------------ allergies on every path
@pytest.mark.parametrize("allergy, ingredient", [
    ("soy", "teriyaki sauce"), ("soy", "tamari"), ("gluten", "panko breadcrumbs"), ("fish", "worcestershire sauce"),
    ("dairy", "sour cream"), ("egg", "aioli"),
])
def test_an_allergy_removes_foods_made_from_it_on_every_path(db, tmp_path, monkeypatch, allergy, ingredient):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Glazed Chicken", ["chicken breast", ingredient], protein=40),
        _dish(2, "Lemon Chicken", ["chicken breast", "lemon"], protein=40),
    ]))
    _add(db, "Chicken Breast", 900)
    engine.cooked(1, made=1.0, servings_eaten=1)  # leftovers of the allergen recipe in the fridge
    _add(db, "Chicken Breast", 900)
    bot = _bot(db, engine)
    _offline(monkeypatch)
    assert 1 in [m.recipe.id for m in engine.suggest(automatic=True)]  # the path finds it without the allergy

    db.update_profile(allergies=[allergy])
    assert 1 not in [m.recipe.id for m in engine.suggest(automatic=True)]                 # Cook tonight
    assert all(1 not in u.recipe_ids for u in unlock_suggestions(db, engine))               # One item away
    assert 1 not in _card_ids(bot.chat("chicken dinner ideas"))                             # chat search
    without = bot.chat("What can I make without shopping?")                                 # fallback + leftovers
    assert 1 not in _card_ids(without) and 2 in _card_ids(without)
    assert "leftovers" not in without["reply"].lower()


def test_teriyaki_is_blocked_for_soy_with_a_sentence_from_code(db, tmp_path, monkeypatch):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Teriyaki Chicken", ["chicken breast", "teriyaki sauce"], protein=40),
        _dish(2, "Hoisin Chicken", ["chicken breast", "hoisin sauce"], protein=40),
        _dish(3, "Chicken Stir Fry", ["chicken breast", "broccoli"], protein=40, steps=["Add the tamari.", "Serve."]),
        _dish(4, "Roast Chicken", ["chicken breast", "lemon"], protein=40),
    ]))
    _add(db, "Chicken Breast", 900)
    db.update_profile(allergies=["soy"])
    _offline(monkeypatch)
    out = _bot(db, engine).chat("any teriyaki chicken recipes?")
    assert out["reply"].startswith("You listed soy as an allergy, and teriyaki is made with soy, so I won't suggest it.")
    assert _card_ids(out) == {4}


def test_the_recipe_page_names_the_allergen_line(db, tmp_path):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Rice, Spinach and Spicy Chickpeas", ["brown rice", "soy sauce"], protein=12),
    ]))
    assert engine.adapted(1)["allergens"] == []
    db.update_profile(allergies=["soy"])
    page = engine.adapted(1)
    assert page["allergens"] == [{"allergy": "soy", "lines": ["1 cup soy sauce"]}]
    assert [line.get("allergy") for line in page["ingredients"]] == [None, "soy"]
    assert allergens_in(engine.store.get(1), ["dairy"]) == []


# ------------------------------------------------------------ a true no-shopping answer
def test_source_escapes_are_decoded():
    assert source_text(r"salt & pepper") == "salt & pepper"
    assert source_text("Mac &amp; Cheese") == "Mac & Cheese"


def test_no_shopping_lists_recipes_with_nothing_to_buy_first(db, tmp_path, monkeypatch):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Salmon Bake", ["salmon fillet", "lemon"], protein=35),
        _dish(2, "Plain Chicken", ["chicken breast", "salt & pepper"], protein=35),
    ]))
    _add(db, "Chicken Breast", 600)
    _offline(monkeypatch)
    out = _bot(db, engine).chat("salmon without shopping")
    assert out["reply"] == "These use only what you have."
    assert _card_ids(out) == {2} and out["recipes"][0]["missing"] == []


# ------------------------------------------------------------ "X or Y"
@pytest.mark.parametrize("line, quantity, unit, product, grams", [
    ("margarine or 1/4 cup butter", "1/4", "cup", "Butter", 132),
    ("quick-cooking rice or 4 cups leftover cooked rice", "2", "cups", "Rice", 534),
])
def test_either_alternative_on_hand_is_have(db, tmp_path, line, quantity, unit, product, grams):
    recipe = _dish(1, "Dish", [line], protein=20)
    recipe["ingredients"][0].update(quantity=quantity, unit=unit)
    engine = RecipeEngine(db, _store(tmp_path, [recipe]))
    _add(db, product, grams)
    [ing] = engine.adapted(1)["ingredients"]
    assert ing["status"] == "have" and ing["using"] == product
    assert engine.adapted(1)["missing"] == []


def test_alternatives_are_split():
    assert alternatives("margarine or 1/4 cup butter") == ["margarine", "butter"]
    assert alternatives("salt/pepper") == ["salt", "pepper"]
    assert alternatives("chickpeas (in water or precooked") == ["chickpeas (in water or precooked"]
    assert alternatives("1/2 cup milk") == ["1/2 cup milk"]


# ------------------------------------------------------------ search
def test_search_ignores_case_and_plural_and_needs_every_word(db):
    for name in ("Eggs", "Rice", "Cherry Tomatoes", "Eggplant"):
        _add(db, name, 500)
    assert [r.product_name for r in search(db, "egg")] == ["Eggs"]
    assert [r.product_name for r in search(db, "EGGS")] == ["Eggs"]
    assert [r.product_name for r in search(db, "tomato")] == ["Cherry Tomatoes"]
    assert search(db, "soy sauce") == []


# ------------------------------------------------------------ one row per food
@pytest.mark.parametrize("text, name, amount", [
    ("a dozen eggs", "eggs", "12"), ("half a dozen eggs", "eggs", "6"), ("a couple of lemons", "lemons", "2"),
    ("a couple limes", "limes", "2"), ("an avocado", "avocado", "1"), ("a lemon", "lemon", "1"),
])
def test_amount_words(text, name, amount):
    assert grocery_list.parse_entry(text) == (name, amount)


def test_a_dozen_eggs_merges_into_the_eggs_row_and_adding_eggs_checks_it_off(db):
    grocery_list.add_entries(db, ["eggs"], "manual")
    entry_id, new = grocery_list.add_entry(db, "a dozen eggs", "manual")
    rows = grocery_list.build_list(db)["items"]
    assert not new and [(r["name"], r["amount"]) for r in rows] == [("eggs", "12")]
    grocery_list.add_entry(db, "6 eggs", "manual")
    assert grocery_list.build_list(db)["items"][0]["amount"] == "18"
    assert grocery_list.check_off(db, "Eggs") == {"id": entry_id, "name": "eggs"}
    assert all(r["checked"] for r in grocery_list.build_list(db)["items"])


# ------------------------------------------------------------ food going to waste
NOW = datetime.now(timezone.utc)


def _wasting_chicken(db) -> int:
    """600 g of chicken that goes bad in 2 days; you use about 100 g a day."""
    pid = db.get_or_create_product("Chicken breast", is_staple=True, usual_package_size_g=700)
    item_id = inv_events.apply_add(db, pid, grams=600, expiration_date=clock.date_in(2).isoformat())
    for day in range(1, 10):
        db.log_event("consume", product_id=pid, item_id=item_id, grams_delta=-100,
                     occurred_at=(NOW - timedelta(days=day)).isoformat())
    return pid


def test_grocery_does_not_restock_what_will_be_wasted(db):
    pid = _wasting_chicken(db)
    for horizon in (None, 1, 3, 7):
        assert all(p.product_id != pid for p in grocery_plan(db, trip_in_days=horizon or 3))
    [row] = use_first(db, 3)
    assert row["product_id"] == pid and row["expires_in_days"] == 2
    assert row["likely_wasted_g"] > 0 and row["restock_g"] == 700


def test_use_first_leaves_once_you_add_it_yourself(db):
    _wasting_chicken(db)
    grocery_list.set_horizon(db, 3)
    assert [u["name"] for u in grocery_list.build_list(db)["use_first"]] == ["Chicken breast"]
    grocery_list.add_entries(db, ["Chicken breast 700 g"], "manual")
    listed = grocery_list.build_list(db)
    assert listed["use_first"] == [] and [i["amount"] for i in listed["items"]] == ["700 g"]


# ------------------------------------------------------------ budget
def test_specialty_items():
    assert is_specialty("saffron threads") and is_specialty("beef dripping") and is_specialty("pine nuts")
    assert not is_specialty("chicken breast")


def test_cheap_means_at_most_one_thing_to_buy_and_no_specialty(db, tmp_path, monkeypatch):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Fried Chicken", ["chicken breast", "dripping"], protein=40),
        _dish(2, "Chicken Pie", ["chicken breast", "puff pastry", "peas"], protein=40),
        _dish(3, "Lemon Chicken", ["chicken breast", "lemon"], protein=40),
        _dish(4, "Plain Chicken", ["chicken breast"], protein=40),
    ]))
    _add(db, "Chicken Breast", 900)
    _offline(monkeypatch)
    out = _bot(db, engine).chat("something cheap with chicken")
    assert [c["id"] for c in out["recipes"]] == [4, 3]
    assert out["reply"].startswith("These need at most one thing from the store.")
