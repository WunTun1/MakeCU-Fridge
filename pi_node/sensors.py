"""Every sensor on the Pi, live — and the scale's tare and calibration, in one place.

    cd ~/MakeCU-Fridge && .venv/bin/python -m pi_node.sensors

Shows each shelf's weight (and the raw load-cell number), the door switch, the light
sensor and the barometer, refreshed twice a second. Press Enter for the menu:

    t   tare a shelf: take everything off it, and this becomes 0 g
    c   calibrate a shelf: put a known weight on it and type how many grams it is
    q   quit

Calibration goes into the same file run.py reads (pi_node/calibration.json), so what
you set here is what the fridge uses. Stop run.py first: both use the same pins.
Calibrate inside the cold fridge if you can — load cells drift with temperature.
"""
from __future__ import annotations

import os
import sys
import time

from pi_node.calibrate import _steady_raw
from pi_node.config import config

REFRESH_S = 0.5


# ------------------------------------------------------------------ reading
def snapshot(hw) -> dict:
    """One reading of everything: {"shelves": [(shelf, raw, grams)], "door", "pressed", "light", "baro"}."""
    shelves = []
    for shelf, cell in enumerate(hw.cells):
        raw = cell.read_raw()
        shelves.append((shelf, raw, None if raw is None else hw.calibration.to_grams(shelf, raw)))
    pressed = hw._GPIO.input(hw.cfg.door_switch_pin) == hw._GPIO.HIGH
    light = hw._light()
    baro = None
    if hw._baro is not None:
        try:
            baro = hw._baro.read()
        except OSError:
            baro = None  # a dropped I2C read: show "no reading" this time
    return {"shelves": shelves, "door_open": hw.door_open(), "pressed": pressed, "light": light, "baro": baro}


def calibrated(hw, shelf: int) -> str:
    entry = hw.calibration.shelves.get(str(shelf))
    if entry is None or (entry.get("offset", 0) == 0 and entry.get("factor", 1) == 1):
        return "not calibrated"
    return "calibrated" if entry.get("factor", 1) != 1 else "tared only"


def render(hw, s: dict) -> str:
    cfg = hw.cfg
    lines = ["ShelfLife sensors     Enter: tare / calibrate      Ctrl+C: quit", ""]
    lines.append("Scale")
    if not s["shelves"]:
        lines.append("  no load cells set up — HX711_PINS in pi_node/.env is empty")
    for (shelf, raw, grams), (dt, sck) in zip(s["shelves"], cfg.hx711_pins):
        reading = "no reading — check the HX711 wiring" if raw is None else f"{grams:9.1f} g     raw {raw:>9}"
        lines.append(f"  Shelf {shelf}  {reading}     ({calibrated(hw, shelf)}; DT GPIO{dt}, SCK GPIO{sck})")
    lines.append("")
    state = "OPEN" if s["door_open"] else "closed"
    lines.append(f"Door switch   {state:<7}  switch {'pressed' if s['pressed'] else 'released'}"
                 f"     (GPIO{cfg.door_switch_pin}; closed when {'pressed' if cfg.door_closed_when_pressed else 'released'})")
    light = "not found (Grove Base Hat ADC)" if s["light"] is None else f"{s['light']:.0f}"
    lines.append(f"Light         {light}     (A{cfg.light_adc_channel})")
    if hw._baro is None:
        lines.append("Barometer     not found — plug it into an I2C port and turn I2C on: sudo raspi-config nonint do_i2c 0")
    elif s["baro"] is None:
        lines.append(f"Barometer     {hw._baro.chip_name} at 0x{hw._baro.address:02x}: no reading this time")
    else:
        b = s["baro"]
        parts = [f"{b.temperature_c:.1f} °C", f"{b.pressure_hpa:.1f} hPa"]
        if b.humidity_pct is not None:
            parts.append(f"{b.humidity_pct:.0f} % humidity")
        lines.append(f"Barometer     {'   '.join(parts)}     ({hw._baro.chip_name} at 0x{hw._baro.address:02x})")
    return "\n".join(lines)


# -------------------------------------------------------------- calibration
def tare(hw, shelf: int) -> float:
    """The shelf's current (empty) reading becomes 0 g. Returns the new reading."""
    raw = _steady_raw(hw.cells[shelf])
    hw.calibration.tare(shelf, raw)
    return hw.calibration.to_grams(shelf, _steady_raw(hw.cells[shelf]))


def calibrate(hw, shelf: int, known_grams: float) -> float:
    """Set the scale factor from a known weight on the shelf. Returns the new reading."""
    hw.calibration.set_known_weight(shelf, _steady_raw(hw.cells[shelf]), known_grams)
    return hw.calibration.to_grams(shelf, _steady_raw(hw.cells[shelf]))


def _ask(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def _pick_shelf(hw) -> int | None:
    if len(hw.cells) == 1:
        return 0
    answer = _ask(f"Which shelf (0-{len(hw.cells) - 1})? ")
    return int(answer) if answer.isdigit() and int(answer) < len(hw.cells) else None


def menu(hw) -> bool:
    """Returns False to quit."""
    print("\n  t  tare a shelf (take everything off it first)")
    print("  c  calibrate a shelf with a known weight")
    print("  q  quit")
    choice = _ask("  Enter: back to the live view > ").lower()
    if choice == "q":
        return False
    if choice not in ("t", "c"):
        return True
    shelf = _pick_shelf(hw)
    if shelf is None:
        print("No such shelf.")
        time.sleep(1.5)
        return True
    try:
        if choice == "t":
            _ask(f"Take everything off shelf {shelf}, then press Enter...")
            print(f"Shelf {shelf} tared. It now reads {tare(hw, shelf):.1f} g.")
        else:
            if calibrated(hw, shelf) == "not calibrated":
                print(f"Tip: tare shelf {shelf} first (t), with nothing on it — calibration measures from there.")
            grams = _ask(f"Put a known weight on shelf {shelf}, then type its weight in grams (e.g. 500): ")
            try:
                value = float(grams)
            except ValueError:
                print("That isn't a number — nothing changed.")
            else:
                print(f"Shelf {shelf} calibrated. With the weight on it, it now reads {calibrate(hw, shelf, value):.1f} g.")
    except (ValueError, SystemExit) as e:
        print(f"Couldn't: {e}")
    _ask("Press Enter to go back to the live view...")
    return True


# ---------------------------------------------------------------------- run
def _enter_pressed(timeout: float) -> bool:
    """Waits up to `timeout` s for Enter, without blocking the live view."""
    if os.name == "nt":
        import msvcrt
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if msvcrt.kbhit() and msvcrt.getwch() in "\r\n":
                return True
            time.sleep(0.02)
        return False
    import select
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if ready:
        sys.stdin.readline()
        return True
    return False


def main() -> None:
    from pi_node.hardware import RealHardware
    from pi_node.hx711 import cleanup

    hw = RealHardware(config, camera=False)
    try:
        while True:
            print("\033[2J\033[H" + render(hw, snapshot(hw)), flush=True)  # clear the terminal, then redraw
            if _enter_pressed(REFRESH_S) and not menu(hw):
                break
    except KeyboardInterrupt:
        pass
    finally:
        print()
        cleanup()


if __name__ == "__main__":
    main()
