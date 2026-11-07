"""Reads load-cell weights and the door switch, from one of three sources:

- "mock"    no hardware attached — weights stay at whatever `set_mock_weight`
            last set (used by the demo seeder / manual API endpoints).
- "serial"  an ESP32 running firmware/scale_esp32, over USB, streaming
            newline-delimited JSON: {"t":"w","shelf":0,"grams":842.3} /
            {"t":"door","open":true}.
- "network" a Raspberry Pi (pi_node/agent.py) reading the load cells + Grove
            microswitch directly and pushing readings to this backend's
            POST /api/pi/weight and /api/pi/door endpoints, which call
            `ingest_weight` / `ingest_door` on the shared singleton below.

Whichever source is used, the rest of the app only ever talks to this same
settling/noise-filtering logic (section 3 of the architecture doc).
"""
from __future__ import annotations

import json
import os
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field

try:
    import serial  # pyserial
except ImportError:  # pragma: no cover - optional until hardware is attached
    serial = None

SETTLE_WINDOW = 10          # readings kept per shelf for the settling check
# "Settled" (architecture doc section 3 says readings within ~3 g). A max-min
# test over 10 samples trips on a single noisy sample, so use std-dev instead.
SETTLE_MAX_STDEV_G = 1.5
SETTLE_TIMEOUT_S = 5.0
NOISE_THRESHOLD_G = 15.0    # changes below this are treated as noise (section 3)
NOISE_THRESHOLD_PCT = 0.10

VALID_SOURCES = {"mock", "serial", "network"}


@dataclass
class _ShelfState:
    readings: deque[float] = field(default_factory=lambda: deque(maxlen=SETTLE_WINDOW))
    mock_grams: float = 0.0


