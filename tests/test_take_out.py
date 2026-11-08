import cv2
import numpy as np

import main
from inventory import events
from inventory.database import Database
from vision import snapshots
from vision.change import appeared, detect_changes


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
    assert appeared(empty, full, region.bbox) is True    # put in
    assert appeared(full, empty, region.bbox) is False   # taken out


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
