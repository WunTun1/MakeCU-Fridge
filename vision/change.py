"""Before/after photo comparison -> changed regions. Section 4."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MIN_CONTOUR_AREA = 600  # px — filters out tiny noise contours


@dataclass
class ChangedRegion:
    bbox: tuple[int, int, int, int]  # x, y, w, h
    area: int

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.bbox
        return (x + w / 2, y + h / 2)


def detect_changes(before: np.ndarray, after: np.ndarray, min_area: int = MIN_CONTOUR_AREA) -> list[ChangedRegion]:
    diff = cv2.absdiff(before, after)
    gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    _, mask = cv2.threshold(blur, 30, 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    regions: list[ChangedRegion] = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        bbox = cv2.boundingRect(c)
        regions.append(ChangedRegion(bbox=bbox, area=int(area)))
    return regions
