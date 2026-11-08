"""Hand trips: someone reaches in, then leaves -> measure once. Section 2.

Primary signal: MediaPipe people detection (vision/people.py) — a hand or an arm
in view. It ignores camera noise, auto-exposure drift, and the items themselves,
which frame-to-frame motion can't tell apart from a hand.

Movement between consecutive frames counts too (MediaPipe can miss a hand reaching in from
the edge), and is the only signal when MediaPipe is unavailable (or for the simulator's drawn
"hand").

"Hand arrived" needs ENTER_FRAMES consecutive frames, so a one-frame flicker
can't start a trip; "hand left" needs HAND_GONE_DEBOUNCE_S with nobody in view.
"""
from __future__ import annotations

import time

import cv2
import numpy as np

HAND_GONE_DEBOUNCE_S = 0.6
DOOR_OPEN_RELEARN_S = 1.0       # ignore the door-light flicker right after opening
ENTER_FRAMES = 2
MIN_MOTION_AREA = 4000          # motion fallback: px of changed pixels between frames that counts as a hand
MOTION_PIXEL_THRESHOLD = 25
MIN_MOTION_BOX_AREA = 1500      # ignore specks when reporting where the motion is

Box = tuple[int, int, int, int]


class TripDetector:
    def __init__(self, people=None, min_motion_area: int = MIN_MOTION_AREA):
        """`people`: a vision.people.PeopleDetector, or None to use motion."""
        self.people = people
        self.min_motion_area = min_motion_area
        self._prev_gray: np.ndarray | None = None
        self._hand_present = False
        self._present_streak = 0
        self._last_seen_ts: float | None = None
        self._ignore_until: float = 0.0
        # For the live vision view: where the hand/person/motion is in the latest frame.
        self.motion_boxes: list[Box] = []
        self.last_people = None  # vision.people.People from the latest frame, when MediaPipe is in use

    @property
    def method(self) -> str:
        return "mediapipe" if self.people is not None else "motion"

    def on_door_open(self) -> None:
        self._ignore_until = time.monotonic() + DOOR_OPEN_RELEARN_S
        self._hand_present = False
        self._present_streak = 0
        self._last_seen_ts = None
        self._prev_gray = None

    def motion_area(self, frame: np.ndarray) -> int:
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0)
        prev, self._prev_gray = self._prev_gray, gray
        if prev is None or prev.shape != gray.shape:
            self.motion_boxes = []
            return 0
        _, mask = cv2.threshold(cv2.absdiff(prev, gray), MOTION_PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)
        area = int(cv2.countNonZero(mask))
        if area >= MIN_MOTION_BOX_AREA:
            blobs = cv2.dilate(mask, np.ones((15, 15), np.uint8))  # merge a hand's pieces into one box
            contours, _ = cv2.findContours(blobs, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            self.motion_boxes = [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) >= MIN_MOTION_BOX_AREA]
        else:
            self.motion_boxes = []
        return area

    def _someone_in_view(self, frame: np.ndarray) -> bool:
        if self.people is None:
            return self.motion_area(frame) >= self.min_motion_area
        found = self.people.detect(frame)
        self.last_people = found
        # MediaPipe misses a hand that only reaches in from the edge to set something small down,
        # so a hand-sized movement counts too. A false alarm costs nothing: the trip it starts
        # just finds nothing changed.
        moving = self.motion_area(frame) >= self.min_motion_area
        motion = self.motion_boxes if moving else []
        # Below the presence threshold, outlines are segmenter speckle (shiny packaging, shadows).
        self.motion_boxes = (found.hand_boxes + [cv2.boundingRect(c) for c in found.person_outlines]
                             if found.present else []) + motion
        return found.present or moving

    def process_frame(self, frame: np.ndarray) -> dict:
        """Returns {"hand_entered", "hand_left", "hand_present"} for this frame;
        hand_left fires once, after the debounce window."""
        now = time.monotonic()
        seen = self._someone_in_view(frame)
        if now < self._ignore_until:
            return {"hand_entered": False, "hand_left": False, "hand_present": False}

        hand_entered = hand_left = False
        if seen:
            self._last_seen_ts = now
            self._present_streak += 1
            if not self._hand_present and self._present_streak >= ENTER_FRAMES:
                self._hand_present = hand_entered = True
        else:
            self._present_streak = 0
            if self._hand_present and self._last_seen_ts is not None and now - self._last_seen_ts >= HAND_GONE_DEBOUNCE_S:
                hand_left = True
                self._hand_present = False

        return {"hand_entered": hand_entered, "hand_left": hand_left, "hand_present": self._hand_present}

    def is_hand_present(self) -> bool:
        return self._hand_present
