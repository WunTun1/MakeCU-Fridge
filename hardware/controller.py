"""ESP32 serial interface for retrieval motors (stretch). Section 13.

Sends the same newline-delimited JSON protocol the firmware already uses for
scale commands (see firmware/scale_esp32), extended with a "retrieve" command.
Verification that retrieval worked happens in main.py by checking both the
camera (item gone from its shelf photo) and the scale (expected weight drop)
— this module only drives the motors.
"""
from __future__ import annotations

import json
import os

try:
    import serial
except ImportError:  # pragma: no cover
    serial = None

from hardware.planner import RetrievalPlan


class MotorController:
    def __init__(self, port: str | None = None, baud: int = 115200, mock: bool | None = None):
        self.port = port or os.getenv("SCALE_SERIAL_PORT", "COM3")
        self.baud = baud
        self.mock = mock if mock is not None else os.getenv("SCALE_MOCK", "true").lower() == "true"
        self._ser: "serial.Serial | None" = None

    def connect(self) -> None:
        if self.mock:
            return
        if serial is None:
            raise RuntimeError("pyserial not installed; pip install pyserial or set SCALE_MOCK=true")
        self._ser = serial.Serial(self.port, self.baud, timeout=1)

    def disconnect(self) -> None:
        if self._ser:
            self._ser.close()
            self._ser = None

    def retrieve(self, plan: RetrievalPlan) -> None:
        if plan.blocked_by:
            raise RuntimeError(f"path blocked by item(s) {plan.blocked_by}; move them first")
        command = json.dumps({
            "command": "retrieve",
            "item_id": plan.item_id,
            "target_x_mm": plan.target_x_mm,
            "target_y_mm": plan.target_y_mm,
        })
        if self.mock or self._ser is None:
            return
        self._ser.write((command + "\n").encode("utf-8"))
