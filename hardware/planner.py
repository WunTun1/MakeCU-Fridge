"""Safe retrieval planning (stretch). Section 13.

Converts a target shelf position into a motion plan, checking for other
active items in the path before handing off to the motor controller.
"""
from __future__ import annotations

from dataclasses import dataclass

from inventory.database import Database


@dataclass
class RetrievalPlan:
    item_id: int
    target_x_mm: float
    target_y_mm: float
    blocked_by: list[int]  # item_ids in the path, if any


def plan_retrieval(db: Database, item_id: int) -> RetrievalPlan:
    item = db.get_item(item_id)
    if item is None or item["status"] != "active":
        raise ValueError(f"item {item_id} is not an active fridge item")
    if item["position_x"] is None or item["position_y"] is None:
        raise ValueError(f"item {item_id} has no known shelf position")

    shelf_items = db.active_items(shelf=item["shelf"])
    blocked_by = [
        other["id"] for other in shelf_items
        if other["id"] != item_id
        and other["position_x"] is not None
        # Anything strictly between the item and the front of the shelf (y=0) is in the path.
        and other["position_y"] is not None
        and other["position_y"] < item["position_y"]
        and abs(other["position_x"] - item["position_x"]) < 0.1
    ]

    return RetrievalPlan(
        item_id=item_id,
        target_x_mm=item["position_x"],
        target_y_mm=item["position_y"],
        blocked_by=blocked_by,
    )
