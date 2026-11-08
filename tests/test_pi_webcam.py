import time

import pytest

from pi_node.hardware import WebcamGrabber

MISSING_INDEX = 9  # no machine running the tests has ten cameras


def test_missing_camera_raises_without_keep_trying():
    with pytest.raises(RuntimeError):
        WebcamGrabber(MISSING_INDEX, 640, 480)


def test_missing_camera_keeps_looking_and_serves_nothing_meanwhile(monkeypatch):
    attempts = []
    real_open = WebcamGrabber._open

    def counting_open(self):
        attempts.append(time.monotonic())
        return real_open(self)

    monkeypatch.setattr(WebcamGrabber, "_open", counting_open)
    monkeypatch.setattr(WebcamGrabber, "REOPEN_S", 0.05)
    cam = WebcamGrabber(MISSING_INDEX, 640, 480, keep_trying=True)
    try:
        deadline = time.monotonic() + 10
        while len(attempts) < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(attempts) >= 3, "should retry opening a camera that isn't there yet"
        assert not cam.connected
        assert cam.latest() is None
    finally:
        cam.close()


class _FakeCapture:
    """Stands in for cv2.VideoCapture: only `working` indexes open and give a picture."""

    working: set[int] = set()
    opened: list[int] = []

    def __init__(self, index, backend=None):
        self.index = index
        _FakeCapture.opened.append(index)

    def isOpened(self):
        return True  # like a metadata node: opens, but...

    def read(self):
        import numpy as np
        return (self.index in self.working, np.zeros((4, 4, 3), np.uint8) if self.index in self.working else None)

    def set(self, *args):
        pass

    def release(self):
        pass


def test_scan_finds_the_camera_that_gives_a_picture(monkeypatch):
    import cv2
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    monkeypatch.setattr(WebcamGrabber, "_candidates", lambda self: [0, 1, 2, 3] if self._scan else [0])
    _FakeCapture.working, _FakeCapture.opened = {2}, []
    cam = WebcamGrabber(0, 640, 480, keep_trying=True, scan=True)
    try:
        assert cam.connected and cam._index == 2
        assert _FakeCapture.opened[:3] == [0, 1, 2]  # the configured index first, then the rest in order
    finally:
        cam.close()


def test_without_scan_only_the_configured_camera_is_tried(monkeypatch):
    import cv2
    monkeypatch.setattr(cv2, "VideoCapture", _FakeCapture)
    _FakeCapture.working, _FakeCapture.opened = {2}, []
    with pytest.raises(RuntimeError):
        WebcamGrabber(0, 640, 480)  # e.g. the laptop: never falls back to another camera
    assert set(_FakeCapture.opened) == {0}
