from nutrition.chatbot import NutritionistChatbot, order_by_mention, plain_text
from recipes.engine import RecipeEngine
from tests.test_recipes import _recipe  # noqa: F401  (shared recipe builder)
from recipes.store import RecipeStore


def test_plain_text_strips_markdown():
    assert plain_text("**Chicken Parmesan** is great\n## Steps\n* chop\n- stir") == \
        "Chicken Parmesan is great\nSteps\n• chop\n• stir"


def test_cards_follow_the_order_the_reply_mentions_them():
    cards = [{"id": 1, "name": "Chicken Vino Bianco - Tastes Just Like Olive Garden"},
             {"id": 2, "name": "Lobster Pasta"},
             {"id": 3, "name": "Unmentioned Dish"}]
    reply = "Try the Lobster Pasta, or Chicken Vino Bianco if you have wine."
    assert [c["id"] for c in order_by_mention(cards, reply)] == [2, 1, 3]


def test_offline_mode_still_finds_real_recipes(db, tmp_path, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    store = RecipeStore(tmp_path / "r.db")
    store.add(_recipe(1, "Spinach Pesto Pasta", "italian", ["spaghetti", "spinach"]))
    store.add(_recipe(2, "Chicken Tacos", "mexican", ["chicken breast", "tortilla"]))
    store.commit()
    bot = NutritionistChatbot(db)
    bot._engine = RecipeEngine(db, store)

    out = bot.chat("I'm feeling Italian tonight")
    assert [c["name"] for c in out["recipes"]] == ["Spinach Pesto Pasta"]
    assert "Italian" in out["reply"]
    # The request also teaches the taste profile.
    from intelligence import taste
    assert taste.profile(db).get("cuisine:italian", 0) > 0
