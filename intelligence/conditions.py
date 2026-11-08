"""The fridge's latest sensor reading (temperature, pressure, humidity, light), as every
screen and alert should see it.

DEMO_CONDITIONS=on (in .env) shows steady room numbers instead (about 21.8 °C, 40 %
humidity, 1013 hPa, drifting a little), which is where the fridge actually sits for the
demo, for when the barometer isn't wired. Light still comes from the real sensor if there
is one. They never raise the too-warm alert (see alerts._fridge_temp_alert).
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
        "temperature_c": round(21.8 + 0.3 * math.sin(t / 900), 1),   # a room, drifting slowly
        "pressure_hpa": round(1013.2 + 0.4 * math.sin(t / 1800), 1),
        "humidity_pct": round(40 + 2 * math.sin(t / 900 + 1), 1),
        "light_raw": real["light_raw"] if real else None,
    }
