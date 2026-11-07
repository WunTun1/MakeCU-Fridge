"""Pi node entry point: reads the hardware and pushes to the backend.

  python -m pi_node.agent                    # on the Raspberry Pi (PI_HARDWARE=real)
  PI_HARDWARE=sim python -m pi_node.agent    # on any computer, simulated fridge

Pushes (all to BACKEND_URL):
  POST /api/pi/weight      every 1/WEIGHT_PUSH_HZ s, all shelves in one batch
  POST /api/pi/door        on every change, plus a heartbeat so a restarted backend catches up
  POST /api/pi/conditions  every CONDITIONS_PUSH_S s (barometer + light)
and serves GET /frame.jpg on CAMERA_PORT for the backend's vision pipeline.
"""
from __future__ import annotations

import logging
import threading
import time

import requests
import uvicorn

from pi_node.config import Config, config
from pi_node.hardware import Hardware, make_hardware
from pi_node.server import create_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("refridge.pi.agent")

REQUEST_TIMEOUT_S = 2
ERROR_LOG_INTERVAL_S = 10


def push_loop(hw: Hardware, cfg: Config, stop: threading.Event) -> None:
    session = requests.Session()
    period = 1.0 / cfg.weight_push_hz
    last_door: bool | None = None
    last_door_sent = 0.0
    last_conditions_sent = 0.0
    last_error_logged = 0.0
    connected = False

    while not stop.is_set():
        tick = time.monotonic()
        try:
            weights = hw.read_weights()
            if weights:
                session.post(
                    f"{cfg.backend_url}/api/pi/weight",
                    json={"readings": [{"shelf": s, "grams": g} for s, g in weights.items()]},
                    timeout=REQUEST_TIMEOUT_S,
                ).raise_for_status()

            door = hw.door_open()
            if door != last_door or tick - last_door_sent >= cfg.door_heartbeat_s:
                session.post(f"{cfg.backend_url}/api/pi/door", json={"open": door},
                             timeout=REQUEST_TIMEOUT_S).raise_for_status()
                if door != last_door:
                    log.info("Door %s", "opened" if door else "closed")
                last_door, last_door_sent = door, tick

            if tick - last_conditions_sent >= cfg.conditions_push_s:
                session.post(f"{cfg.backend_url}/api/pi/conditions", json=hw.read_conditions(),
                             timeout=REQUEST_TIMEOUT_S).raise_for_status()
                last_conditions_sent = tick

            if not connected:
                log.info("Connected to backend at %s", cfg.backend_url)
                connected = True
        except requests.RequestException as e:
            connected = False
            if tick - last_error_logged >= ERROR_LOG_INTERVAL_S:
                log.warning("Can't reach backend at %s (%s) — retrying", cfg.backend_url, e)
                last_error_logged = tick

        stop.wait(max(0.0, period - (time.monotonic() - tick)))


def main() -> None:
    hw = make_hardware(config)
    log.info("Pi node starting: %s, %d shelves, backend %s", type(hw).__name__, hw.num_shelves, config.backend_url)
    stop = threading.Event()
    threading.Thread(target=push_loop, args=(hw, config, stop), daemon=True).start()
    try:
        uvicorn.run(create_app(hw, config.backend_url), host="0.0.0.0", port=config.camera_port, log_level="warning")
    finally:
        stop.set()
        hw.close()


if __name__ == "__main__":
    main()
