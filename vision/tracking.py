"""Decide what happened to known items between two photos. Section 5.

1. For each known item, compare a patch at its last position in the before
   and after photos. Unchanged patch -> the item is still there. (An
   untouched item produces no changed region, so absence from the diff must
   not be read as "gone".)
2. Changed patch -> the item left that spot. Changed regions covering such a
   spot are where it *was*; every other changed region is something that
   *appeared*.
3. Appeared regions are matched to the items that left (color histogram +
   distance, Hungarian algorithm) -> moves. Unmatched appearances are new
   items; unmatched departures are vanished (removed, or now hidden — fusion
   checks against the scale).

One camera can't tell identical products apart if they swap, or see fully
hidden items; fusion (section 6) reconciles against the scale.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

from vision.change import ChangedRegion

PATCH_FRACTION = 0.08          # patch side, as a fraction of frame width, sampled at an item's center
PATCH_CHANGE_THRESHOLD = 20.0  # mean gray-level difference that means "different thing here now"
MATCH_COST_THRESHOLD = 0.55    # combined cost above this = not the same item


@dataclass
class KnownItem:
    item_id: int
    position: tuple[float, float]         # normalized (0-1) frame coordinates of its center
    color_hist: np.ndarray | None = None  # from color_histogram() on the before photo


@dataclass
class TrackingResult:
    moved: list[tuple[int, ChangedRegion]]  # item_id, region it moved to
    vanished_item_ids: list[int]
    new_regions: list[ChangedRegion]


def color_histogram(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = bbox
    hsv = cv2.cvtColor(frame[y:y + h, x:x + w], cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def normalized_position(bbox: tuple[int, int, int, int], frame_shape: tuple[int, ...]) -> tuple[float, float]:
    x, y, w, h = bbox
    frame_h, frame_w = frame_shape[:2]
    return ((x + w / 2) / frame_w, (y + h / 2) / frame_h)


def patch_box(position: tuple[float, float], frame_shape: tuple[int, ...]) -> tuple[int, int, int, int]:
    frame_h, frame_w = frame_shape[:2]
    side = max(int(frame_w * PATCH_FRACTION), 8)
    cx, cy = int(position[0] * frame_w), int(position[1] * frame_h)
    x = min(max(cx - side // 2, 0), frame_w - side)
    y = min(max(cy - side // 2, 0), frame_h - side)
    return x, y, side, side


def _patch_changed(before: np.ndarray, after: np.ndarray, box: tuple[int, int, int, int]) -> bool:
    x, y, w, h = box
    b = cv2.cvtColor(before[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(np.float32)
    a = cv2.cvtColor(after[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.mean(np.abs(a - b))) > PATCH_CHANGE_THRESHOLD


def _contains(region: ChangedRegion, position: tuple[float, float], frame_shape: tuple[int, ...]) -> bool:
    frame_h, frame_w = frame_shape[:2]
    px, py = position[0] * frame_w, position[1] * frame_h
    x, y, w, h = region.bbox
    return x <= px <= x + w and y <= py <= y + h


def match(
    known_items: list[KnownItem],
    regions: list[ChangedRegion],
    before_frame: np.ndarray,
    after_frame: np.ndarray,
) -> TrackingResult:
    shape = after_frame.shape
    departed = [k for k in known_items if _patch_changed(before_frame, after_frame, patch_box(k.position, shape))]

    appeared = [r for r in regions if not any(_contains(r, k.position, shape) for k in departed)]

    moved: list[tuple[int, ChangedRegion]] = []
    matched_items: set[int] = set()
    matched_regions: set[int] = set()
    if departed and appeared:
        hists = [color_histogram(after_frame, r.bbox) for r in appeared]
        cost = np.array([[_cost(k, r, h, shape) for r, h in zip(appeared, hists)] for k in departed])
        for i, j in zip(*linear_sum_assignment(cost)):
            if cost[i, j] <= MATCH_COST_THRESHOLD:
                moved.append((departed[i].item_id, appeared[j]))
                matched_items.add(i)
                matched_regions.add(j)

    return TrackingResult(
        moved=moved,
        vanished_item_ids=[k.item_id for i, k in enumerate(departed) if i not in matched_items],
        new_regions=[r for j, r in enumerate(appeared) if j not in matched_regions],
    )


def _cost(known: KnownItem, region: ChangedRegion, region_hist: np.ndarray, frame_shape: tuple[int, ...]) -> float:
    pos = normalized_position(region.bbox, frame_shape)
    dist = ((pos[0] - known.position[0]) ** 2 + (pos[1] - known.position[1]) ** 2) ** 0.5
    if known.color_hist is None:
        appearance = 0.5
    else:
        appearance = 1.0 - float(cv2.compareHist(known.color_hist, region_hist, cv2.HISTCMP_CORREL))
        appearance = max(0.0, min(appearance, 1.0))
    return 0.3 * dist + 0.7 * appearance
