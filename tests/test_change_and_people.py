import cv2
import numpy as np
import pytest

from vision.change import detect_changes, steady_frame
from vision.hands import TripDetector
from vision.people import People

H, W = 480, 640


def _shelf(seed: int = 0) -> np.ndarray:
    """A textured fridge shelf: gradient, a few items, sensor noise."""
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img[:] = np.linspace(70, 150, W)[None, :, None]
    cv2.rectangle(img, (60, 200), (130, 400), (40, 120, 200), -1)
    cv2.circle(img, (480, 330), 55, (60, 170, 70), -1)
    img += rng.normal(0, 3, img.shape)
    return np.clip(img, 0, 255).astype(np.uint8)


def test_exposure_and_white_balance_drift_is_not_a_change():
    before = _shelf(0)
    after = _shelf(1).astype(np.float32)
    after = after * np.array([1.25, 1.3, 1.35]) + 8   # auto-exposure brighter, white balance warmer
    after = np.clip(after, 0, 255).astype(np.uint8)
    assert detect_changes(before, after) == []


def test_new_item_is_one_region_at_the_item():
    before = _shelf(0)
    after = _shelf(1)
    cv2.rectangle(after, (260, 220), (340, 400), (230, 230, 235), -1)
    regions = detect_changes(before, after)
    assert len(regions) == 1
    x, y, w, h = regions[0].bbox
    assert abs(x - 260) < 8 and abs(y - 220) < 8 and abs(w - 81) < 12 and abs(h - 181) < 12


def test_ignore_mask_hides_a_person():
    before = _shelf(0)
    after = _shelf(1)
    cv2.rectangle(after, (400, 0), (640, 480), (150, 170, 210), -1)   # an arm across the right side
    ignore = np.zeros((H, W), np.uint8)
    ignore[:, 390:] = 255
    assert detect_changes(before, after, ignore=ignore) == []


def test_steady_frame_removes_one_frame_flicker():
    frames = [_shelf(i) for i in range(5)]
    frames[2] = np.full_like(frames[2], 255)
    assert np.abs(steady_frame(frames).astype(int) - _shelf(0).astype(int)).mean() < 5


class _FakePeople:
    """Stands in for vision.people.PeopleDetector: returns queued results."""

    def __init__(self, results):
        self.results = list(results)

    def detect(self, frame):
        return self.results.pop(0)


def _people(fraction: float, hands: int = 0) -> People:
    blob = np.array([[[10, 10]], [[40, 10]], [[40, 40]], [[10, 40]]], np.int32)
    return People(mask=np.zeros((H, W), np.uint8), fraction=fraction,
                  hands=[[(0, 0)] * 21] * hands, hand_boxes=[(0, 0, 50, 50)] * hands, person_outlines=[blob])


def test_segmenter_speckle_is_not_someone_in_view(monkeypatch):
    monkeypatch.setattr("vision.hands.DOOR_OPEN_RELEARN_S", 0.0)
    td = TripDetector(_FakePeople([_people(0.005)] * 3))
    td.on_door_open()
    for _ in range(3):
        assert td.process_frame(_shelf())["hand_present"] is False
        assert td.motion_boxes == []   # the main loop treats boxes as "not quiet" — speckle mustn't block it


def test_hand_enters_after_two_frames_and_leaves_after_debounce(monkeypatch):
    monkeypatch.setattr("vision.hands.DOOR_OPEN_RELEARN_S", 0.0)
    monkeypatch.setattr("vision.hands.HAND_GONE_DEBOUNCE_S", 0.0)
    td = TripDetector(_FakePeople([_people(0.2, hands=1)] * 2 + [_people(0.0)]))
    td.on_door_open()
    assert td.process_frame(_shelf())["hand_entered"] is False   # one frame could be a flicker
    assert td.process_frame(_shelf())["hand_entered"] is True
    assert td.motion_boxes
    assert td.process_frame(_shelf())["hand_left"] is True


def test_mediapipe_detector_ignores_an_empty_shelf():
    people = pytest.importorskip("vision.people")
    try:
        detector = people.PeopleDetector()
    except Exception as e:   # no mediapipe, or the models can't be downloaded offline
        pytest.skip(f"MediaPipe unavailable: {e}")
    try:
        for _ in range(3):
            found = detector.detect(_shelf())
        assert not found.present and not found.hands
    finally:
        detector.close()
