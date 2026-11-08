"""Fusion: weight delta + camera observation -> a decision for one shelf, one
hand trip. See ReFridge_Architecture.md section 6 and 6b for the table this
implements.

This module is pure logic — it takes already-computed camera observations
(what the tracker decided vanished, moved, or is a brand-new region) and the
before/after weight for a shelf, and returns a list of `Decision`s. The
caller (main loop / demo) is responsible for turning each Decision into
database writes via inventory.events, and for calling the AI classifier to
name "add" / "swap" regions before doing so.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any, Optional

from sensors.scale import is_significant_change

# Typical package weights (grams) used to split a combined weight across
# several items added in one trip when hardware can't tell them apart
# (section 6b, step 2). Rough guesses — refined by self-correction once an
# item is later removed and its exact weight is measured.
TYPICAL_PACKAGE_WEIGHTS_G = {
    "milk": 1050, "yogurt": 500, "eggs": 600, "butter": 450, "cheese": 300,
    "bread": 500, "juice": 1000, "leafy greens": 150, "berries": 350,
}
SPLIT_SUM_TOLERANCE_PCT = 0.15
NOISE_RECONCILE_TOLERANCE_G = 20.0


@dataclass
class VanishedItem:
    item_id: int
    product_id: int
    grams: float


@dataclass
class NewRegion:
    index: int
    position: tuple[float, float]
    bbox: tuple[int, int, int, int] | None = None
    crop_path: str | None = None


@dataclass
class MovedItem:
    item_id: int
    new_position: tuple[float, float]


@dataclass
class CameraObservation:
    moved: list[MovedItem] = field(default_factory=list)
    vanished: list[VanishedItem] = field(default_factory=list)
    new_regions: list[NewRegion] = field(default_factory=list)


@dataclass
class Decision:
    kind: str  # noop|move|remove|consume|add|swap|restock_hidden|needs_review
    item_id: Optional[int] = None
    product_id: Optional[int] = None
    grams: float = 0.0
    position: Optional[tuple[float, float]] = None
    region: Optional[NewRegion] = None
    note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


def _closest_vanishing_subset(vanished: list[VanishedItem], target: float) -> list[VanishedItem]:
    """Some items may only be hidden, not removed. Find the subset of
    `vanished` whose total weight is closest to the measured loss."""
    best: list[VanishedItem] = []
    best_diff = float("inf")
    for r in range(1, len(vanished) + 1):
        for combo in itertools.combinations(vanished, r):
            diff = abs(sum(v.grams for v in combo) - target)
            if diff < best_diff:
                best_diff = diff
                best = list(combo)
    return best


def _split_combined_weight(total: float, item_names: list[str]) -> list[float]:
    """Section 6b step 2: split a combined add-weight using typical package
    weights when several new regions appear with one weight reading."""
    typical = [TYPICAL_PACKAGE_WEIGHTS_G.get(n.lower(), total / len(item_names)) for n in item_names]
    typical_sum = sum(typical)
    if typical_sum > 0 and abs(typical_sum - total) <= typical_sum * SPLIT_SUM_TOLERANCE_PCT:
        scale = total / typical_sum
        return [t * scale for t in typical]
    # Typical weights don't add up convincingly — split evenly and flag for review.
    return [total / len(item_names)] * len(item_names)


def _adds(new_regions: list[NewRegion], grams: float) -> list[Decision]:
    """One add per new region the camera saw, sharing `grams` (what the scale says came in;
    0 when it didn't move, so the amount is left for the person to set)."""
    each = max(grams, 0.0) / len(new_regions)
    return [Decision(kind="add", grams=each, region=r, position=r.position) for r in new_regions]


def reconcile_shelf(
    shelf: int,
    weight_before: float,
    weight_after: float,
    observation: CameraObservation,
) -> list[Decision]:
    delta = weight_after - weight_before
    significant = is_significant_change(delta, weight_before)
    decisions: list[Decision] = []

    for moved in observation.moved:
        decisions.append(Decision(kind="move", item_id=moved.item_id, position=moved.new_position))

    vanished = observation.vanished
    new_regions = observation.new_regions

    # Whether something was added is the camera's call alone: a new region is a new item, whatever
    # the scale did. The scale only says how much it weighs.
    if not significant:
        if vanished and new_regions:
            # Something left and something new arrived at about the same weight: a swap.
            for v in vanished:
                decisions.append(Decision(kind="remove", item_id=v.item_id, product_id=v.product_id, grams=v.grams))
            decisions.extend(_adds(new_regions, sum(v.grams for v in vanished) + delta))
        elif new_regions:
            decisions.extend(_adds(new_regions, 0.0))
        elif vanished:
            decisions.append(Decision(
                kind="needs_review", note="camera saw an item go but the weight did not change",
                meta={"vanished": [v.item_id for v in vanished], "new_region_count": 0},
            ))
        return decisions

    if vanished and new_regions:
        # Swap: an item left and a (possibly different) item arrived. This can
        # net out to a weight gain, loss, or even ~0 depending on the two
        # items' weights, so it's checked before the gain/loss branches.
        removed_weight = sum(v.grams for v in vanished)
        for v in vanished:
            decisions.append(Decision(kind="remove", item_id=v.item_id, product_id=v.product_id, grams=v.grams))
        decisions.extend(_adds(new_regions, delta + removed_weight))
        return decisions

    if delta < 0:
        loss = -delta
        if new_regions:
            decisions.extend(_adds(new_regions, 0.0))  # seen arriving while something else was used
        if not vanished:
            # Nothing gone visually -> someone used some of a still-visible item.
            decisions.append(Decision(
                kind="consume", grams=loss,
                note="weight dropped with no item gone — assign to a visible item heavy enough",
                meta={"shelf": shelf},
            ))
            return decisions

        total_vanished = sum(v.grams for v in vanished)
        if abs(total_vanished - loss) <= max(NOISE_RECONCILE_TOLERANCE_G, total_vanished * 0.1):
            for v in vanished:
                decisions.append(Decision(kind="remove", item_id=v.item_id, product_id=v.product_id, grams=v.grams))
        else:
            best_subset = _closest_vanishing_subset(vanished, loss)
            subset_ids = {v.item_id for v in best_subset}
            for v in best_subset:
                decisions.append(Decision(kind="remove", item_id=v.item_id, product_id=v.product_id, grams=v.grams))
            remaining_diff = loss - sum(v.grams for v in best_subset)
            if abs(remaining_diff) > NOISE_RECONCILE_TOLERANCE_G:
                decisions.append(Decision(
                    kind="needs_review",
                    note="removed items don't fully account for the weight drop",
                    meta={"matched": list(subset_ids), "unmatched_grams": remaining_diff},
                ))
        return decisions

    # delta > 0, nothing vanished. Only what the camera saw is added; weight alone adds nothing.
    if new_regions:
        decisions.extend(_adds(new_regions, delta))
    return decisions
