"""Protein mode, same-food matching, truthful chat logging, allergy blocks, leftovers,
the freezer and count remnants."""
from datetime import date, timedelta

import pytest

from intelligence.alerts import low_stock_alerts
from inventory import events as inv_events
from inventory.database import Database
from nutrition import chatbot as chatbot_module
from nutrition.chatbot import NutritionistChatbot
from nutrition.intake import eat_from_fridge, get_intake, protein_mode
from recipes.engine import RecipeEngine
from recipes.ingredients import allergen_found, canonical, matches
from recipes.store import RecipeStore
from tests.test_recipes import _recipe


def _store(tmp_path, recipes):
    store = RecipeStore(tmp_path / "r.db")
    for r in recipes:
        store.add(r)
    store.commit()
    return store


def _dish(rid, name, ingredients, protein, servings=2, calories=400, steps=None, **kw):
    r = _recipe(rid, name, None, ingredients, protein=protein)
    r.update(servings=servings, calories=calories, **kw)
    if steps:
        r["steps"] = steps
    return r


def _add(db, name, grams, **kw):
    product_id = db.get_or_create_product(name, **{k: v for k, v in kw.items() if k in ("category", "nutrition_per_100g", "unit")})
    return inv_events.apply_add(db, product_id, grams, **{k: v for k, v in kw.items() if k in ("expiration_date", "shelf", "location")})


def _grams(db, name):
    product = db.find_product_by_name(name)
    return sum(i["grams"] for i in db.active_items() if i["product_id"] == product["id"])


# ------------------------------------------------------------- protein mode
@pytest.mark.parametrize("protein, calories, on", [(160, 2200, True), (140, 2200, True), (125, 2000, True),
                                                   (100, 2000, False), (None, 2000, False)])
def test_protein_mode_threshold(protein, calories, on):
    # 160/2200 is 29%, 125/2000 exactly 25%, 100/2000 is 20%.
    assert protein_mode({"daily_protein_g": protein, "daily_calories": calories}) is on


def test_protein_mode_hides_low_and_unknown_protein_and_ranks_by_protein(db, tmp_path):
    store = _store(tmp_path, [
        _dish(1, "Chicken Bowl", ["chicken breast", "rice"], protein=35, calories=500),
        _dish(2, "Chicken Wrap", ["chicken breast", "tortilla"], protein=35, calories=350),
        _dish(3, "Chicken Stew", ["chicken breast", "carrot"], protein=28),
        _dish(4, "Rice Spinach Bake", ["rice", "spinach"], protein=None),
        _dish(5, "Mac and Cheese", ["macaroni", "cheddar cheese"], protein=15),
        _dish(6, "Chicken Salad", ["chicken breast", "lettuce"], protein=22),
    ])
    engine = RecipeEngine(db, store)
    for name in ("Chicken Breast", "Rice", "Spinach", "Cheddar Cheese"):
        _add(db, name, 1000)

    names = [m.recipe.name for m in engine.suggest(limit=10, automatic=True, high_protein=True)]
    assert names == ["Chicken Wrap", "Chicken Bowl", "Chicken Stew"]  # 35 g at 350 kcal beats 35 g at 500

    default = [m.recipe.name for m in engine.suggest(limit=10, automatic=True)]
    assert "Rice Spinach Bake" in default and "Mac and Cheese" in default


def test_protein_floor_relaxes_to_20_g_when_fewer_than_3_qualify(db, tmp_path):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Chicken Bowl", ["chicken breast"], protein=30),
        _dish(2, "Chicken Salad", ["chicken breast", "lettuce"], protein=22),
        _dish(3, "Chicken Soup", ["chicken breast", "noodle"], protein=12),
    ]))
    _add(db, "Chicken Breast", 1000)
    names = [m.recipe.name for m in engine.suggest(query="chicken", high_protein=True)]
    assert names == ["Chicken Bowl", "Chicken Salad"]


def test_meal_prep_filters_by_servings_and_protein(db, tmp_path):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Chicken Pancakes", ["chicken breast", "flour"], protein=15, servings=6),
        _dish(2, "Chicken Bake", ["chicken breast", "rice"], protein=38, servings=6),
        _dish(3, "Chicken Plate", ["chicken breast"], protein=45, servings=1),
    ]))
    _add(db, "Chicken Breast", 1700)
    names = [m.recipe.name for m in engine.suggest(query="chicken", min_servings=4, min_protein_g=30)]
    assert names == ["Chicken Bake"]


