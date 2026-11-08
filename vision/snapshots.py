"""The photos the fridge loop takes of new items — the crop that goes (or would go) to
Gemini — kept in data/snapshots/ with what came of each, for the live camera page
(GET /vision) to show.

Each snapshot is <time>.jpg plus <time>.json: when, how much the scale said, and
Gemini's answer (or that identification was off). The .json is written twice: once
when the photo is taken ("asking Gemini") and again with the answer.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"
NAME_RE = re.compile(r"^\d{8}-\d{6}(-\d+)?\.jpg$")


def save(image: np.ndarray, grams: float | None = None) -> Path:
    """Write the photo (never overwriting one taken the same second) and mark it pending."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path, n = SNAPSHOT_DIR / f"{stamp}.jpg", 1
    while path.exists():
        path, n = SNAPSHOT_DIR / f"{stamp}-{n}.jpg", n + 1
    cv2.imwrite(str(path), image)
    _write(path, {"at": time.time(), "grams": grams, "status": "pending"})
    return path


def record(path: Path, info: dict) -> None:
    """What came of the snapshot: Gemini's answer, or that identification was off."""
    meta = _read(path)
    meta.update(
        status="skipped" if info.get("skipped") else "named",
        item_name=None if info.get("skipped") else info.get("item_name"),
        confidence=info.get("confidence"),
        needs_confirmation=bool(info.get("needs_confirmation")),
    )
    _write(path, meta)


def recent(limit: int = 12) -> list[dict]:
    """Newest first: {"name", "at", "grams", "status", "item_name", "confidence", "needs_confirmation"}."""
    if not SNAPSHOT_DIR.is_dir():
        return []
    photos = sorted((p for p in SNAPSHOT_DIR.glob("*.jpg") if NAME_RE.match(p.name)), key=_order, reverse=True)
    return [{"name": p.name, **_read(p)} for p in photos[:limit]]


def _order(photo: Path) -> tuple[str, int]:
    """Taken-at order: the time stamp, then the counter of a second photo in the same second."""
    stamp, _, n = photo.stem.partition("-")[2].partition("-")
    return photo.stem[:8] + stamp, int(n or 0)


def path_for(name: str) -> Path | None:
    """The photo's file, if `name` is one of ours (never a path outside the folder)."""
    if not NAME_RE.match(name):
        return None
    path = SNAPSHOT_DIR / name
    return path if path.is_file() else None


def _read(photo: Path) -> dict:
    try:
        return json.loads(photo.with_suffix(".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"at": photo.stat().st_mtime, "status": "unknown"}  # older photos, from before the .json


def _write(photo: Path, meta: dict) -> None:
    photo.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
