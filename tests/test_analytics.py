from datetime import date, timedelta
from types import SimpleNamespace

from intelligence import analytics, clock
from inventory import events as inv_events


def _with_history(db, name: str, grams: float, per_day: float, days: int = 14, expires_in: int | None = None):
    """A product with `grams` on hand that's been used at `per_day` for `days` days."""
    pid = db.get_or_create_product(name)
    exp = (clock.local_today() + timedelta(days=expires_in)).isoformat() if expires_in is not None else None
    inv_events.apply_add(db, pid, grams, location="fridge", expiration_date=exp, expiration_estimated=False)
    now = clock.utc_now()
    for d in range(1, days + 1):
        db.log_event("consume", product_id=pid, grams_delta=-per_day, occurred_at=(now - timedelta(days=d)).isoformat())
    return pid


def test_restock_says_when_and_how_much_from_daily_use(db):
    _with_history(db, "Milk", grams=500, per_day=250)
    report = analytics.restock(db)
    assert report["source"] == "local"  # no Tiger in tests
    milk = report["items"][0]
    assert milk["name"] == "Milk" and 200 <= milk["rate_g_per_day"] <= 260
    assert 1.5 <= milk["runs_out_in_days"] <= 2.6
    assert milk["restock_in_days"] in (0, 1)  # a day before it runs out
    assert date.fromisoformat(milk["restock_on"]) >= clock.local_today()
    assert milk["restock_g"] >= milk["rate_g_per_day"] * 7  # about a week's worth
    assert len(milk["series"]) == analytics.WINDOW_DAYS + 1


def test_food_you_never_use_isnt_in_the_restock_report(db):
    pid = db.get_or_create_product("Ketchup")
    inv_events.apply_add(db, pid, 400, location="fridge")
    assert analytics.restock(db)["items"] == []


def test_best_recipe_uses_the_food_most_at_risk(db):
    _with_history(db, "Baby Spinach", grams=300, per_day=10, expires_in=1)   # ~290 g at risk tomorrow
    _with_history(db, "Cheddar Cheese", grams=100, per_day=20, expires_in=6)  # finished in 5 days: nothing at risk

    def match(name, have):
        return SimpleNamespace(recipe=SimpleNamespace(name=name), have=have, swaps=[], short=[], missing=["flour"])

    spinach = match("Spinach Pie", ["spinach", "egg"])
    cheese = match("Cheese Toast", ["cheddar cheese", "bread"])
    engine = SimpleNamespace(suggest=lambda **kw: [cheese, spinach])
    import recipes.engine as recipe_engine

    original = recipe_engine.card
    recipe_engine.card = lambda m: {"name": m.recipe.name}
    try:
        best = analytics.best_recipe(db, engine)
    finally:
        recipe_engine.card = original
    assert best["recipe"] == {"name": "Spinach Pie"}
    assert best["why"] and "spinach" in best["why"][0] and "tomorrow" in best["why"][0]
    assert [f["name"] for f in best["foods"]] == ["Baby Spinach"]  # the cheese gets eaten in time


def test_stock_score_compares_today_with_your_usual(db):
    # Milk: normally ~2 days of supply; today 6 days' worth on hand -> overstocked.
    pid = db.get_or_create_product("Milk")
    now = clock.utc_now()
    inv_events.apply_add(db, pid, 500, location="fridge")
    for d in range(1, 15):
        db.log_event("consume", product_id=pid, grams_delta=-250, occurred_at=(now - timedelta(days=d)).isoformat())
        db.log_event("add", product_id=pid, grams_delta=250, occurred_at=(now - timedelta(days=d, hours=1)).isoformat())
    inv_events.apply_add(db, pid, 1000, location="fridge")
    report = analytics.stock_score(db, days=14)
    assert report["source"] == "local"
    assert report["score"] > 25 and report["band"] == "over"
    assert [f["name"] for f in report["high"]] == ["Milk"]
    assert len(report["history"]) == 14 and report["history"][-1]["score"] == report["score"]


def test_stock_score_is_balanced_with_no_history(db):
    report = analytics.stock_score(db)
    assert report["score"] == 0 and report["band"] == "balanced" and report["history"] == []
