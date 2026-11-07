"""Load-cell calibration on the real Pi (do it inside the cold fridge — load
cells drift with temperature, see architecture doc section 3).

  python -m pi_node.calibrate tare 0          # shelf 0 empty
  python -m pi_node.calibrate cal 0 500       # shelf 0 with a known 500 g weight on it
  python -m pi_node.calibrate read            # live grams for every shelf (Ctrl+C to stop)
"""
from __future__ import annotations

import argparse
import statistics
import time

from pi_node.config import config
from pi_node.hx711 import HX711, Calibration, cleanup

SAMPLES = 15


def _steady_raw(cell: HX711) -> int:
    reads = [r for r in (cell.read_raw() for _ in range(SAMPLES)) if r is not None]
    if not reads:
        raise SystemExit("No readings — check the HX711 wiring and HX711_PINS in pi_node/.env")
    return int(statistics.median(reads))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    tare = sub.add_parser("tare")
    tare.add_argument("shelf", type=int)
    cal = sub.add_parser("cal")
    cal.add_argument("shelf", type=int)
    cal.add_argument("grams", type=float)
    sub.add_parser("read")
    args = parser.parse_args()

    cells = [HX711(dt, sck) for dt, sck in config.hx711_pins]
    calibration = Calibration(config.calibration_file)
    try:
        if args.cmd == "tare":
            calibration.tare(args.shelf, _steady_raw(cells[args.shelf]))
            print(f"Shelf {args.shelf} tared.")
        elif args.cmd == "cal":
            calibration.set_known_weight(args.shelf, _steady_raw(cells[args.shelf]), args.grams)
            print(f"Shelf {args.shelf} calibrated against {args.grams} g.")
        else:
            while True:
                parts = []
                for shelf, cell in enumerate(cells):
                    raw = cell.read_raw()
                    parts.append(f"shelf {shelf}: " + ("—" if raw is None else f"{calibration.to_grams(shelf, raw):8.1f} g"))
                print("   ".join(parts), end="\r", flush=True)
                time.sleep(0.2)
    except KeyboardInterrupt:
        print()
    finally:
        cleanup()


if __name__ == "__main__":
    main()
