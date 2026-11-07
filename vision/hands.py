"""Hand / motion detection -> trip start/end. Section 2.

"Hand present" = significant motion between consecutive frames. We use
frame-to-frame differencing rather than a learned background model (MOG2):
a background model treats a freshly placed item as foreground until it
slowly learns it (tens of seconds), which would keep "hand present" stuck on
after every add. A static new item produces no frame-to-frame motion.

"Hand gone" = no significant motion for HAND_GONE_DEBOUNCE_S. Swap in
MediaPipe Hands later if shadows / door-light cause false triggers; nothing
outside this module needs to change (same TripDetector interface).
"""
from __future__ import annotations

import time

import cv2
import numpy as np

HAND_GONE_DEBOUNCE_S = 0.5
DOOR_OPEN_RELEARN_S = 1.0       # ignore the door-light flicker right after opening
MIN_MOTION_AREA = 4000          # px of changed pixels between frames that counts as a hand
MOTION_PIXEL_THRESHOLD = 25


class TripDetector:
    def __init__(self, min_motion_area: int = MIN_MOTION_AREA):
        self.min_motion_area = min_motion_area
        self._prev_gray: np.ndarray | None = None
        self._hand_present = False
        self._last_motion_ts: float | None = None
        self._ignore_until: float = 0.0

    def on_door_open(self) -> None:
        self._ignore_until = time.monotonic() + DOOR_OPEN_RELEARN_S
        self._hand_present = False
        self._last_motion_ts = None
        self._prev_gray = None

    def motion_area(self, frame: np.ndarray) -> int:
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0)
        prev, self._prev_gray = self._prev_gray, gray
        if prev is None or prev.shape != gray.shape:
            return 0
        _, mask = cv2.threshold(cv2.absdiff(prev, gray), MOTION_PIXEL_THRESHOLD, 255, cv2.THRESH_BINARY)
        return int(cv2.countNonZero(mask))

    def process_frame(self, frame: np.ndarray) -> dict:
        """Returns {"hand_entered", "hand_left", "hand_present"} for this frame;
        hand_left fires once, after the debounce window."""
        now = time.monotonic()
        area = self.motion_area(frame)
        if now < self._ignore_until:
            return {"hand_entered": False, "hand_left": False, "hand_present": False}

        hand_entered = hand_left = False
        if area >= self.min_motion_area:
            self._last_motion_ts = now
            hand_entered = not self._hand_present
            self._hand_present = True
        elif self._hand_present and self._last_motion_ts is not None:
            if now - self._last_motion_ts >= HAND_GONE_DEBOUNCE_S:
                hand_left = True
                self._hand_present = False

        return {"hand_entered": hand_entered, "hand_left": hand_left, "hand_present": self._hand_present}

    def is_hand_present(self) -> bool:
        return self._hand_present
