"""Round 5: the fact note never reaches the screen, chat adds to the grocery list with Undo, "without
shopping" never dead-ends, exclusions and card-true text, total minutes, spices as pantry, clean steps."""
from types import SimpleNamespace

import pytest

from nutrition import chatbot as chatbot_module
from nutrition.chatbot import NutritionistChatbot, drop_unshown_foods, exclusions, plain_text
from recipes.engine import RecipeEngine
from recipes.ingredients import canonical, food_terms, needs_no_badge
from recipes.timing import inactive_time, wait_in
from recipes.titles import clean_steps
from tests.test_goals_and_truth import _add, _dish, _store

FACT_PHRASES = ("soonest first", "Fridge facts", "Going bad within", "Leftovers:")


class EchoModel:
    """A stand-in for Gemini that calls the tools a request needs, then pastes the system note into its reply."""

    def __init__(self):
        self.calls = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append((list(contents), config.system_instruction))
        asked = contents[-1].parts[0].text if len(self.calls) == 1 else ""
        if "soy sauce" in asked:
            call = SimpleNamespace(name="add_to_grocery",
                                   args={"items": [{"name": "soy sauce"}, {"name": "lemons", "amount": 6}]})
            return _response([SimpleNamespace(function_call=call)])
        if "without shopping" in asked:
            call = SimpleNamespace(name="find_recipes", args={"must_have_all": True})
            return _response([SimpleNamespace(function_call=call)])
        note = config.system_instruction.split("\n\n", 1)[1]
        return _response([SimpleNamespace(function_call=None)], text=f"Here you go.\n{note}\nEnjoy.")


def _response(parts, text=None):
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))], text=text)


@pytest.fixture
def kitchen(db, tmp_path):
    """Drastic Chicken cooked (1 serving left), spinach going bad; nothing else is makeable without shopping."""
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Drastic Chicken", ["chicken breast", "cheddar cheese"], protein=40, servings=2),
        _dish(2, "Salmon Bake", ["salmon fillet", "lemon"], protein=35),
        _dish(3, "Salmon Salad", ["salmon fillet", "spinach"], protein=30),
        _dish(4, "Spinach Frittata", ["eggs", "spinach", "feta cheese"], protein=25),
    ]))
    _add(db, "Chicken Breast", 600)
    _add(db, "Cheddar Cheese", 300)
    engine.cooked(1, made=1.0, servings_eaten=1)
    _add(db, "Salmon Fillet", 400)
    _add(db, "Baby Spinach", 150)
    bot = NutritionistChatbot(db)
    bot._engine = engine
    return bot


@pytest.mark.parametrize("message", ["add soy sauce and 6 lemons to my grocery list", "What can I make without shopping?",
                                     "put soy sauce and 6 lemons on my shopping list please"])
def test_fact_note_never_reaches_the_reply_or_history(kitchen, db, monkeypatch, message):
    model = EchoModel()
    monkeypatch.setattr(chatbot_module, "make_client", lambda: model)
    out = kitchen.chat(message)
    stored = " ".join(m["content"] for m in db.recent_chat(limit=50))
    for phrase in FACT_PHRASES:
        assert phrase.lower() not in out["reply"].lower()
        assert phrase.lower() not in stored.lower()
    if not model.calls:
        assert out["reply"] == "Added soy sauce and 6 lemons to your grocery list."  # done in code, no model
        return
    contents, system = model.calls[0]
    assert "soonest first" in system  # the facts went to the model as system context...
    assert all("soonest first" not in p.text for c in contents for p in c.parts)  # ...not in a message


def test_plain_text_drops_echoed_fact_lines():
    reply = ("Leftovers: Drastic Chicken leftovers: 1 serving, keeps until Monday.\n"
             "Spinach goes bad tomorrow. Going bad within 7 days, soonest first: Spinach (150 g).")
    assert plain_text(reply) == "Spinach goes bad tomorrow."


# ------------------------------------------------------------ grocery from chat
def test_chat_adds_to_the_grocery_list_and_undo_removes_only_those(kitchen, db, monkeypatch):
    monkeypatch.setattr(chatbot_module, "make_client", lambda: None)
    from intelligence import grocery_list
    grocery_list.add_entries(db, ["milk"], "manual")
    out = kitchen.chat("add soy sauce and 6 lemons to my grocery list")
    assert out["reply"] == "Added soy sauce and 6 lemons to your grocery list."
    rows = {e["name"]: e["amount"] for e in grocery_list.build_list(db)["items"]}
    assert rows == {"milk": None, "soy sauce": None, "lemons": "6"}

    again = kitchen.chat("add soy sauce and 6 lemons to my grocery list")
    assert again["reply"] == "Soy sauce and lemons were already on your list." and again["turn_id"] is None
    assert len(grocery_list.build_list(db)["items"]) == 3

    assert out["undo"] == "Undo: takes soy sauce and lemons off your grocery list"
    kitchen.undo_turn(out["turn_id"])
    assert [e["name"] for e in grocery_list.build_list(db)["items"]] == ["milk"]


# ------------------------------------------------------------ no dead ends
def test_without_shopping_offers_leftovers_then_one_item_away(kitchen, monkeypatch):
    monkeypatch.setattr(chatbot_module, "make_client", lambda: None)
    out = kitchen.chat("What can I make without shopping?")
    assert out["reply"].startswith("Nothing in the library uses only what you have. Your Drastic Chicken "
                                   "leftovers (1 serving) are ready, and these need one thing.")
    assert "There are no recipes" not in out["reply"]
    names = [c["name"] for c in out["recipes"]]
    assert names[0] == "Drastic Chicken" and len(names) >= 2
    assert all(len(c["missing"]) + len(c["short"]) == 1 for c in out["recipes"][1:])


