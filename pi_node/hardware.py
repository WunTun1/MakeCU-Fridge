"""The Pi node's hardware, behind one interface so the same agent runs on:

- the real Raspberry Pi  (PI_HARDWARE=real): HX711 load cells, Grove micro
  switch, Grove light sensor, Grove barometer, USB webcam;
- any computer           (PI_HARDWARE=sim):  an in-memory fridge you drive
  from a control page, with a synthetic camera feed (or your laptop webcam
  with PI_CAMERA=webcam).

Either way the agent pushes to the backend over HTTP, so local testing uses
the exact network path the final Pi + computer setup does.
"""
from __future__ import annotations

import logging
import math
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Protocol

import cv2
import numpy as np

from pi_node.config import Config

log = logging.getLogger("refridge.pi.hardware")


class Hardware(Protocol):
    num_shelves: int

    def read_weights(self) -> dict[int, float]: ...
    def door_open(self) -> bool: ...
    def read_conditions(self) -> dict[str, float | None]: ...
    def frame(self) -> np.ndarray | None: ...
    def close(self) -> None: ...


class WebcamGrabber:
    """Reads a USB webcam continuously on a thread so /frame.jpg always serves
    the newest frame instead of a stale buffered one."""

    def __init__(self, index: int, width: int, height: int):
        backend = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
        self._cap = cv2.VideoCapture(index, backend)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open webcam index {index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._latest: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._latest = frame
            else:
                time.sleep(0.05)

    def latest(self) -> np.ndarray | None:
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def close(self) -> None:
        self._stop.set()
        self._cap.release()


# ===================================================================== real
class RealHardware:
    def __init__(self, cfg: Config):
        import RPi.GPIO as GPIO

        from pi_node.hx711 import HX711, Calibration

        self._GPIO = GPIO
        self.cfg = cfg
        self.cells = [HX711(dt, sck) for dt, sck in cfg.hx711_pins]
        self.num_shelves = len(self.cells)
        self.calibration = Calibration(cfg.calibration_file)
        GPIO.setup(cfg.door_switch_pin, GPIO.IN)

        try:
            from grove.adc import ADC  # Seeed grove.py, for the Base Hat's ADC
            self._adc = ADC()
        except Exception as e:
            log.warning("Grove light sensor unavailable (%s) — light readings disabled", e)
            self._adc = None

        try:
            from pi_node.barometer import Barometer
            self._baro = Barometer(cfg.barometer_address)
            log.info("Barometer: %s at 0x%02x", self._baro.chip_name, self._baro.address)
        except Exception as e:
            log.warning("Barometer unavailable (%s) — temperature/pressure disabled", e)
            self._baro = None

        try:
            self._cam: WebcamGrabber | None = WebcamGrabber(cfg.camera_index, cfg.camera_width, cfg.camera_height)
        except RuntimeError as e:
            log.warning("%s — camera disabled", e)
            self._cam = None

    def read_weights(self) -> dict[int, float]:
        weights = {}
        for shelf, cell in enumerate(self.cells):
            raw = cell.read_raw()
            if raw is not None:
                weights[shelf] = self.calibration.to_grams(shelf, raw)
        return weights

    def _light(self) -> float | None:
        return float(self._adc.read(self.cfg.light_adc_channel)) if self._adc else None

    def door_open(self) -> bool:
        pressed = self._GPIO.input(self.cfg.door_switch_pin) == self._GPIO.HIGH
        open_by_switch = not pressed if self.cfg.door_closed_when_pressed else pressed
        if self.cfg.door_light_threshold is not None:
            light = self._light()
            if light is not None and light > self.cfg.door_light_threshold:
                return True  # fridge light is on — door is open even if the switch disagrees
        return open_by_switch

    def read_conditions(self) -> dict[str, float | None]:
        reading = self._baro.read() if self._baro else None
        return {
            "temperature_c": reading.temperature_c if reading else None,
            "pressure_hpa": reading.pressure_hpa if reading else None,
            "humidity_pct": reading.humidity_pct if reading else None,
            "light_raw": self._light(),
        }

    def frame(self) -> np.ndarray | None:
        return self._cam.latest() if self._cam else None

    def close(self) -> None:
        if self._cam:
            self._cam.close()
        self._GPIO.cleanup()


# ====================================================================== sim
PALETTE = [(60, 180, 75), (48, 130, 245), (75, 25, 230), (200, 130, 0), (180, 30, 145), (0, 210, 255), (240, 240, 70)]
HAND_DURATION_S = 1.4
HAND_ACTION_AT_S = 0.8          # when, during the hand visit, the item appears/disappears
DOOR_SETTLE_S = 1.5             # backend ignores motion ~1s after the door opens
TEMP_CLOSED_C, TEMP_OPEN_C, TEMP_TAU_S = 3.5, 12.0, 90.0
SCALE_NOISE_G = 0.8


@dataclass
class SimItem:
    id: int
    name: str
    grams: float
    shelf: int
    x: float                     # normalized horizontal center
    color: tuple[int, int, int]
    size_grams: float = 0.0      # drawn size; fixed at placement, like a real carton that doesn't shrink as you pour


@dataclass
class _Visit:
    start: float
    shelf: int
    x: float
    action: object = None        # callable run at start + HAND_ACTION_AT_S
    done: bool = False


@dataclass
class SimHardware:
    num_shelves: int
    width: int = 640
    height: int = 480
    camera: WebcamGrabber | None = None
    door: bool = False
    items: list[SimItem] = field(default_factory=list)
    temp_override_c: float | None = None
    _visits: list[_Visit] = field(default_factory=list)
    _next_id: int = 1
    _temp_c: float = TEMP_CLOSED_C
    _temp_ts: float = field(default_factory=time.monotonic)
    _door_opened_at: float = 0.0
    _lock: threading.RLock = field(default_factory=threading.RLock)

    # ------------------------------------------------------------- timeline
    def _advance(self) -> float:
        now = time.monotonic()
        for v in self._visits:
            if not v.done and now >= v.start + HAND_ACTION_AT_S:
                if v.action:
                    v.action()
                v.done = True
        self._visits = [v for v in self._visits if now < v.start + HAND_DURATION_S]
        target = TEMP_OPEN_C if self.door else TEMP_CLOSED_C
        self._temp_c += (target - self._temp_c) * (1 - math.exp(-(now - self._temp_ts) / TEMP_TAU_S))
        self._temp_ts = now
        return now

    def _schedule_visit(self, shelf: int, x: float, action) -> None:
        """A hand reaches into `shelf` at `x`, `action` happens mid-visit. Opens
        the door first if needed, and queues after any visit already in progress."""
        now = self._advance()
        if not self.door:
            self.set_door(True)
        start = max(now, self._door_opened_at + DOOR_SETTLE_S)
        if self._visits:
            start = max(start, max(v.start for v in self._visits) + HAND_DURATION_S + 0.8)
        self._visits.append(_Visit(start, shelf, x, action))

    # -------------------------------------------------------------- controls
    def set_door(self, open_: bool) -> None:
        with self._lock:
            self._advance()
            if open_ and not self.door:
                self._door_opened_at = time.monotonic()
            self.door = open_

    def place(self, name: str, grams: float, shelf: int, x: float | None = None) -> None:
        with self._lock:
            if not 0 <= shelf < self.num_shelves:
                raise ValueError(f"shelf must be 0..{self.num_shelves - 1}")
            if x is None:
                taken = sorted(i.x for i in self.items if i.shelf == shelf)
                x = next((c for c in (0.15, 0.4, 0.65, 0.88) if all(abs(c - t) > 0.15 for t in taken)), 0.5)
            item = SimItem(self._next_id, name, grams, shelf, x, PALETTE[self._next_id % len(PALETTE)], grams)
            self._next_id += 1
            self._schedule_visit(shelf, x, lambda: self.items.append(item))

    def remove(self, item_id: int) -> None:
        with self._lock:
            item = self._find(item_id)

            def apply() -> None:
                if item in self.items:  # a double-click may have queued two removals
                    self.items.remove(item)

            self._schedule_visit(item.shelf, item.x, apply)

    def use(self, item_id: int, grams: float) -> None:
        """Take some out without removing the item (pour milk, take 2 eggs)."""
        with self._lock:
            item = self._find(item_id)

            def apply() -> None:
                item.grams = max(item.grams - grams, 0.0)

            self._schedule_visit(item.shelf, item.x, apply)

    def _find(self, item_id: int) -> SimItem:
        for i in self.items:
            if i.id == item_id:
                return i
        raise KeyError(f"no sim item {item_id}")

    def state(self) -> dict:
        with self._lock:
            now = self._advance()
            return {
                "door_open": self.door,
                "hand_busy": any(v.start <= now for v in self._visits),
                "queued_actions": len(self._visits),
                "weights": {s: round(g, 1) for s, g in self._true_weights().items()},
                "items": [i.__dict__ | {"grams": round(i.grams, 1)} for i in self.items],
                "conditions": self.read_conditions(),
            }

    # -------------------------------------------------------- Hardware API
    def _true_weights(self) -> dict[int, float]:
        w = {s: 0.0 for s in range(self.num_shelves)}
        for i in self.items:
            w[i.shelf] += i.grams
        return w

    def read_weights(self) -> dict[int, float]:
        with self._lock:
            now = self._advance()
            weights = self._true_weights()
            for v in self._visits:
                if v.start <= now:  # a hand resting on the shelf disturbs the reading
                    weights[v.shelf] += random.uniform(50, 300)
            return {s: g + random.gauss(0, SCALE_NOISE_G) for s, g in weights.items()}

    def door_open(self) -> bool:
        with self._lock:
            return self.door

    def read_conditions(self) -> dict[str, float | None]:
        with self._lock:
            self._advance()
            temp = self.temp_override_c if self.temp_override_c is not None else self._temp_c
            return {
                "temperature_c": round(temp + random.gauss(0, 0.05), 2),
                "pressure_hpa": round(1013.2 + random.gauss(0, 0.2), 2),
                "humidity_pct": round(45 + random.gauss(0, 0.5), 1),
                "light_raw": 850.0 if self.door else 15.0,
            }

    def frame(self) -> np.ndarray | None:
        if self.camera:
            return self.camera.latest()
        with self._lock:
            return self._render()

    def close(self) -> None:
        if self.camera:
            self.camera.close()

    # ------------------------------------------------------------ rendering
    def _band(self, shelf: int) -> tuple[int, int]:
        h = self.height / self.num_shelves
        return int(shelf * h), int((shelf + 1) * h)

    def _render(self) -> np.ndarray:
        now = self._advance()
        img = np.full((self.height, self.width, 3), (42, 40, 38), np.uint8)
        if not self.door:
            return np.full((self.height, self.width, 3), 4, np.uint8)  # dark inside a closed fridge

        for s in range(self.num_shelves):
            _, y1 = self._band(s)
            cv2.rectangle(img, (0, y1 - 6), (self.width, y1), (150, 150, 150), -1)

        for item in self.items:
            y0, y1 = self._band(item.shelf)
            h = int(min(max(40 + item.size_grams / 12, 40), (y1 - y0) - 30))
            w = 78
            cx = int(item.x * self.width)
            top, left = y1 - 6 - h, cx - w // 2
            cv2.rectangle(img, (left, top), (left + w, y1 - 7), item.color, -1)
            cv2.putText(img, item.name[:8].upper(), (left + 4, top + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        for v in self._visits:
            if v.start <= now:
                y0, y1 = self._band(v.shelf)
                cx = int(v.x * self.width) + random.randint(-28, 28)
                cy = (y0 + y1) // 2 + random.randint(-12, 12)
                cv2.rectangle(img, (cx - 30, 0), (cx + 30, cy), (110, 150, 205), -1)  # arm
                cv2.ellipse(img, (cx, cy), (55, 42), 0, 0, 360, (120, 165, 225), -1)  # hand
        return img


def make_hardware(cfg: Config) -> Hardware:
    kind = os.getenv("PI_HARDWARE", "real").lower()
    if kind == "real":
        return RealHardware(cfg)
    if kind == "sim":
        camera = None
        if os.getenv("PI_CAMERA", "sim").lower() == "webcam":
            camera = WebcamGrabber(cfg.camera_index, cfg.camera_width, cfg.camera_height)
        num_shelves = int(os.getenv("NUM_SHELVES", len(cfg.hx711_pins)))
        return SimHardware(num_shelves=num_shelves, width=cfg.camera_width,
                           height=cfg.camera_height, camera=camera)
    raise ValueError(f"PI_HARDWARE must be 'real' or 'sim', got {kind!r}")
