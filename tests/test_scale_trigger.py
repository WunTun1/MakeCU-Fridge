"""The fridge loop's trigger is the scale: a shelf settling at least CHANGE_MIN_G from where it was.
Gemini, shown the before and after photos with the weight change, says what it was."""
import numpy as np
import pytest

import main
from inventory import events
from inventory.database import Database
from sensors.scale import ScaleReader
from vision import classifier, snapshots


def _scale(*readings):
    scale = ScaleReader(source="network", num_shelves=1)
    for g in readings:
        scale.ingest_weight(0, g)
    return scale


def _settle(scale, grams):
    for _ in range(10):
        scale.ingest_weight(0, grams)


def test_a_settled_change_of_eight_grams_or_more_is_a_change():
    scale = _scale(*[500.0] * 10)
    watcher = main.WeightWatcher(scale)
    assert watcher.changes() == {}            # first settled weight is the baseline
    _settle(scale, 506.0)
    assert watcher.changes() == {}            # under 8 g: drift, folded into the baseline
    _settle(scale, 515.0)
    assert watcher.changes() == {0: (506.0, 515.0)}


def test_nothing_counts_until_the_scale_settles():
    scale = _scale(*[500.0] * 10)
    watcher = main.WeightWatcher(scale)
    watcher.changes()
    for g in (520, 640, 580, 700, 690, 705, 680, 699, 702, 690):  # a hand pressing, an item landing
        scale.ingest_weight(0, g)
    assert watcher.changes() == {} and not watcher.steady()
    _settle(scale, 682.0)
    assert watcher.changes() == {0: (500.0, 682.0)}


def test_slow_creep_never_adds_up_to_a_change():
    scale = _scale(*[500.0] * 10)
    watcher = main.WeightWatcher(scale)
    for step in range(1, 20):
        _settle(scale, 500.0 - step * 2)       # 38 g of creep, 2 g at a time
        assert watcher.changes() == {}


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snaps")
    return Database(tmp_path / "t.db")


def _frames():
    return np.zeros((48, 64, 3), np.uint8), np.full((48, 64, 3), 40, np.uint8)


def _gemini(monkeypatch, **answer):
    seen = {}

    def fake(before, after, grams_delta, on_shelf):
        seen.update(grams_delta=grams_delta, on_shelf=on_shelf, before=before, after=after)
        return {"item_name": "Lime", "category": "produce", "visible_expiration_date": None,
                "days_until_expired": 14, "confidence": 0.9, "needs_confirmation": False, "index": None, **answer}

    monkeypatch.setattr(classifier, "identify_change", fake)
    return seen


def test_heavier_adds_what_gemini_names_at_the_weight_change(db, monkeypatch):
    seen = _gemini(monkeypatch)
    before, after = _frames()
    main.handle_change(db, 0, before, after, 500.0, 567.0)
    (item,) = db.active_items()
    assert db.get_product(item["product_id"])["name"] == "Lime" and item["grams"] == pytest.approx(67)
    assert seen["grams_delta"] == pytest.approx(67) and seen["before"] is before and seen["after"] is after


def test_lighter_by_about_the_whole_item_removes_the_one_gemini_picks(db, monkeypatch):
    lime = events.apply_add(db, db.get_or_create_product("Lime"), 67, shelf=0)
    avocado = events.apply_add(db, db.get_or_create_product("Avocado"), 200, shelf=0)
    seen = _gemini(monkeypatch, item_name="Avocado", index=1)
    main.handle_change(db, 0, *_frames(), 767.0, 570.0)
    assert seen["on_shelf"] == ["Lime", "Avocado"]
    assert [i["id"] for i in db.active_items()] == [lime]
    assert avocado not in [i["id"] for i in db.active_items()]
    assert snapshots.recent()[0]["status"] == "removed" and snapshots.recent()[0]["item_name"] == "Avocado"


def test_lighter_by_part_of_an_item_is_some_used(db, monkeypatch):
    milk = events.apply_add(db, db.get_or_create_product("Milk"), 1000, shelf=0)
    _gemini(monkeypatch, item_name="Milk", index=0)
    main.handle_change(db, 0, *_frames(), 1000.0, 750.0)
    assert db.get_item(milk)["grams"] == pytest.approx(750)


def test_without_gemini_the_weight_still_finds_what_left(db, monkeypatch):
    events.apply_add(db, db.get_or_create_product("Lime"), 67, shelf=0)
    avocado = events.apply_add(db, db.get_or_create_product("Avocado"), 200, shelf=0)
    _gemini(monkeypatch, item_name="Unknown Item", confidence=0.0, needs_confirmation=True)
    main.handle_change(db, 0, *_frames(), 767.0, 572.0)   # 195 g left: the avocado's weight
    assert avocado not in [i["id"] for i in db.active_items()]


def test_unsure_what_was_put_in_asks_in_the_app(db, monkeypatch):
    _gemini(monkeypatch, item_name="Unknown Item", confidence=0.2, needs_confirmation=True)
    main.handle_change(db, 0, *_frames(), 0.0, 120.0)
    assert db.active_items() == []
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM events WHERE event_type = 'needs_review'")
        assert cur.fetchone()[0] == 1
