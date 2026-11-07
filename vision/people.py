"""Find people — hands, arms, anyone — in a camera frame, with MediaPipe.

Two models run on every frame (~40 ms together on a laptop CPU):
  hand landmarker    21 joints per hand (drawn as a skeleton in the live view)
  person segmenter   which pixels belong to a person — skin, hair, sleeves — so an
                     arm reaching in counts even when the hand itself isn't visible

"Someone is reaching in" = a hand was found, or person pixels cover more than a
small share of the frame. Unlike frame-to-frame motion, this ignores camera
noise, auto-exposure shifts, and the items themselves (they aren't people).

The segmenter runs on a quarter-size frame: ~9 ms instead of ~35, and in testing
it also produced fewer false "person" pixels on an empty scene (MediaPipe's
multiclass body-part model was tried too: similar masks, but ~170 ms a frame).

Models (~8 MB) download on first use into data/models/ (git-ignored).
"""
from __future__ import annotations

import logging
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("refridge.vision.people")

MODELS_DIR = Path(__file__).resolve().parent.parent / "data" / "models"
HAND_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/"
                  "float16/latest/hand_landmarker.task")
SEGMENTER_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/image_segmenter/"
                       "selfie_segmenter/float16/latest/selfie_segmenter.tflite")

SEGMENT_SCALE = 0.25            # segment a quarter-size frame (faster, and fewer false positives)
PERSON_CONFIDENCE = 0.6         # per-pixel probability above which a pixel counts as a person
MIN_PERSON_FRACTION = 0.03      # person pixels needed (share of the frame) to count as "someone's here";
                                # an empty scene measured <= 0.010
MIN_PERSON_BLOB_FRACTION = 0.004  # ignore smaller specks when outlining people
HAND_DETECTION_CONFIDENCE = 0.5
HAND_PADDING_PX = 18            # grow each hand's outline a little so fingertips are covered

# Joint pairs of MediaPipe's 21-point hand model, for drawing the skeleton.
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
    (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (17, 18), (18, 19), (19, 20), (0, 17),
]

Box = tuple[int, int, int, int]
Point = tuple[int, int]


@dataclass
class People:
    """What the detector found in one frame."""
    mask: np.ndarray                    # uint8, 255 where a person (or hand) is
    fraction: float                     # share of the frame covered by people
    hands: list[list[Point]] = field(default_factory=list)   # 21 pixel points per hand
    hand_boxes: list[Box] = field(default_factory=list)
    person_outlines: list[np.ndarray] = field(default_factory=list)  # contours, for drawing

    @property
    def present(self) -> bool:
        return bool(self.hands) or self.fraction >= MIN_PERSON_FRACTION


def _ensure_model(url: str) -> Path:
    path = MODELS_DIR / url.rsplit("/", 1)[-1]
    if not path.exists():
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        log.info("Downloading %s (one time)...", path.name)
        tmp = path.with_suffix(path.suffix + ".part")
        urllib.request.urlretrieve(url, tmp)
        tmp.replace(path)
    return path


class PeopleDetector:
    """Stateful (video mode): call `detect` with frames in time order, from one thread."""

    def __init__(self):
        import mediapipe as mp  # optional dependency — callers fall back to motion if unavailable

        vision = mp.tasks.vision
        base = mp.tasks.BaseOptions
        self._mp = mp
        self._hands = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=base(model_asset_path=str(_ensure_model(HAND_MODEL_URL))),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=HAND_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=HAND_DETECTION_CONFIDENCE,
            min_tracking_confidence=HAND_DETECTION_CONFIDENCE,
        ))
        self._segmenter = vision.ImageSegmenter.create_from_options(vision.ImageSegmenterOptions(
            base_options=base(model_asset_path=str(_ensure_model(SEGMENTER_MODEL_URL))),
            running_mode=vision.RunningMode.VIDEO,
            output_confidence_masks=True,
            output_category_mask=False,
        ))
        self._last_ts = 0

    def _image(self, frame_bgr: np.ndarray):
        return self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))

    def detect(self, frame_bgr: np.ndarray) -> People:
        h, w = frame_bgr.shape[:2]
        image = self._image(frame_bgr)
        small = self._image(cv2.resize(frame_bgr, None, fx=SEGMENT_SCALE, fy=SEGMENT_SCALE, interpolation=cv2.INTER_AREA))
        # Video mode needs strictly increasing timestamps.
        ts = max(int(time.monotonic() * 1000), self._last_ts + 1)
        self._last_ts = ts

        person_prob = np.squeeze(self._segmenter.segment_for_video(small, ts).confidence_masks[0].numpy_view())
        person_prob = cv2.resize(person_prob, (w, h), interpolation=cv2.INTER_LINEAR)
        mask = np.where(person_prob > PERSON_CONFIDENCE, 255, 0).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

        hands: list[list[Point]] = []
        hand_boxes: list[Box] = []
        for landmarks in self._hands.detect_for_video(image, ts).hand_landmarks:
            points = [(int(p.x * w), int(p.y * h)) for p in landmarks]
            hands.append(points)
            hull = cv2.convexHull(np.array(points, dtype=np.int32))
            hand_mask = np.zeros_like(mask)
            cv2.fillConvexPoly(hand_mask, hull, 255)
            hand_mask = cv2.dilate(hand_mask, np.ones((HAND_PADDING_PX * 2 + 1,) * 2, np.uint8))
            mask = cv2.bitwise_or(mask, hand_mask)
            x, y, bw, bh = cv2.boundingRect(hull)
            hand_boxes.append((max(x - HAND_PADDING_PX, 0), max(y - HAND_PADDING_PX, 0),
                               bw + 2 * HAND_PADDING_PX, bh + 2 * HAND_PADDING_PX))

        min_blob = MIN_PERSON_BLOB_FRACTION * w * h
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outlines = [c for c in contours if cv2.contourArea(c) >= min_blob]
        return People(mask=mask, fraction=float(np.count_nonzero(mask)) / (w * h),
                      hands=hands, hand_boxes=hand_boxes, person_outlines=outlines)

    def close(self) -> None:
        self._hands.close()
        self._segmenter.close()


def make_detector() -> PeopleDetector | None:
    """The MediaPipe detector, or None (with a logged reason) if it can't load —
    the trip detector then falls back to frame-to-frame motion."""
    try:
        return PeopleDetector()
    except Exception as e:  # missing package, no network for the first model download, ...
        log.warning("MediaPipe people detection unavailable (%s); falling back to motion detection", e)
        return None