def test_chat_relaxes_a_protein_ask_by_10_g_and_says_the_closest(db, tmp_path):
    bot = NutritionistChatbot(db)
    bot._engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Chicken Bake", ["chicken breast", "rice"], protein=35, servings=6),
        _dish(2, "Chicken Pancakes", ["chicken breast", "flour"], protein=15, servings=6),
    ]))
    _add(db, "Chicken Breast", 1700)
    out = bot._find_recipes({"query": "chicken", "min_servings": 4, "min_protein_g": 40})
    assert [r["name"] for r in out["recipes"]] == ["Chicken Bake"]
    assert out["say"] == "Nothing has 40 g protein per serving. Closest is 35 g per serving."


# ------------------------------------------------------------ same food
@pytest.mark.parametrize("recipe, have, ok", [
    ("peanut butter", "butter", False), ("almond milk", "milk", False), ("coconut cream", "cream", False),
    ("cream cheese", "cheddar cheese", False), ("greek yogurt", "yogurt", True),
    ("boneless chicken breast", "chicken breast", True), ("sharp cheddar cheese", "cheddar cheese", True),
])
def test_a_match_is_the_same_food(recipe, have, ok):
    assert matches(recipe, have) is ok


def test_peanut_butter_is_to_buy_not_have(db, tmp_path):
    engine = RecipeEngine(db, _store(tmp_path, [_dish(1, "Peanut Noodles", ["peanut butter", "noodles"], protein=20)]))
    _add(db, "Butter", 450)
    _add(db, "Noodles", 500)
    r = engine.adapted(1)
    assert {line["name"]: line["status"] for line in r["ingredients"]}["peanut butter"] == "missing"
    assert r["missing"] == ["peanut butter"]


# ---------------------------------------------------------------- allergies
def test_allergy_words_are_whole_words_with_plurals():
    assert allergen_found("high-protein shrimp stir fry", ["Shellfish"]) == ("shellfish", "shrimp")
    assert allergen_found("Chicken (Or Shrimp, or Pork) Lo Mein", ["shellfish"]) == ("shellfish", "shrimp")
    assert allergen_found("3 large eggs", ["egg"]) == ("egg", "eggs")
    assert allergen_found("roasted eggplant", ["egg"]) is None


def test_allergies_filter_titles_and_steps(db, tmp_path):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Healthy Chicken (Or Shrimp, or Pork) Lo Mein", ["chicken breast", "noodles"], protein=30),
        _dish(2, "Chicken Skillet", ["chicken breast", "rice"], protein=30, steps=["Add the prawns and stir."]),
        _dish(3, "Chicken Rice", ["chicken breast", "rice"], protein=30),
    ]))
    db.update_profile(allergies=["shellfish"])
    _add(db, "Chicken Breast", 1000)
    for kw in ({"query": "chicken"}, {"automatic": True}):
        assert [m.recipe.name for m in engine.suggest(limit=10, **kw)] == ["Chicken Rice"]


def test_a_blocked_query_names_the_allergy_and_shows_no_cards(db, tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(chatbot_module, "make_client", lambda: None)
    bot = NutritionistChatbot(db)
    bot._engine = RecipeEngine(db, _store(tmp_path, [_dish(1, "Shrimp Stir Fry", ["shrimp", "rice"], protein=30)]))
    db.update_profile(allergies=["shellfish"])
    out = bot.chat("high-protein shrimp stir fry")
    assert out["reply"] == "You listed shellfish as an allergy, so I won't suggest shrimp. You can change allergies in Profile."
    assert out["recipes"] == []


# ------------------------------------------------------ truthful chat logging
def test_log_meal_reports_what_it_could_not_count(db, monkeypatch):
    monkeypatch.setattr(chatbot_module, "lookup_nutrition_usda", lambda name: None)
    _add(db, "Greek Yogurt", 500, nutrition_per_100g={"calories": 59, "protein_g": 10.0})
    bot = NutritionistChatbot(db)

    out = bot._log_meal_tool("Yogurt and whey", 1, {"Greek Yogurt": 200, "whey": 30})
    assert [i["name"] for i in out["logged_items"]] == ["Greek Yogurt"] and out["unresolved"] == ["whey"]
    assert out["must_say"] == ("I couldn't find nutrition for whey, so it isn't counted. "
                               "Tell me the protein and calories on the label.")
    assert get_intake(db)["totals"]["protein_g"] == pytest.approx(20)
    assert bot._with_code_sentences("I've logged your Greek yogurt and whey.") == (
        "Logged Greek yogurt 200 g (20 g protein, 118 kcal). " + out["must_say"])

    before = _grams(db, "Greek Yogurt")
    label = bot._log_meal_tool("Whey", protein_g=24, calories=120)
    assert label["logged"] and get_intake(db)["totals"]["protein_g"] == pytest.approx(44)
    assert _grams(db, "Greek Yogurt") == before


# ----------------------------------------------------------------- leftovers
@pytest.fixture
def cook(db, tmp_path):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Greek Stuffed Chicken", ["chicken breast", "feta cheese"], protein=35, servings=4, calories=362),
    ]))
    _add(db, "Chicken Breast", 1000, category="Meat")
    return engine


