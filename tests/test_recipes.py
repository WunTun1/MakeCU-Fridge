from datetime import datetime, timedelta, timezone

from intelligence.recipes import suggest, suggested_recipes


def test_only_recipes_with_every_ingredient():
    names = [s.name for s in suggest(["Eggs", "Baby Spinach"], set(), limit=10)]
    assert names == ["Spinach Omelette"]


def test_keywords_match_word_starts_only():
    # "ham" must not match "Graham Crackers"; "egg" must not match "Veggie Mix".
    assert suggest(["Graham Crackers", "Veggie Mix", "Cheddar Cheese"], set(), limit=10) == []


def test_recipes_using_food_expiring_soon_rank_first():
    on_hand = ["Eggs", "Cheddar Cheese", "Butter", "Baby Spinach"]
    first = suggest(on_hand, use_soon={"Baby Spinach"}, limit=2)[0]
    assert first.name == "Spinach Omelette"
    assert first.uses_soon == ["Baby Spinach"]
    assert first.uses[0] == "Baby Spinach"


def test_prefers_expiring_alternative_ingredient():
    s = suggest(["Chicken Breast", "Lettuce", "Baby Spinach"], use_soon={"Baby Spinach"}, limit=10)
    salad = next(x for x in s if x.name == "Chicken Salad")
    assert "Baby Spinach" in salad.uses and "Lettuce" not in salad.uses


def test_suggested_recipes_reads_inventory(db):
    eggs = db.get_or_create_product("Eggs")
    spinach = db.get_or_create_product("Baby Spinach")
    db.create_item(eggs, grams=300)
    soon = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    db.create_item(spinach, grams=100, expiration_date=soon)
    [s] = suggested_recipes(db)
    assert s.name == "Spinach Omelette" and s.uses_soon == ["Baby Spinach"]
