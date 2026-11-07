"""Before/after photo comparison -> changed regions. Section 4.

Real cameras drift: auto-exposure and white balance re-adjust between the two
photos, and shadows move. A plain pixel difference reads all of that as
"changed". So, before comparing:
  1. the after photo's per-channel brightness is matched to the before photo,
  2. colors are compared in LAB with lightness at half weight (a shadow mostly
     changes lightness; a different object usually changes color too),
  3. the threshold adapts to this pair's measured noise,
and pixels covered by a person can be ignored.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MIN_AREA_FRACTION = 0.002   # ignore regions smaller than 0.2% of the frame (~600 px at 640x480)
BASE_THRESHOLD = 28.0       # minimum per-pixel difference that can count as a change
NOISE_K = 6.0               # threshold also clears median + K * MAD of this pair's differences
LIGHTNESS_WEIGHT = 0.5


@dataclass
class ChangedRegion:
    bbox: tuple[int, int, int, int]  # x, y, w, h
    area: int

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return (x + w / 2, y + h / 2)


def match_exposure(after: np.ndarray, before: np.ndarray, valid: np.ndarray | None = None) -> np.ndarray:
    """Map each channel of `after` onto `before` with a gain and an offset fitted on the 10th/90th
    percentiles — undoes auto-exposure and white-balance drift (which shift and stretch brightness)."""
    out = after.astype(np.float32)
    for c in range(3):
        a = after[..., c] if valid is None else after[..., c][valid]
        b = before[..., c] if valid is None else before[..., c][valid]
        a_lo, a_hi = np.percentile(a, (10, 90))
        b_lo, b_hi = np.percentile(b, (10, 90))
        if a_hi - a_lo > 4:
            out[..., c] = (out[..., c] - a_lo) * (b_hi - b_lo) / (a_hi - a_lo) + b_lo
    return np.clip(out, 0, 255).astype(np.uint8)


def difference_map(before: np.ndarray, after: np.ndarray, ignore: np.ndarray | None = None) -> np.ndarray:
    """Per-pixel change strength (float32), exposure-compensated."""
    valid = None if ignore is None else ignore == 0
    after = match_exposure(after, before, valid)
    lab_b = cv2.cvtColor(cv2.GaussianBlur(before, (7, 7), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    lab_a = cv2.cvtColor(cv2.GaussianBlur(after, (7, 7), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    d = np.abs(lab_a - lab_b)
    return LIGHTNESS_WEIGHT * d[..., 0] + d[..., 1] + d[..., 2]


def detect_changes(
    before: np.ndarray,
    after: np.ndarray,
    min_area: int | None = None,
    ignore: np.ndarray | None = None,
) -> list[ChangedRegion]:
    """`ignore`: optional uint8 mask (non-zero = skip), e.g. where a person is."""
    h, w = before.shape[:2]
    diff = difference_map(before, after, ignore)
    sample = diff if ignore is None else diff[ignore == 0]
    median = float(np.median(sample))
    mad = float(np.median(np.abs(sample - median)))
    threshold = max(BASE_THRESHOLD, median + NOISE_K * mad)

    mask = np.where(diff > threshold, 255, 0).astype(np.uint8)
    if ignore is not None:
        mask[ignore > 0] = 0
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))    # drop speckle
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))   # join an object's pieces
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_area = min_area if min_area is not None else int(MIN_AREA_FRACTION * w * h)
    regions: list[ChangedRegion] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area >= min_area:
            regions.append(ChangedRegion(bbox=cv2.boundingRect(c), area=int(area)))
    return regions


def steady_frame(frames: list[np.ndarray]) -> np.ndarray:
    """Per-pixel median of a few consecutive frames: removes sensor noise and one-frame flicker."""
    if len(frames) == 1:
        return frames[0]
    return np.median(np.stack(frames), axis=0).astype(np.uint8)
