"""HX711 load-cell amplifier, bit-banged from Pi GPIO (replaces the ESP32).

Uses the RPi.GPIO API. On a Pi 5, install `rpi-lgpio` (a drop-in RPi.GPIO
replacement that works with the Pi 5's RP1 chip) instead of `RPi.GPIO`.

Python can't disable interrupts, and if SCK stays high >60us the HX711
powers down mid-read and returns garbage. So each `read_raw` is a median of
several samples, which rejects the occasional corrupted read.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - only importable on a Pi
    GPIO = None

READY_TIMEOUT_S = 0.5
GAIN_128_EXTRA_PULSES = 1  # channel A, gain 128


def twos_complement_24(value: int) -> int:
    return value - (1 << 24) if value & 0x800000 else value


class HX711:
    def __init__(self, dt_pin: int, sck_pin: int):
        if GPIO is None:
            raise RuntimeError("RPi.GPIO not available — run this on the Pi (pip install RPi.GPIO or rpi-lgpio)")
        self.dt = dt_pin
        self.sck = sck_pin
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.sck, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(self.dt, GPIO.IN)

    def _wait_ready(self) -> bool:
        deadline = time.monotonic() + READY_TIMEOUT_S
        while GPIO.input(self.dt) == GPIO.HIGH:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.0005)
        return True

    def _read_once(self) -> int | None:
        if not self._wait_ready():
            return None
        value = 0
        for _ in range(24):
            GPIO.output(self.sck, GPIO.HIGH)
            GPIO.output(self.sck, GPIO.LOW)
            value = (value << 1) | GPIO.input(self.dt)
        for _ in range(GAIN_128_EXTRA_PULSES):
            GPIO.output(self.sck, GPIO.HIGH)
            GPIO.output(self.sck, GPIO.LOW)
        return twos_complement_24(value)

    def read_raw(self, samples: int = 3) -> int | None:
        reads = [r for r in (self._read_once() for _ in range(samples)) if r is not None]
        return int(statistics.median(reads)) if reads else None


class Calibration:
    """Per-shelf tare offset + scale factor, persisted as JSON on the Pi
    (the ESP32 kept these in flash). grams = (raw - offset) / factor."""

    def __init__(self, path: Path):
        self.path = path
        self.shelves: dict[str, dict[str, float]] = {}
        if path.exists():
            self.shelves = json.loads(path.read_text())

    def _entry(self, shelf: int) -> dict[str, float]:
        return self.shelves.setdefault(str(shelf), {"offset": 0.0, "factor": 1.0})

    def to_grams(self, shelf: int, raw: int) -> float:
        e = self._entry(shelf)
        return (raw - e["offset"]) / e["factor"]

    def tare(self, shelf: int, raw_empty: int) -> None:
        self._entry(shelf)["offset"] = float(raw_empty)
        self.save()

    def set_known_weight(self, shelf: int, raw_loaded: int, known_grams: float) -> None:
        if known_grams <= 0:
            raise ValueError("known weight must be positive")
        e = self._entry(shelf)
        factor = (raw_loaded - e["offset"]) / known_grams
        if factor == 0:
            raise ValueError("reading didn't change from the tared value — is the load cell wired?")
        e["factor"] = factor
        self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.shelves, indent=2))


def cleanup() -> None:
    if GPIO is not None:
        GPIO.cleanup()
