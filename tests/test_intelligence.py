from datetime import datetime, timedelta, timezone

from inventory import events as inv_events
from intelligence.alerts import low_stock_alerts
from intelligence.consumption import days_left, grams_on_hand, usage_rate_g_per_day
from intelligence.grocery import grocery_plan
from intelligence.search import search

NOW = datetime.now(timezone.utc)


def _log_consume_days_ago(db, product_id, item_id, days_ago, grams):
    db.log_event(
        "consume", product_id=product_id, item_id=item_id, grams_delta=-grams,
        occurred_at=(NOW - timedelta(days=days_ago)).isoformat(),
    )


def test_grams_on_hand_sums_active_items(db):
    pid = db.get_or_create_product("Milk")
    inv_events.apply_add(db, pid, grams=500)
    inv_events.apply_add(db, pid, grams=300)
    assert grams_on_hand(db, pid) == 800


def test_usage_rate_reflects_recent_consumption(db):
    pid = db.get_or_create_product("Milk")
    item_id = inv_events.apply_add(db, pid, grams=2000)
    for day in range(1, 8):
        _log_consume_days_ago(db, pid, item_id, day, 150)
    rate = usage_rate_g_per_day(db, pid)
    assert rate > 0
    # ~150g/day on average, within a generous margin for the decay weighting
    assert 50 < rate < 300


def test_days_left_is_none_without_usage_history(db):
    pid = db.get_or_create_product("Rice")
    inv_events.apply_add(db, pid, grams=2000)
    assert days_left(db, pid) is None


def test_days_left_decreases_as_stock_runs_low(db):
    pid = db.get_or_create_product("Milk")
    item_id = inv_events.apply_add(db, pid, grams=100)
    for day in range(1, 5):
        _log_consume_days_ago(db, pid, item_id, day, 50)
    db.update_item_grams(item_id, 100)  # restore "on hand" after simulated history
    dl = days_left(db, pid)
    assert dl is not None and dl > 0


def test_low_stock_alert_for_staple_fully_out(db):
    pid = db.create_product("Butter", is_staple=True, usual_package_size_g=450)
    alerts = low_stock_alerts(db)
    assert any(a.product_id == pid and a.reason == "staple_out" for a in alerts)


def test_low_stock_alert_for_low_fraction(db):
    pid = db.create_product("Butter", is_staple=False, usual_package_size_g=450)
    inv_events.apply_add(db, pid, grams=50)  # well under 20% of 450g
    alerts = low_stock_alerts(db)
    assert any(a.product_id == pid and a.reason == "low_fraction" for a in alerts)


def test_grocery_plan_skips_products_with_no_usage_rate(db):
    db.create_product("Rice", is_staple=True, usual_package_size_g=2000)
    plan = grocery_plan(db, trip_in_days=3)
    assert plan == []


def test_grocery_plan_suggests_buying_staple_running_low(db):
    pid = db.get_or_create_product("Rice", is_staple=True, usual_package_size_g=2000)
    item_id = inv_events.apply_add(db, pid, grams=300)
    for day in range(1, 10):
        _log_consume_days_ago(db, pid, item_id, day, 100)
    db.update_item_grams(item_id, 300)
    plan = grocery_plan(db, trip_in_days=1)
    assert any(p.product_id == pid for p in plan)


def test_search_finds_close_match_by_fuzzy_name(db):
    pid = db.get_or_create_product("Greek Yogurt")
    inv_events.apply_add(db, pid, grams=400)
    results = search(db, "yogurt")
    assert any(r.product_id == pid for r in results)