# ------------------------------------------------------------ exclusions, card-true text
def test_exclusions_are_parsed():
    assert exclusions("salmon ideas besides salad") == ["salad"]
    assert exclusions("something other than pasta please") == ["pasta"]
    assert exclusions("no thanks, without shopping") == []
    assert exclusions("not chicken soup") == ["chicken soup"]


def test_besides_salad_drops_salad_titles_and_code_writes_the_lead(kitchen, monkeypatch):
    monkeypatch.setattr(chatbot_module, "make_client", lambda: None)
    out = kitchen.chat("salmon ideas besides salad")
    assert out["recipes"] and not any("salad" in c["name"].lower() for c in out["recipes"])
    assert out["reply"].startswith("Here are salmon recipes without salad.")
    assert "salmons" not in out["reply"]


def test_a_sentence_about_a_food_no_card_uses_is_removed():
    reply = "The Salmon Bake card is quick. It's great with feta and sun-dried tomatoes. The lemon keeps it bright."
    shown = ["salmon fillet", "lemon", "salmon bake"]
    assert drop_unshown_foods(reply, shown, food_terms()) == "The Salmon Bake card is quick. The lemon keeps it bright."


# ------------------------------------------------------------ total minutes
@pytest.mark.parametrize("sentence, minutes", [
    ("Marinate in the refrigerator at least four hours but a full day is best", 240),
    ("Cover and refrigerate overnight", 480),
    ("Chill for 2-3 hours", 180),
    ("Let the dough rest 30 minutes", 30),
])
def test_waiting_time_in_a_step(sentence, minutes):
    assert wait_in(sentence)[0] == minutes


def test_waits_add_up_and_name_the_longest():
    assert inactive_time(["Marinate 4 hours.", "Bake 20 minutes.", "Let rest 30 minutes."]) == (270, "marinating")
    assert inactive_time(["Add the rest of the cheese and bake 20 minutes.", "Let rest 5 minutes."]) == (0, None)


def test_a_long_marinade_fails_under_30_minutes_and_cook_tonight(db, tmp_path):
    steps = ["Mix maple syrup and soy sauce.", "Marinate the salmon at least four hours.", "Bake 7 minutes."]
    engine = RecipeEngine(db, _store(tmp_path, [
        _dish(1, "Pepper-Crusted Maple-Glazed Salmon", ["salmon fillet"], protein=30, minutes=17, steps=steps),
        _dish(2, "Quick Salmon", ["salmon fillet"], protein=30, minutes=20),
    ]))
    _add(db, "Salmon Fillet", 600)
    salmon = engine.store.get(1)
    assert (salmon.minutes, salmon.inactive_min, salmon.inactive_verb, salmon.total_minutes) == (17, 240, "marinating", 257)
    assert [m.recipe.id for m in engine.suggest("salmon", max_minutes=30)] == [2]
    assert [m.recipe.id for m in engine.suggest(automatic=True)] == [2]


# ------------------------------------------------------------ spices are pantry
@pytest.mark.parametrize("name, unit, quantity, pantry", [
    ("dried thyme", None, None, True),
    ("turmeric", "tsp", "1", True),
    ("fresh basil", "cups", "2", False),
    ("coarse salt", "tsp", "1", True),
    ("freshly cracked pepper", None, None, True),
    ("fresh rosemary", "sprig", "2", False),
])
def test_spoon_spices_are_pantry(name, unit, quantity, pantry):
    assert needs_no_badge(name, canonical(name), unit, quantity) is pantry


# ------------------------------------------------------------ steps are instructions
def test_blog_sentences_leave_the_steps():
    steps = ["Brown the onions.", "I've messed it up enough times over the years.", "These times are only a guide.",
             "Add the milk. My kids love this part.", "Alternatively you can use the stove.",
             "I'm sure that mushrooms could be added to this recipe.", "Serve hot."]
    assert clean_steps(steps) == ["Brown the onions.", "Add the milk.", "Serve hot."]


# ------------------------------------------------------------ Cook tonight without the wait
def test_cook_tonight_is_rebuilt_in_the_background_after_a_change(monkeypatch, tmp_path):
    import time

    from fastapi.testclient import TestClient

    from inventory.database import Database
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "import.db"))
    server = pytest.importorskip("api.server")
    monkeypatch.setattr(server, "db", Database(tmp_path / "api.db"))
    builds = []
    engine = SimpleNamespace(suggest=lambda **kw: builds.append(kw) or [])
    monkeypatch.setattr(server, "chatbot", SimpleNamespace(engine=engine))
    monkeypatch.setattr(server, "_tonight", {"key": None, "at": 0.0, "value": None, "building": False})
    client = TestClient(server.app)

    assert client.get("/api/recipes/tonight").json() == []  # nothing cached yet: built on the spot
    client.post("/api/items", json={"name": "Eggs", "quantity": 6, "unit": "count", "location": "fridge"})
    deadline = time.monotonic() + 5
    while not server._tonight_fresh() and time.monotonic() < deadline:
        time.sleep(0.02)
    built = len(builds)
    assert built == 2
    client.get("/api/recipes/tonight")
    assert len(builds) == built  # answered from the background build
