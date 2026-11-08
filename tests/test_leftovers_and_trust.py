"""Round 4: eating leftovers never cooks again, chat changes undo, the assistant sees Home's fridge,
alerts match the colors, Cook tonight ranks by what you can make now, clean recipe text, nut allergies."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from intelligence.alerts import low_stock_alerts
from intelligence.fridge_view import fact_block, going_bad_soon, inventory_entries
from inventory import events as inv_events
from nutrition import chatbot as chatbot_module
from nutrition.chatbot import SYSTEM_PROMPT, NutritionistChatbot, only_ate
from recipes.engine import RecipeEngine, fits_dinner
from recipes.ingredients import allergen_found
from recipes.store import DEFAULT_PATH
from recipes.titles import clean_steps, clean_title
from tests.test_goals_and_truth import _add, _dish, _grams, _store


def _in(days: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=days)).isoformat()


def _consumes(db, name):
    product = db.find_product_by_name(name)
    return [e for e in db.events_for_product(product["id"]) if e["event_type"] == "consume"]


@pytest.fixture
def kitchen(db, tmp_path):
    """Greek Stuffed Chicken cooked once (3 servings left over), chicken and butter in the fridge."""
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Greek Stuffed Chicken", ["chicken breast", "butter"], protein=35, servings=4, calories=362),
        _dish(2, "Chicken Rice Bowl", ["chicken breast", "rice"], protein=30, servings=2, calories=500),
    ]))
    _add(db, "Chicken Breast", 1000, category="Meat")
    _add(db, "Butter", 450)
    engine.cooked(1, made=1.0, servings_eaten=1)
    bot = NutritionistChatbot(db)
    bot._engine = engine
    return bot


def _leftover_servings(bot):
    left = bot.engine.leftovers_for(1)
    return left["servings"] if left else 0


def _offline(monkeypatch):
    monkeypatch.setattr(chatbot_module, "make_client", lambda: None)


def _model_calls(monkeypatch, bot, tool, args, text="Done."):
    """A stand-in for Gemini that calls one tool, then answers."""
    monkeypatch.setattr(chatbot_module, "make_client", lambda: object())
    monkeypatch.setattr(bot, "_converse", lambda client: (bot._run_tool(tool, args), text)[1])


# ------------------------------------------------------------ eating leftovers
def test_logging_a_leftover_serving_in_chat_takes_nothing_else(kitchen, db, monkeypatch):
    _offline(monkeypatch)
    chicken, butter = _grams(db, "Chicken Breast"), _grams(db, "Butter")
    meals_before = len(db.meals_since("2000-01-01"))

    out = kitchen.chat("log one serving of the Greek Stuffed Chicken leftovers")

    assert (_grams(db, "Chicken Breast"), _grams(db, "Butter")) == (chicken, butter)
    assert _leftover_servings(kitchen) == 2
    assert len(db.meals_since("2000-01-01")) == meals_before + 1
    assert out["reply"].startswith("Logged 1 serving of Greek Stuffed Chicken leftovers (35 g protein, 362 kcal).")
    assert "2 servings left, good until" in out["reply"]
    assert out["undo"] == "Undo: puts back 1 serving of Greek Stuffed Chicken leftovers"


def test_cooked_recipe_after_i_had_it_never_deducts(kitchen, db, monkeypatch):
    _model_calls(monkeypatch, kitchen, "cooked_recipe", {"recipe_id": 1, "servings_eaten": 1})
    consumes = len(_consumes(db, "Chicken Breast")), len(_consumes(db, "Butter"))

    out = kitchen.chat("I had the Greek stuffed chicken")

    assert (len(_consumes(db, "Chicken Breast")), len(_consumes(db, "Butter"))) == consumes
    assert _leftover_servings(kitchen) == 2
    assert "2 servings left" in out["reply"]


def test_had_it_without_leftovers_logs_nutrition_only(kitchen, db, monkeypatch):
    _model_calls(monkeypatch, kitchen, "cooked_recipe", {"recipe_id": 2})
    chicken = _grams(db, "Chicken Breast")
    out = kitchen.chat("I ate a chicken rice bowl at lunch")
    assert _grams(db, "Chicken Breast") == chicken
    assert out["reply"] == "Logged 1 serving of Chicken Rice Bowl (30 g protein, 500 kcal). Nothing was taken from the fridge."
    assert out["undo"] is None  # nothing in the fridge changed


@pytest.mark.parametrize("message, ate", [
    ("I had the leftovers", True), ("ate the chicken", True), ("I had some left over chicken", True),
    ("I made it and ate two servings", False), ("I cooked the Greek stuffed chicken", False),
])
def test_only_ate(message, ate):
    assert only_ate(message) is ate


def test_no_leftovers_logs_nothing(db, tmp_path, monkeypatch):
    bot = NutritionistChatbot(db)
    bot._engine = RecipeEngine(db, _store(tmp_path, [_dish(1, "Chili", ["ground beef"], protein=30)]))
    _model_calls(monkeypatch, bot, "ate_leftovers", {"name": "chili"})
    out = bot.chat("I had a serving of the chili leftovers")
    assert out["reply"] == "You don't have any leftovers, so I didn't log anything."
    assert db.meals_since("2000-01-01") == [] and out["turn_id"] is None


# ------------------------------------------------------------------ turn undo
def test_undo_puts_back_every_gram_and_the_leftovers(kitchen, db, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "import.db"))
    server = pytest.importorskip("api.server")
    monkeypatch.setattr(server, "chatbot", kitchen)
    client = TestClient(server.app)

    before = (_grams(db, "Chicken Breast"), _grams(db, "Butter"), _leftover_servings(kitchen))
    meals_before = len(db.meals_since("2000-01-01"))
    _model_calls(monkeypatch, kitchen, "cooked_recipe", {"recipe_id": 1, "servings_eaten": 1})
    out = kitchen.chat("I made the Greek stuffed chicken again")
    assert _leftover_servings(kitchen) == 6
    assert out["undo"] == "Undo: puts back 200 g chicken breast, 200 g butter and removes 3 leftover servings"

    assert client.post(f"/api/chat/turns/{out['turn_id']}/undo").json() == {"ok": True}
    assert (_grams(db, "Chicken Breast"), _grams(db, "Butter"), _leftover_servings(kitchen)) == before
    assert len(db.meals_since("2000-01-01")) == meals_before
    assert client.post(f"/api/chat/turns/{out['turn_id']}/undo").status_code == 409


def test_chat_added_items_and_corrections_undo(db, monkeypatch):
    monkeypatch.setattr(chatbot_module, "lookup_nutrition_usda", lambda name: None)
    bot = NutritionistChatbot(db)
    _add(db, "Rice", 500)
    monkeypatch.setattr(chatbot_module, "make_client", lambda: object())
    monkeypatch.setattr(bot, "_converse", lambda client: (
        bot._run_tool("add_item", {"name": "Oats", "grams": 400, "location": "pantry"}),
        bot._run_tool("update_item", {"name": "Rice", "remaining_grams": 900}), "Done.")[2])
    out = bot.chat("I bought oats, and there's more rice than you think: 900 g")
    assert out["undo"] == "Undo: removes 400 g oats, 400 g rice"
    bot.undo_turn(out["turn_id"])
    assert _grams(db, "Rice") == 500 and db.find_product_by_name("Oats") is not None
    assert not [i for i in db.active_items() if i["product_id"] == db.find_product_by_name("Oats")["id"]]


# ------------------------------------------------------ /today's two undos
def test_today_cooked_meal_offers_both_undos(kitchen, db, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "import.db"))
    server = pytest.importorskip("api.server")
    monkeypatch.setattr(server, "db", db)
    monkeypatch.setattr(server, "chatbot", kitchen)
    client = TestClient(server.app)

    cooked = next(m for m in client.get("/api/meals").json() if m["source"] == "recipe")
    assert cooked["cook_undo"] == "puts back 200 g chicken breast, 200 g butter and removes 3 leftover servings"
    stock = (_grams(db, "Chicken Breast"), _grams(db, "Butter"), _leftover_servings(kitchen))
    client.delete(f"/api/meals/{cooked['id']}")  # "Remove from today's log": nutrition only
    assert (_grams(db, "Chicken Breast"), _grams(db, "Butter"), _leftover_servings(kitchen)) == stock

    meal_id = kitchen.engine.cooked(1)["meal_id"]
    client.post(f"/api/meals/{meal_id}/undo")  # "Undo cooking it too"
    assert (_grams(db, "Chicken Breast"), _grams(db, "Butter"), _leftover_servings(kitchen)) == stock


# ------------------------------------------------- the assistant sees Home
def test_fact_block_lists_exactly_homes_week(kitchen, db):
    _add(db, "Baby Spinach", 150, expiration_date=_in(1))
    _add(db, "Milk", 1000, expiration_date=_in(5))
    _add(db, "Cheddar Cheese", 300, expiration_date=_in(20))
    _add(db, "Peas", 400, expiration_date=_in(2), location="freezer")

    home = {e["name"] for e in inventory_entries(db)
            if e["location"] != "freezer" and e["expires_in_days"] is not None and e["expires_in_days"] <= 7}
    assert {e["name"] for e in going_bad_soon(db)} == home == {"Baby Spinach", "Milk", "Greek Stuffed Chicken leftovers"}
    facts = fact_block(db)
    assert "Greek Stuffed Chicken leftovers: 3 servings, keeps until" in facts
    assert "Baby Spinach (150 g) goes bad tomorrow" in facts
    assert "Cheddar" not in facts.split("Going bad")[1] and "Peas" not in facts

    inventory = kitchen._get_inventory()
    assert inventory["items"][0]["name"] == "Baby Spinach"
    leftovers = next(i for i in inventory["items"] if i["leftovers"])
    assert leftovers["amount"] == "3 servings"
    assert [f["name"] for f in inventory["freezer"]] == ["Peas"]


def test_leftovers_question_offline_names_servings_and_day(kitchen, monkeypatch):
    _offline(monkeypatch)
    out = kitchen.chat("Don't I still have leftovers?")
    assert out["reply"].startswith("You have Greek Stuffed Chicken leftovers: 3 servings, keeps until")
    assert _leftover_servings(kitchen) == 3


def test_supper_searches_use_the_dinner_filter(db, tmp_path, monkeypatch):
    bot = NutritionistChatbot(db)
    bot._engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Homemade Yogurt", ["milk"], protein=10, tags=("breakfast",)),
        _dish(2, "Chocolate Milk Shake", ["milk"], protein=8, tags=("beverages",)),
        _dish(3, "Milk Braised Chicken", ["milk", "chicken breast"], protein=35),
    ]))
    _add(db, "Milk", 1000)
    _add(db, "Chicken Breast", 600)
    _offline(monkeypatch)
    out = bot.chat("Something for supper for one with milk")
    assert [c["name"] for c in out["recipes"]] == ["Milk Braised Chicken"]
    assert all(fits_dinner(bot.engine.store.get(c["id"])) for c in out["recipes"])


def test_system_prompt_is_for_the_phone():
    assert "touchscreen" not in SYSTEM_PROMPT.lower()
    assert SYSTEM_PROMPT.startswith("You are ReFridge's assistant in the phone app.")


# ------------------------------------------------------ alerts match colors
def test_alerts_are_everything_colored_amber_or_red(kitchen, db):
    _add(db, "Baby Spinach", 150, expiration_date=_in(1))
    _add(db, "Milk", 1000, expiration_date=_in(3))
    _add(db, "Yogurt", 500, expiration_date=_in(4))
    colored = {e["product_id"] for e in inventory_entries(db) if e["location"] != "freezer" and (
        (e["expires_in_days"] is not None and e["expires_in_days"] <= 3)
        or (not e["leftovers"] and e["days_left"] is not None and e["days_left"] < 2))}
    alerted = {a.product_id for a in low_stock_alerts(db)}
    assert colored <= alerted
    names = {a.product_name for a in low_stock_alerts(db)}
    assert {"Greek Stuffed Chicken leftovers", "Milk", "Baby Spinach"} <= names and "Yogurt" not in names


# ---------------------------------------------------- Cook tonight ranking
def test_tonight_ranks_by_items_to_buy_and_drops_three_or_more(db, tmp_path):
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Chicken Feast", ["chicken breast", "feta cheese", "olive", "lemon"], protein=40),
        _dish(2, "Chicken Rice", ["chicken breast", "rice"], protein=20),
        _dish(3, "Chicken Feta Bake", ["chicken breast", "feta cheese"], protein=30),
        _dish(4, "Chicken Spinach Feta", ["chicken breast", "spinach", "feta cheese", "cottage cheese"], protein=30),
        _dish(5, "Chicken Spinach", ["chicken breast", "spinach"], protein=25),
    ]))
    for name in ("Chicken Breast", "Rice", "Spinach"):
        _add(db, name, 1000)
    for protein_mode in (False, True):
        ranked = engine.suggest(limit=10, automatic=True, high_protein=protein_mode)
        buys = [len(m.to_buy) for m in ranked]
        assert buys == sorted(buys) and max(buys) <= 2
        assert "Chicken Feast" not in [m.recipe.name for m in ranked]
    # Protein mode keeps its 25 g floor (the 20 g rice bowl goes) and sorts within each buy count.
    assert [m.recipe.name for m in engine.suggest(limit=10, automatic=True, high_protein=True)] == [
        "Chicken Spinach", "Chicken Feta Bake", "Chicken Spinach Feta"]


# ------------------------------------------------------- clean recipe text
@pytest.mark.parametrize("raw, clean", [
    ("Alli's Crunchy Ranch Chicken #RSC", "Alli's Crunchy Ranch Chicken"),
    ("Mr. Foods Banana Bread BEST BANANa BREAD EVER!!!!!!", "Mr. Foods Banana Bread"),
    ("Pastitsio (Makaronia Me", "Pastitsio"),
    ("Chicken Pot Pie (Variation of Mom's)", "Chicken Pot Pie"),
    ("HEAVENLY Crock-Pot HONEY TERIYAKI CHICKEN", "Heavenly Crock-Pot Honey Teriyaki Chicken"),
    ("Baby BLT's With Arugula", "Baby BLT's With Arugula"),
    ("Peanut Butter Sheet Cake With Peanut Butter Frosting", "Peanut Butter Sheet Cake With Peanut Butter Frosting"),
])
def test_clean_title(raw, clean):
    assert clean_title(raw) == clean


def test_clean_steps_drops_headings():
    steps = ["Cooking time: 40 min", "For the sauce:", "Prep time 10 minutes.", "Mix the flour and water:", "Bake."]
    assert clean_steps(steps) == ["Mix the flour and water:", "Bake."]


def test_no_cleaned_library_title_shouts_or_tags():
    if not DEFAULT_PATH.exists():
        pytest.skip("no recipe library built")
    names = [r[0] for r in sqlite3.connect(DEFAULT_PATH).execute("SELECT name FROM recipes")]
    assert not [n for n in map(clean_title, names) if "!!" in n or "#" in n]


# --------------------------------------------------------------- nut allergy
def test_tree_nut_allergy_blocks_the_word_nuts():
    assert allergen_found("Fold in the nuts.", ["walnuts"]) == ("walnuts", "nuts")
    assert allergen_found("1 tsp nutmeg and a doughnut", ["walnut"]) is None


def test_walnut_banana_bread_names_the_allergy_and_shows_nut_free_cards(db, tmp_path, monkeypatch):
    bot = NutritionistChatbot(db)
    bot._engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Walnut Banana Bread", ["banana", "walnuts", "flour"], protein=5),
        _dish(2, "Banana Bread", ["banana", "flour"], protein=5, steps=["Mash.", "Add nuts if you like."]),
        _dish(3, "Classic Banana Bread", ["banana", "flour", "butter"], protein=5),
    ]))
    db.update_profile(allergies=["walnuts"])
    _add(db, "Banana", 600)
    _offline(monkeypatch)
    out = bot.chat("walnut banana bread")
    assert out["reply"] == ("You listed walnuts as an allergy, so I won't suggest recipes with them. "
                            "Here are banana breads without nuts.")
    assert [c["name"] for c in out["recipes"]] == ["Classic Banana Bread"]
    for c in out["recipes"]:
        recipe = bot.engine.store.get(c["id"])
        text = " ".join([recipe.name, *recipe.steps, *(i["name"] for i in recipe.ingredients)])
        assert allergen_found(text, ["walnuts"]) is None


def test_grocery_rows_show_the_clean_title(db):
    from intelligence import grocery_list
    grocery_list.add_entries(db, ["bananas"], "recipe", 7, "Mr. Foods Banana Bread BEST BANANa BREAD EVER!!!!!!")
    row = grocery_list.build_list(db)["items"][0]
    assert row["recipe_name"] == "Mr. Foods Banana Bread"


def test_undo_summary_ignores_events_with_no_stock(db):
    item = _add(db, "Eggs", 300)
    event = inv_events.apply_consume(db, item, 100, meta={"source": "app"})
    assert inv_events.undo_summary(db, [db.get_event(event)]) == "puts back 2 eggs"
    assert inv_events.undo_summary(db, []) is None


def test_a_reply_never_quotes_the_facts_note():
    from nutrition.chatbot import plain_text
    assert plain_text("You have 3 servings left. Fridge facts from the app") == "You have 3 servings left."
