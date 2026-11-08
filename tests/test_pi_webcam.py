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
