"""Live view of what the vision pipeline is doing, for testing.

The fridge loop reports into the shared `view`; the backend serves the latest
annotated frame at GET /api/vision/frame.jpg, and the simulated fridge's
control page shows it.

  orange  you — person outline + hand skeleton (MediaPipe), or motion boxes
  cyan    what changed after the hand left (the item put in / taken out)
  green   the picture sent to Gemini, then Gemini's answer
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np

ORANGE, CYAN, GREEN, YELLOW, WHITE = (0, 140, 255), (255, 220, 0), (80, 220, 60), (0, 210, 255), (255, 255, 255)
CHANGE_SHOW_S = 4.0
GEMINI_FLASH_S = 1.5
GEMINI_RESULT_S = 6.0
JPEG_QUALITY = 75

Box = tuple[int, int, int, int]


@dataclass
class _Gemini:
    box: Box | None
    started: float
    result: str | None = None
    confident: bool = True


class VisionView:
    def __init__(self):
        self._lock = threading.Lock()
        self._jpeg: bytes | None = None
        self._changes: list[Box] = []
        self._changes_until = 0.0
        self._gemini: _Gemini | None = None
        self._last_frame: np.ndarray | None = None
        self._last_status = ""

    # ------------------------------------------------------------ reporting
    def frame(self, frame: np.ndarray, *, door_open: bool, hand_boxes: list[Box], status: str, people=None) -> None:
        """Called every loop tick with the current camera frame. `people` (vision.people.People)
        draws person outlines and hand skeletons; otherwise `hand_boxes` are drawn as boxes."""
        with self._lock:
            self._last_frame, self._last_status = frame, status
            self._render(frame, door_open, hand_boxes, status, people)

    def changes(self, boxes: list[Box]) -> None:
        with self._lock:
            self._changes = list(boxes)
            self._changes_until = time.monotonic() + CHANGE_SHOW_S

    def gemini_sending(self, box: Box | None) -> None:
        """Flash green now — the loop then blocks on the Gemini call, so render immediately."""
        with self._lock:
            self._gemini = _Gemini(box, time.monotonic())
            if self._last_frame is not None:
                self._render(self._last_frame, True, [], "Sending snapshot to Gemini...")

    def gemini_result(self, info: dict) -> None:
        with self._lock:
            if self._gemini is None:
                return
            if info.get("skipped"):
                self._gemini.result = "Snapshot ready (Gemini off) - saved to data/snapshots"
                self._gemini.confident = True
            else:
                confidence = info.get("confidence") or 0
                self._gemini.result = f"Gemini: {info.get('item_name', '?')} ({confidence:.0%})"
                self._gemini.confident = not info.get("needs_confirmation")
            self._gemini.started = time.monotonic()  # keep the answer up for a few seconds

    def jpeg(self) -> bytes | None:
        with self._lock:
            return self._jpeg

    # ------------------------------------------------------------- drawing
    def _render(self, frame: np.ndarray, door_open: bool, hand_boxes: list[Box], status: str, people=None) -> None:
        img = frame.copy()
        now = time.monotonic()
        if not door_open:
            img = (img * 0.35).astype(np.uint8)
            _banner(img, "Door closed - open it on the control page", WHITE, top=True)
        if people is not None:
            _draw_people(img, people)
        else:
            for box in hand_boxes:
                _box(img, box, ORANGE, "hand")
        if now < self._changes_until:
            for box in self._changes:
                _box(img, box, CYAN, "changed")

        g = self._gemini
        if g is not None:
            age = now - g.started
            if g.result is None and age < GEMINI_FLASH_S * 4:
                cv2.rectangle(img, (0, 0), (img.shape[1] - 1, img.shape[0] - 1), GREEN, 10)
                if g.box:
                    _box(img, g.box, GREEN, "sent to Gemini", thickness=4)
                _banner(img, "SNAPSHOT -> GEMINI", GREEN, top=True)
            elif g.result is not None and age < GEMINI_RESULT_S:
                color = GREEN if g.confident else YELLOW
                if g.box:
                    _box(img, g.box, color, "", thickness=3)
                text = g.result if g.confident else g.result + " - not sure, check the fridge screen"
                _banner(img, text, color, top=True)

        _banner(img, status, WHITE, top=False)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if ok:
            self._jpeg = buf.tobytes()


def _draw_people(img: np.ndarray, people) -> None:
    """Tinted person outline (arms, sleeves, anyone in view) plus each hand's joint skeleton."""
    from vision.people import HAND_CONNECTIONS

    if people.present and people.person_outlines:
        tint = img.copy()
        cv2.drawContours(tint, people.person_outlines, -1, ORANGE, -1)
        cv2.addWeighted(tint, 0.25, img, 0.75, 0, dst=img)
        cv2.drawContours(img, people.person_outlines, -1, ORANGE, 2)
        x, y, _, _ = cv2.boundingRect(max(people.person_outlines, key=cv2.contourArea))
        _box_label(img, x, y, "person" if not people.hands else f"hand{'s' if len(people.hands) > 1 else ''}", ORANGE)
    for points in people.hands:
        for a, b in HAND_CONNECTIONS:
            cv2.line(img, points[a], points[b], WHITE, 2, cv2.LINE_AA)
        for p in points:
            cv2.circle(img, p, 3, ORANGE, -1, cv2.LINE_AA)


def _box_label(img: np.ndarray, x: int, y: int, label: str, color) -> None:
    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
    ty = max(y - 6, th + 4)
    cv2.rectangle(img, (x, ty - th - 4), (x + tw + 8, ty + 4), color, -1)
    cv2.putText(img, label, (x + 4, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 1, cv2.LINE_AA)


def _box(img: np.ndarray, box: Box, color, label: str, thickness: int = 2) -> None:
    x, y, w, h = box
    cv2.rectangle(img, (x, y), (x + w, y + h), color, thickness)
    if label:
        _box_label(img, x, y, label, color)


def _banner(img: np.ndarray, text: str, color, top: bool) -> None:
    if not text:
        return
    h = 30
    y0 = 0 if top else img.shape[0] - h
    overlay = img.copy()
    cv2.rectangle(overlay, (0, y0), (img.shape[1], y0 + h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, img, 0.4, 0, dst=img)
    # Shrink long lines (status + shelf weights) to fit the frame width.
    scale = 0.6
    while scale > 0.35 and cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)[0][0] > img.shape[1] - 20:
        scale -= 0.05
    cv2.putText(img, text, (10, y0 + 21), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


view = VisionView()
