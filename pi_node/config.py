"""All Pi-side settings, from pi_node/.env (see .env.example next to this file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")


def _pins(spec: str) -> list[tuple[int, int]]:
    """"16:17,18:19" -> [(16, 17), (18, 19)] — one (DT, SCK) pair per shelf."""
    pairs = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if chunk:
            dt, sck = chunk.split(":")
            pairs.append((int(dt), int(sck)))
    return pairs


def _opt_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    return float(raw) if raw else None


@dataclass(frozen=True)
class Config:
    backend_url: str = os.getenv("BACKEND_URL", "http://192.168.1.50:8000").rstrip("/")
    hx711_pins: tuple[tuple[int, int], ...] = tuple(_pins(os.getenv("HX711_PINS", "16:17,18:19")))
    door_switch_pin: int = int(os.getenv("DOOR_SWITCH_PIN", "5"))
    door_closed_when_pressed: bool = os.getenv("DOOR_CLOSED_WHEN_PRESSED", "true").lower() == "true"
    light_adc_channel: int = int(os.getenv("LIGHT_ADC_CHANNEL", "0"))
    door_light_threshold: float | None = _opt_float("DOOR_LIGHT_THRESHOLD")
    barometer_address: int | None = int(os.getenv("BAROMETER_I2C_ADDRESS"), 0) if os.getenv("BAROMETER_I2C_ADDRESS") else None
    camera_index: int = int(os.getenv("CAMERA_INDEX", "0"))
    camera_width: int = int(os.getenv("CAMERA_WIDTH", "640"))
    camera_height: int = int(os.getenv("CAMERA_HEIGHT", "480"))
    camera_port: int = int(os.getenv("CAMERA_PORT", "8001"))
    weight_push_hz: float = float(os.getenv("WEIGHT_PUSH_HZ", "10"))
    conditions_push_s: float = float(os.getenv("CONDITIONS_PUSH_S", "30"))
    door_heartbeat_s: float = float(os.getenv("DOOR_HEARTBEAT_S", "5"))
    calibration_file: Path = Path(os.getenv("CALIBRATION_FILE", str(Path(__file__).parent / "calibration.json")))


config = Config()
