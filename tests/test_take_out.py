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
