"""Run the whole system on one computer for testing.

Starts two processes, wired exactly like the final hybrid setup:
  1. the backend   (main.py)            http://localhost:8000
  2. a simulated Pi (pi_node.agent, sim) http://localhost:8001  <- control page

The simulated Pi pushes weights/door/sensor readings to the backend over HTTP
and serves camera frames the backend pulls — the same traffic the real Pi
will send over Wi-Fi. Moving to real hardware later means running
`python -m pi_node.agent` on the Pi and pointing the backend at it; no code
changes.

  python run_local.py            # keep existing database
  python run_local.py --seed     # wipe the database and load weeks of demo history
  python run_local.py --webcam   # simulated sensors, but this computer's real webcam
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
BACKEND_PORT = 8000
PI_PORT = 8001


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", action="store_true", help="reset the database and load demo history")
    parser.add_argument("--webcam", action="store_true", help="use this computer's webcam instead of the synthetic feed")
    parser.add_argument("--db", default="refridge.db")
    args = parser.parse_args()

    base_env = {**os.environ, "PYTHONUNBUFFERED": "1", "DATABASE_PATH": args.db, "NUM_SHELVES": "2"}

    if args.seed:
        db_path = ROOT / args.db
        if db_path.exists():
            db_path.unlink()
        subprocess.run([sys.executable, "scripts/seed_demo.py"], cwd=ROOT, env=base_env, check=True)

    backend_env = {
        **base_env,
        "SCALE_SOURCE": "network",
        "PI_AGENT_URL": f"http://127.0.0.1:{PI_PORT}",
        "ENABLE_FRIDGE_LOOP": "true",
        "API_PORT": str(BACKEND_PORT),
    }
    pi_env = {
        **base_env,
        "PI_HARDWARE": "sim",
        "PI_CAMERA": "webcam" if args.webcam else "sim",
        "BACKEND_URL": f"http://127.0.0.1:{BACKEND_PORT}",
        "CAMERA_PORT": str(PI_PORT),
        "CONDITIONS_PUSH_S": "5",
    }

    procs = [
        subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=backend_env),
        subprocess.Popen([sys.executable, "-m", "pi_node.agent"], cwd=ROOT, env=pi_env),
    ]

    kiosk = (
        f"http://localhost:{BACKEND_PORT}/kiosk   (best at 1024x600)"
        if (ROOT / "mobile" / "dist").is_dir()
        else "build it first: cd mobile && npx expo export --platform web"
    )
    print(
        "\n"
        f"  Simulated fridge   http://localhost:{PI_PORT}        <- open this to put things in\n"
        f"  Fridge screen      {kiosk}\n"
        "  Phone app          cd mobile && npx expo start     (press w for a browser version)\n"
        f"  Backend API        http://localhost:{BACKEND_PORT}/docs\n"
        "\n  Ctrl+C to stop.\n",
        flush=True,
    )
    try:
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("A process exited — shutting down the other.")
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
