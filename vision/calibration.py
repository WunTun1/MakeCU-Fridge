"""Pixel -> physical shelf coordinates via a 4-point homography. Section 13
(robotic retrieval, stretch goal) — not needed for inventory tracking itself."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np


class ShelfCalibration:
    """Maps camera pixel coordinates to millimeter shelf coordinates for one shelf.

    `image_points` and `world_points_mm` are four matching corresponding points
    (e.g. the shelf's four corners), collected once during setup.
    """

    def __init__(self, homography: np.ndarray):
        self.homography = homography

    @classmethod
    def from_points(cls, image_points: list[tuple[float, float]], world_points_mm: list[tuple[float, float]]) -> "ShelfCalibration":
        if len(image_points) != 4 or len(world_points_mm) != 4:
            raise ValueError("Homography calibration needs exactly 4 point pairs")
        src = np.array(image_points, dtype=np.float32)
        dst = np.array(world_points_mm, dtype=np.float32)
        homography, _ = cv2.findHomography(src, dst)
        if homography is None:
            raise RuntimeError("Could not compute homography from the given points")
        return cls(homography)

    def pixel_to_mm(self, pixel: tuple[float, float]) -> tuple[float, float]:
        point = np.array([[pixel]], dtype=np.float32)
        transformed = cv2.perspectiveTransform(point, self.homography)
        x, y = transformed[0][0]
        return float(x), float(y)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.homography.tolist()))

    @classmethod
    def load(cls, path: str | Path) -> "ShelfCalibration":
        data = json.loads(Path(path).read_text())
        return cls(np.array(data, dtype=np.float32))