def test_made_minus_eaten_becomes_leftovers(cook, db):
    result = cook.cooked(1, made=1.0, servings_eaten=1)
    left = result["leftovers"]
    assert left["servings"] == 3
    assert left["expiration_date"] == (date.today() + timedelta(days=3)).isoformat()
    assert cook.leftovers_for(1) == {"product_id": left["product_id"], "servings": 3}
    assert db.get_product(left["product_id"])["name"] == "Greek Stuffed Chicken leftovers"

    chicken = _grams(db, "Chicken Breast")
    eaten = eat_from_fridge(db, left["product_id"], db.get_product(left["product_id"])["grams_per_unit"], "Greek Stuffed Chicken")
    assert eaten["protein_g"] == pytest.approx(35)
    assert cook.leftovers_for(1)["servings"] == 2 and _grams(db, "Chicken Breast") == chicken

    cook.undo_meal(eaten["meal_id"])
    assert cook.leftovers_for(1)["servings"] == 3
    assert db.get_meal(eaten["meal_id"]) is None

    cook.undo_meal(result["meal_id"])  # undoing the cook takes the leftovers back too
    assert cook.leftovers_for(1) is None


def test_half_a_recipe_eaten_whole_leaves_nothing(cook):
    assert cook.cooked(1, made=0.5, servings_eaten=2)["leftovers"] is None


# --------------------------------------------------------------------- freezer
def test_freezing_moves_dates_drops_the_alert_and_undoes(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "import.db"))
    server = pytest.importorskip("api.server")
    db = Database(tmp_path / "api.db")
    monkeypatch.setattr(server, "db", db)
    client = TestClient(server.app)

    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    item_id = _add(db, "Chicken Breast", 1400, category="Meat", expiration_date=tomorrow, shelf=0)
    pid = db.get_item(item_id)["product_id"]
    assert any(a.reason == "expiring_soon" for a in low_stock_alerts(db))

    out = client.post(f"/api/products/{pid}/freeze").json()
    assert date.fromisoformat(out["expiration_date"]) - date.today() == timedelta(days=270)
    inv_events.apply_consume(db, item_id, 600, meta={"source": "app"})  # a fast rate: it would "run out" soon
    assert not any(a.product_name == "Chicken Breast" for a in low_stock_alerts(db))
    inventory = client.get("/api/summary").json()["inventory"]
    assert [(e["name"], e["location"]) for e in inventory] == [("Chicken Breast", "freezer")]

    client.post("/api/events/undo", json={"event_ids": out["event_ids"]})
    item = db.get_item(item_id)
    assert (item["location"], item["expiration_date"], item["leaving_shelf"]) == ("fridge", tomorrow, 0)


def test_a_frozen_items_shelf_drop_asks_nothing(db):
    item_id = _add(db, "Chicken Breast", 1400, shelf=0)
    inv_events.move_storage(db, item_id, "freezer", "2027-08-01")
    assert inv_events.apply_needs_review(db, shelf=0, meta={"reason": "drop", "grams": 1390}) is None
    assert db.needs_review() == [] and db.get_item(item_id)["status"] == "active"
    assert db.get_item(item_id)["shelf"] is None

    other = _add(db, "Pork Chops", 600, shelf=0)
    inv_events.move_storage(db, other, "freezer", "2027-08-01")
    inv_events.apply_remove(db, other)  # the camera saw it go
    assert db.get_item(other)["status"] == "active" and db.get_item(other)["location"] == "freezer"


# --------------------------------------------------------------------- remnants
def test_a_count_remnant_under_half_a_unit_is_finished(db):
    item_id = _add(db, "Eggs", 300)  # 6 eggs at 50 g
    inv_events.apply_consume(db, item_id, 285, meta={"source": "app"})  # leaves 0.3 of an egg
    assert db.get_item(item_id)["status"] == "removed"
    kept = _add(db, "Eggs", 300)
    inv_events.apply_consume(db, kept, 260, meta={"source": "app"})  # leaves 0.8: still about 1 egg
    assert db.get_item(kept)["grams"] == pytest.approx(40)


def test_startup_clears_old_remnants_once(tmp_path):
    path = tmp_path / "old.db"
    db = Database(path)
    item_id = _add(db, "Eggs", 10)
    with db.cursor() as cur:  # as an older version left it
        cur.execute("DELETE FROM settings WHERE key = 'remnants_finished'")
    db.close()
    assert Database(path).get_item(item_id)["status"] == "removed"


def test_canonical_keeps_the_food_word():
    assert canonical("2 tbsp peanut butter") == "peanut butter"