class ScaleReader:
    def __init__(
        self,
        source: str | None = None,
        port: str | None = None,
        baud: int = 115200,
        mock: bool | None = None,  # alias for source="mock"/"serial"
        num_shelves: int | None = None,
    ):
        if num_shelves is None:
            num_shelves = int(os.getenv("NUM_SHELVES", "2"))
        if source is None:
            if mock is not None:
                source = "mock" if mock else "serial"
            else:
                source = os.getenv("SCALE_SOURCE", "mock" if os.getenv("SCALE_MOCK", "true").lower() == "true" else "serial")
        if source not in VALID_SOURCES:
            raise ValueError(f"source must be one of {VALID_SOURCES}, got {source!r}")
        self.source = source
        self.mock = source == "mock"  # kept for existing callers that check .mock
        self.port = port or os.getenv("SCALE_SERIAL_PORT", "COM3")
        self.baud = baud
        self.num_shelves = num_shelves
        self._shelves = {i: _ShelfState() for i in range(num_shelves)}
        self._door_open = False
        self._ser: "serial.Serial | None" = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ setup
    def start(self) -> None:
        """Only "serial" needs a background reader thread. "mock" has nothing
        to start, and "network" is fed by the API endpoints calling
        `ingest_weight` / `ingest_door` directly — no polling needed here."""
        if self.source != "serial":
            return
        if serial is None:
            raise RuntimeError("pyserial not installed; pip install pyserial or set SCALE_SOURCE=mock")
        self._ser = serial.Serial(self.port, self.baud, timeout=1)
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._ser:
            self._ser.close()

    def _read_loop(self) -> None:
        assert self._ser is not None
        while not self._stop.is_set():
            try:
                line = self._ser.readline().decode("utf-8", errors="ignore").strip()
            except Exception:
                continue
            if not line:
                continue
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return
        if msg.get("t") == "w":
            self.ingest_weight(int(msg["shelf"]), float(msg["grams"]))
        elif msg.get("t") == "door":
            self.ingest_door(bool(msg.get("open")))

    # ------------------------------------------------------- networked ingest
    def ingest_weight(self, shelf: int, grams: float) -> None:
        """Called by the serial read loop, or by the API's POST /api/pi/weight
        handler when a Raspberry Pi is pushing readings over the network."""
        if shelf in self._shelves:
            self._shelves[shelf].readings.append(grams)

    def ingest_door(self, open_: bool) -> None:
        self._door_open = open_

    # ---------------------------------------------------------------- reading
    def door_is_open(self) -> bool:
        return self._door_open

    def set_mock_weight(self, shelf: int, grams: float) -> None:
        """Demo / test hook: pretend a shelf's true weight just changed."""
        state = self._shelves[shelf]
        state.mock_grams = max(grams, 0.0)
        state.readings.clear()
        for _ in range(SETTLE_WINDOW):
            state.readings.append(state.mock_grams)

    def set_door_open(self, open_: bool) -> None:
        self._door_open = open_

    def read_latest(self, shelf: int) -> float | None:
        readings = self._shelves[shelf].readings
        return readings[-1] if readings else None

    def wait_until_stable(
        self, shelf: int, timeout: float = SETTLE_TIMEOUT_S, poll_interval: float = 0.1
    ) -> float:
        """Blocks until the shelf's recent readings settle, then returns the
        median weight. In mock mode the value is settled instantly."""
        if self.mock:
            return self._shelves[shelf].mock_grams

        deadline = time.monotonic() + timeout
        state = self._shelves[shelf]
        while time.monotonic() < deadline:
            if len(state.readings) >= SETTLE_WINDOW:
                if statistics.pstdev(state.readings) <= SETTLE_MAX_STDEV_G:
                    return statistics.median(state.readings)
            time.sleep(poll_interval)
        # timed out — best effort median of whatever we have
        return statistics.median(state.readings) if state.readings else 0.0

    def snapshot(self) -> dict[int, float]:
        """Current median per shelf, without waiting to settle. For the moment the
        door opens: nothing has touched the shelves yet, and blocking here would
        stall the camera loop through the first hand trip."""
        if self.mock:
            return {s: st.mock_grams for s, st in self._shelves.items()}
        return {s: statistics.median(st.readings) for s, st in self._shelves.items() if st.readings}

    def weigh_all(self, timeout: float = SETTLE_TIMEOUT_S) -> dict[int, float]:
        """Shelves that have never reported (fewer load cells wired than
        NUM_SHELVES) are skipped instead of each blocking for the full timeout."""
        shelves = [s for s, st in self._shelves.items() if self.mock or st.readings]
        return {shelf: self.wait_until_stable(shelf, timeout) for shelf in shelves}

    # ------------------------------------------------------------- calibration
    def tare(self, shelf: int) -> None:
        """Serial (ESP32) only — a networked Pi calibrates itself locally
        (see pi_node/scale_rig.py) since it owns the HX711 chips directly."""
        self._send(f"tare {shelf}")
        if self.mock:
            self.set_mock_weight(shelf, 0.0)

    def calibrate(self, shelf: int, known_grams: float) -> None:
        self._send(f"cal {shelf} {known_grams}")

    def _send(self, command: str) -> None:
        if self.source != "serial" or self._ser is None:
            return
        self._ser.write((command + "\n").encode("utf-8"))


def is_significant_change(delta_g: float, baseline_g: float) -> bool:
    """A weight delta counts as real only if it clears both an absolute and a
    relative noise floor (section 3)."""
    if abs(delta_g) < NOISE_THRESHOLD_G:
        return False
    if baseline_g > 0 and abs(delta_g) < baseline_g * NOISE_THRESHOLD_PCT:
        return False
    return True


_scale: ScaleReader | None = None


def get_scale_reader() -> ScaleReader:
    """Process-wide singleton so the API's /api/pi/* endpoints and the fridge
    loop share the same shelf buffers and door state."""
    global _scale
    if _scale is None:
        _scale = ScaleReader()
        _scale.start()
    return _scale
