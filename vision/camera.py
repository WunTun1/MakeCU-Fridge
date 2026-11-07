"""Frame capture. Section 2 / 4.

`Camera` opens a local webcam directly. `RemoteCamera` fetches the latest
snapshot from a Raspberry Pi running pi_node/camera_server.py instead — same
read_frame() interface, so vision/hands.py, change.py, and tracking.py don't
care which one they're given. `make_camera()` picks between them based on
whether PI_AGENT_URL is set (see .env.example).
"""
from __future__ import annotations

import os

import cv2
import numpy as np
import requests

REMOTE_FRAME_TIMEOUT_S = 3


class Camera:
    def __init__(self, index: int | None = None):
        self.index = index if index is not None else int(os.getenv("CAMERA_INDEX", "0"))
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open camera index {self.index}")

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def read_frame(self) -> np.ndarray:
        if self._cap is None:
            raise RuntimeError("Camera not opened — call open() first")
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("Failed to read a frame from the camera")
        return frame

    def __enter__(self) -> "Camera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class RemoteCamera:
    """Pulls the latest JPEG snapshot from a Pi's camera_server over HTTP."""

    def __init__(self, agent_url: str | None = None):
        self.agent_url = (agent_url or os.getenv("PI_AGENT_URL", "")).rstrip("/")
        if not self.agent_url:
            raise RuntimeError("PI_AGENT_URL is not set — can't reach the Pi's camera server")

    def open(self) -> None:
        pass  # nothing to open; each read is its own HTTP request

    def close(self) -> None:
        pass

    def read_frame(self) -> np.ndarray:
        resp = requests.get(f"{self.agent_url}/frame.jpg", timeout=REMOTE_FRAME_TIMEOUT_S)
        resp.raise_for_status()
        frame = cv2.imdecode(np.frombuffer(resp.content, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Pi camera server returned an undecodable image")
        return frame

    def __enter__(self) -> "RemoteCamera":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def make_camera() -> "Camera | RemoteCamera":
    agent_url = os.getenv("PI_AGENT_URL")
    return RemoteCamera(agent_url) if agent_url else Camera()


def crop(frame: np.ndarray, bbox: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = bbox
    return frame[y:y + h, x:x + w]


def save(frame: np.ndarray, path: str) -> None:
    cv2.imwrite(path, frame)
