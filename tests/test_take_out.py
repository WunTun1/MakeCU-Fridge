import cv2
import numpy as np

import main
from inventory import events
from inventory.database import Database
from vision import snapshots
from vision.change import detect_changes, direction


def _shelf():
    rng = np.random.default_rng(0)
    return (np.full((480, 640, 3), 150) + rng.integers(-3, 4, (480, 640, 3))).astype(np.uint8)


def _with_orange(frame):
    out = frame.copy()
    cv2.circle(out, (320, 300), 45, (30, 140, 245), -1)
    return out


def test_the_photo_with_the_thing_in_it_decides_in_or_out():
    empty, full = _shelf(), _with_orange(_shelf())
    (region,) = detect_changes(empty, full)
    assert direction(empty, full, region.bbox) == "in"
    assert direction(full, empty, region.bbox) == "out"


def test_taking_something_out_removes_it_whatever_the_scale_says(tmp_path, monkeypatch):
    monkeypatch.setenv("IDENTIFY_ITEMS", "off")
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snaps")
    db = Database(tmp_path / "t.db")
    orange = events.apply_add(db, db.get_or_create_product("Orange"), 180, shelf=0, position=(0.5, 300 / 480))
    events.apply_add(db, db.get_or_create_product("Milk"), 1000, shelf=0, position=(0.1, 0.2))
    empty = _shelf()
    main._handle_trip(db, 0, 1, _with_orange(empty), empty, 1180.0, 1181.0)  # scale didn't move
    assert [i["id"] for i in db.active_items()] != [] and orange not in [i["id"] for i in db.active_items()]
    assert [(s["status"], s["item_name"]) for s in snapshots.recent()] == [("removed", "Orange")]


def test_an_item_with_no_saved_spot_is_found_when_its_the_only_one(tmp_path, monkeypatch):
    monkeypatch.setenv("IDENTIFY_ITEMS", "off")
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snaps")
    db = Database(tmp_path / "t.db")
    yogurt = events.apply_add(db, db.get_or_create_product("Greek Yogurt"), 500, shelf=0)
    empty = _shelf()
    main._handle_trip(db, 0, 1, _with_orange(empty), empty, 500.0, 500.0)
    assert yogurt not in [i["id"] for i in db.active_items()]


def test_when_it_cant_tell_what_left_it_asks(tmp_path, monkeypatch):
    monkeypatch.setenv("IDENTIFY_ITEMS", "off")
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snaps")
    db = Database(tmp_path / "t.db")
    for name in ("Greek Yogurt", "Milk"):  # two candidates, no saved spots, no Gemini
        events.apply_add(db, db.get_or_create_product(name), 500, shelf=0)
    empty = _shelf()
    main._handle_trip(db, 0, 1, _with_orange(empty), empty, 1000.0, 1000.0)
    assert len(db.active_items()) == 2
    assert [(s["status"], s["item_name"]) for s in snapshots.recent()] == [("removed", None)]


def test_a_restart_starts_with_an_empty_shelf(tmp_path):
    db = Database(tmp_path / "t.db")
    on_shelf = events.apply_add(db, db.get_or_create_product("Avocado"), 0, shelf=0)
    by_hand = events.apply_add(db, db.get_or_create_product("Milk"), 1000)  # no shelf
    frozen = events.apply_add(db, db.get_or_create_product("Peas"), 400, location="freezer", shelf=0)
    events.apply_needs_review(db, shelf=0, meta={"reason": "taken out, not sure what"})
    assert main.clear_shelves(db) == 1
    left = {i["id"] for i in db.active_items()}
    assert on_shelf not in left and {by_hand, frozen} <= left
    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM events WHERE event_type = 'needs_review' AND resolved = 0")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM events WHERE event_type IN ('remove', 'waste', 'consume')")
        assert cur.fetchone()[0] == 0  # not counted as eaten or thrown out


def _jalapeno(frame, dx=0):
    out = frame.copy()
    cv2.ellipse(out, (200 + dx, 300), (45, 14), 15, 0, 360, (40, 150, 50), -1)
    return out


def test_whats_already_on_the_shelf_isnt_counted_again(tmp_path, monkeypatch):
    monkeypatch.setenv("IDENTIFY_ITEMS", "off")
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snaps")
    db = Database(tmp_path / "t.db")
    events.apply_add(db, db.get_or_create_product("Jalapeno"), 30, shelf=0, position=(200 / 640, 300 / 480))
    before = _jalapeno(_shelf())
    after = _jalapeno(_shelf(), dx=8)               # nudged while the avocado went in
    cv2.ellipse(after, (420, 300), (50, 65), 0, 0, 360, (40, 70, 45), -1)
    main._handle_trip(db, 0, 1, before, after, 30.0, 200.0)
    photos = snapshots.recent()
    assert len(photos) == 1 and photos[0]["status"] == "skipped"   # one new item (the avocado), named in the app
    assert len(db.active_items()) == 1                             # still one jalapeno


def test_a_scene_that_settled_into_something_new_is_noticed_without_a_hand():
    empty = _shelf()
    assert main._scene_changed(empty, _with_orange(empty), 1)
    assert not main._scene_changed(empty, empty, 1)


def test_movement_counts_as_someone_there_when_mediapipe_misses_the_hand():
    from vision.hands import TripDetector

    class Nobody:
        def detect(self, frame):
            from vision.people import People
            return People(mask=np.zeros(frame.shape[:2], np.uint8), fraction=0.0)

    detector = TripDetector(Nobody())
    still = _shelf()
    hand = still.copy()
    cv2.rectangle(hand, (0, 150), (260, 330), (60, 90, 140), -1)  # an arm reaching in from the side
    assert detector._someone_in_view(still) is False
    assert detector._someone_in_view(hand) is True
