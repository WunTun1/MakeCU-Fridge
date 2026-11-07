import cv2
import numpy as np

from vision.debug import ORANGE, VisionView
from vision.hands import TripDetector

H, W = 480, 640


def _frame(hand_x: int | None) -> np.ndarray:
    img = np.full((H, W, 3), 40, np.uint8)
    if hand_x is not None:
        cv2.ellipse(img, (hand_x, 240), (60, 45), 0, 0, 360, (120, 165, 225), -1)
    return img


def test_moving_hand_gets_a_motion_box():
    td = TripDetector()
    td.process_frame(_frame(None))
    td.process_frame(_frame(300))
    assert td.motion_boxes, "hand appearing should produce a motion box"
    x, y, w, h = td.motion_boxes[0]
    assert x < 300 < x + w and y < 240 < y + h

    td.process_frame(_frame(300))  # hand holds still -> no motion
    assert td.motion_boxes == []


def test_view_draws_hand_boxes_and_produces_a_jpeg():
    view = VisionView()
    view.frame(_frame(300), door_open=True, hand_boxes=[(200, 180, 200, 120)], status="Hand in view")
    img = cv2.imdecode(np.frombuffer(view.jpeg(), np.uint8), cv2.IMREAD_COLOR)
    edge = img[180, 300].astype(int)  # a pixel on the box's top edge
    assert np.abs(edge - np.array(ORANGE)).sum() < 90


def test_gemini_skipped_is_labeled_not_named():
    view = VisionView()
    view.frame(_frame(None), door_open=True, hand_boxes=[], status="")
    view.gemini_sending((100, 100, 50, 50))
    view.gemini_result({"skipped": True})
    assert "Gemini off" in view._gemini.result
