"""One command for the Pi: connect to the backend, run the sensors + camera, open the fridge screen.

    python3 ~/MakeCU-Fridge/pi_node/run.py              # everything, fridge screen full-screen
    python3 ~/MakeCU-Fridge/pi_node/run.py --windowed   # fridge screen in a normal window (testing)
    python3 ~/MakeCU-Fridge/pi_node/run.py --no-screen  # sensors + camera only (e.g. over SSH)

It
  1. switches to the project's .venv Python (and creates pi_node/.env from the example if missing),
  2. brings up the direct-cable link if BACKEND_URL is on it (192.168.50.x; pi_node/link.py, see kiosk/HYBRID_SETUP.md),
  3. runs the sensor/camera agent (pi_node.agent), restarting it if it ever crashes,
  4. waits for the backend, then opens /kiosk in Chromium, reopening it if it closes,
  5. says what it found: backend, camera, scale calibration.
Ctrl+C stops everything.
"""
from __future__ import annotations

import argparse
import ipaddress
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PI_DIR = ROOT / "pi_node"
VENV = ROOT / ".venv"

RESTART_DELAY_S = 3


def say(msg: str) -> None:
    print(f"[refridge] {msg}", flush=True)


# ------------------------------------------------------------------ setup
def use_venv() -> None:
    """Re-run this script with .venv's Python, so `python3 run.py` works from anywhere."""
    venv_python = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_python.exists():
        say("No .venv yet. With internet, run:")
        say(f"  cd {ROOT} && python3 -m venv --system-site-packages .venv && "
            ".venv/bin/pip install -r pi_node/requirements.txt")
        sys.exit(1)
    if Path(sys.prefix).resolve() != VENV.resolve():
        args = [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]]
        if os.name == "nt":
            sys.exit(subprocess.call(args))
        os.execv(args[0], args)


def ensure_env_file() -> None:
    env = PI_DIR / ".env"
    if not env.exists() and not os.getenv("BACKEND_URL"):  # settings may also come from the environment
        shutil.copy(PI_DIR / ".env.example", env)
        say(f"Created {env} from the example. Set PI_HARDWARE, HX711_PINS and BACKEND_URL in it, then run this again.")
        sys.exit(1)


def ensure_direct_link(backend_host: str) -> None:
    """If the backend is on the direct cable's network, make sure this Pi is on it too
    (pi_node/link.py, which also runs on its own)."""
    from pi_node import link

    try:
        backend_ip = ipaddress.ip_address(backend_host)
    except ValueError:
        return  # a hostname: nothing to set up
    if backend_ip in link.NETWORK:
        link.ensure_link(quiet=True)


def http_json(url: str, timeout: float = 2) -> dict | None:
    import json
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


# --------------------------------------------------------------- children
def start_agent() -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "pi_node.agent"], cwd=ROOT)


def find_browser() -> str | None:
    for name in ("chromium-browser", "chromium", "google-chrome", "microsoft-edge"):
        if found := shutil.which(name):
            return found
    return None


def screen_env() -> dict | None:
    """The desktop session to open the screen on — also when this runs over SSH."""
    env = dict(os.environ)
    if env.get("WAYLAND_DISPLAY") or env.get("DISPLAY"):
        return env
    runtime = Path(f"/run/user/{os.getuid()}") if hasattr(os, "getuid") else None
    if runtime and (runtime / "wayland-0").exists():
        env.update(XDG_RUNTIME_DIR=str(runtime), WAYLAND_DISPLAY="wayland-0")
        return env
    if Path("/tmp/.X11-unix/X0").exists():
        env["DISPLAY"] = ":0"
        return env
    return None


def start_screen(browser: str, url: str, windowed: bool, env: dict) -> subprocess.Popen:
    flags = [
        f"--user-data-dir={Path.home() / '.config' / 'refridge-kiosk'}",  # its own profile: doesn't touch your browser
        "--touch-events=enabled", "--noerrdialogs", "--disable-infobars", "--no-first-run",
        "--disable-session-crashed-bubble", "--disable-pinch", "--overscroll-history-navigation=0",
        "--check-for-update-interval=31536000",
    ]
    if env.get("WAYLAND_DISPLAY"):
        flags.append("--ozone-platform=wayland")
    flags += [f"--app={url}", "--window-size=1024,600"] if windowed else ["--kiosk", url]
    return subprocess.Popen([browser, *flags], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------- main
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--windowed", action="store_true", help="fridge screen in a window instead of full-screen")
    parser.add_argument("--no-screen", action="store_true", help="don't open the fridge screen")
    args = parser.parse_args()

    use_venv()
    os.chdir(ROOT)
    ensure_env_file()
    sys.path.insert(0, str(ROOT))
    from pi_node.config import config  # after .env exists

    backend = config.backend_url
    host = urllib.parse.urlparse(backend).hostname or ""
    say(f"Backend: {backend}   hardware: {os.getenv('PI_HARDWARE', 'real')}")
    ensure_direct_link(host)
    if os.getenv("PI_HARDWARE", "real").lower() == "real" and not config.calibration_file.exists():
        say("Scale not calibrated yet — weights will be off. Stop this (Ctrl+C) and run:")
        say("  .venv/bin/python -m pi_node.calibrate tare 0      (shelf empty)")
        say("  .venv/bin/python -m pi_node.calibrate cal 0 500   (500 g on the shelf)")

    agent = start_agent()
    screen: subprocess.Popen | None = None
    browser = None if args.no_screen else find_browser()
    env = None if args.no_screen else screen_env()
    if not args.no_screen and (browser is None or env is None):
        say("No browser or desktop found — running without the fridge screen." if browser is None
            else "No desktop session found (running over SSH with nobody logged in?) — no fridge screen.")

    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    backend_up = camera_up = None
    try:
        while not stopping:
            if agent.poll() is not None:
                say(f"Sensor agent exited (code {agent.returncode}) — restarting in {RESTART_DELAY_S} s")
                time.sleep(RESTART_DELAY_S)
                agent = start_agent()

            health = http_json(f"{backend}/api/health")
            if bool(health) != backend_up:
                backend_up = bool(health)
                say("Backend connected." if backend_up else
                    f"Waiting for the backend at {backend} — is main.py running on the computer, "
                    "and Python allowed through its firewall?")

            pi = http_json(f"http://127.0.0.1:{config.camera_port}/health")
            if pi and pi.get("camera") != camera_up:
                camera_up = pi.get("camera")
                say("Camera: sending pictures." if camera_up else
                    "Camera: none found yet (tried every camera device) — plug it in, it's picked up automatically.")

            if backend_up and browser and env and (screen is None or screen.poll() is not None):
                if screen is not None:
                    say(f"Fridge screen closed — reopening in {RESTART_DELAY_S} s")
                    time.sleep(RESTART_DELAY_S)
                say(f"Opening the fridge screen: {backend}/kiosk")
                screen = start_screen(browser, f"{backend}/kiosk?sim=off", args.windowed, env)

            time.sleep(1)
    finally:
        say("Stopping...")
        for p in (screen, agent):
            if p is not None and p.poll() is None:
                p.terminate()
        for p in (screen, agent):
            if p is not None:
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()


if __name__ == "__main__":
    main()
