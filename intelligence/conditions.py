"""The fridge's latest sensor reading (temperature, pressure, humidity, light), as every
screen and alert should see it.

DEMO_CONDITIONS=on (in .env) shows plausible fridge numbers instead — about 3.6 °C,
45 % humidity, 1013 hPa, drifting a little — for demos while the fridge sits at room
temperature or the barometer isn't wired. Light still comes from the real sensor if
there is one.
"""
from __future__ import annotations

import math
import os

from intelligence import clock
from inventory.database import Database

FIELDS = ("occurred_at", "temperature_c", "pressure_hpa", "humidity_pct", "light_raw")


def demo_on() -> bool:
    return os.getenv("DEMO_CONDITIONS", "off").lower() in ("on", "true", "1")


def latest(db: Database) -> dict | None:
    """{"occurred_at", "temperature_c", "pressure_hpa", "humidity_pct", "light_raw"}, or None."""
    row = db.latest_condition()
    real = {k: row[k] for k in FIELDS} if row is not None else None
    if not demo_on():
        return real
    t = clock.utc_now().timestamp()
    return {
        "occurred_at": clock.utc_now().isoformat(),
        "temperature_c": round(3.6 + 0.25 * math.sin(t / 420), 1),   # slow drift, like a real fridge cycling
        "pressure_hpa": round(1013.2 + 0.4 * math.sin(t / 1800), 1),
        "humidity_pct": round(45 + 2 * math.sin(t / 900 + 1), 1),
        "light_raw": real["light_raw"] if real else None,
    }
