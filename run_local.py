"""Run the whole system on one computer for testing.

Starts two processes, wired exactly like the final hybrid setup:
  1. the backend   (main.py)            http://127.0.0.1:8000
  2. a simulated Pi (pi_node.agent, sim) http://127.0.0.1:8001  <- control page

The simulated Pi pushes weights/door/sensor readings to the backend over HTTP
and serves camera frames the backend pulls — the same traffic the real Pi
will send over Wi-Fi. Moving to real hardware later means running
`python -m pi_node.agent` on the Pi and pointing the backend at it; no code
changes.

Once everything is up it opens windows fitted to your screen: the simulated
fridge (live vision view + controls) on the left, the fridge screen on the
right, and the phone app below it if there's room. They close on Ctrl+C.

  python run_local.py                        # keep existing database
  python run_local.py --seed                 # wipe the database and load weeks of demo history
  python run_local.py --camera "USB Camera"  # real camera (by name or index) + simulated scale/door
  python run_local.py --list-cameras         # what cameras are connected, and their indexes
  python run_local.py --identify             # also send new-item snapshots to Gemini (off by default)
  python run_local.py --no-windows           # just the servers

The simulated fridge window shows the live vision view: orange = you (outline + hand skeleton),
cyan = what changed, green flash = the snapshot that goes (or would go) to Gemini.

With a real camera, the scale is still simulated: on the control page, press
"Put in" for what you're adding, then actually place the item in view. The
backend sees your real hand, measures the simulated weight change, crops the
real item from the camera, and Gemini names it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
BACKEND_PORT = 8000
PI_PORT = 8001
STARTUP_TIMEOUT_S = 60

KIOSK_ASPECT = 600 / 1024        # the real fridge panel
TITLE_BAR = 40
PHONE_SIZE = (410, 860)
MIN_PHONE_HEIGHT = 420


def screen_size() -> tuple[int, int]:
    """Usable screen size in the same scaled units browsers use for window sizes."""
    if os.name == "nt":
        import ctypes
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(17)  # width, height above the taskbar
    return 1920, 1040


def window_layout(width: int, height: int) -> list[tuple[str, str, tuple[int, int], tuple[int, int]]]:
    """(name, url, size, position) per window, fitted to the screen:
    left half — the simulated fridge (live vision view + controls), full height;
    right — the fridge screen at the panel's aspect ratio, and the phone app below it if it fits."""
    left_w = width // 2
    right_w = width - left_w
    kiosk_h = min(int(right_w * KIOSK_ASPECT) + TITLE_BAR, height)
    layout = [
        ("sim-fridge", f"http://127.0.0.1:{PI_PORT}/", (left_w, height), (0, 0)),
        ("fridge-screen", f"http://127.0.0.1:{BACKEND_PORT}/kiosk", (right_w, kiosk_h), (left_w, 0)),
    ]
    phone_h = min(height - kiosk_h, PHONE_SIZE[1])
    if phone_h >= MIN_PHONE_HEIGHT:
        layout.append(("phone-app", f"http://127.0.0.1:{BACKEND_PORT}/", (PHONE_SIZE[0], phone_h), (left_w, kiosk_h)))
    return layout

BROWSER_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
]


def camera_names() -> list[str] | None:
    """Camera names in the order OpenCV numbers them (Windows/DirectShow); None elsewhere."""
    try:
        from pygrabber.dshow_graph import FilterGraph
    except ImportError:
        return None
    return FilterGraph().get_input_devices()


def resolve_camera(choice: str) -> int:
    """'1' -> 1; 'usb' / 'USB Camera' -> the index of the camera whose name contains it.
    Indexes shift when cameras are plugged in or out, so a name is the safer choice."""
    if choice.isdigit():
        return int(choice)
    names = camera_names()
    if names is None:
        sys.exit("Choosing a camera by name needs Windows + pygrabber; pass an index instead (e.g. --camera 1).")
    matches = [i for i, n in enumerate(names) if choice.lower() in n.lower()]
    if len(matches) != 1:
        listed = "\n".join(f"  {i}: {n}" for i, n in enumerate(names)) or "  (none found)"
        sys.exit(f"{'No' if not matches else 'More than one'} camera matches {choice!r}. Cameras:\n{listed}")
    print(f"Using camera {matches[0]}: {names[matches[0]]}")
    return matches[0]


def find_browser() -> str | None:
    """A Chromium-based browser, for clean app-mode windows (no tabs or address bar)."""
    for path in BROWSER_CANDIDATES:
        if Path(path).exists():
            return path
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
        if found := shutil.which(name):
            return found
    return None


def wait_until_up(urls: list[str], procs: list[subprocess.Popen]) -> bool:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    pending = list(urls)
    while pending and time.monotonic() < deadline:
        if any(p.poll() is not None for p in procs):
            return False
        try:
            urllib.request.urlopen(pending[0], timeout=1)
            pending.pop(0)
        except OSError:
            time.sleep(0.5)
    return not pending


def ensure_web_build() -> bool:
    """The fridge screen and phone-app window are the Expo web build; build it once if missing."""
    if (ROOT / "mobile" / "dist").is_dir():
        return True
    npx = shutil.which("npx")
    if not npx or not (ROOT / "mobile" / "node_modules").is_dir():
        print("  (No web build — run: cd mobile && npm install && npx expo export --platform web)")
        return False
    print("Building the app's web version (first run only, about a minute)...", flush=True)
    result = subprocess.run([npx, "expo", "export", "--platform", "web"], cwd=ROOT / "mobile")
    return result.returncode == 0


def open_windows(have_web_build: bool, profiles_dir: Path) -> list[subprocess.Popen]:
    windows = [w for w in window_layout(*screen_size()) if have_web_build or w[0] == "sim-fridge"]
    browser = find_browser()
    if browser is None:
        for _, url, _, _ in windows:
            webbrowser.open(url)  # regular tabs — still works, just not panel-sized
        return []
    opened = []
    for name, url, (w, h), (x, y) in windows:
        # A separate, fresh profile per window makes it its own browser process — so the size
        # and position apply even if the browser is already open (a reused profile would restore
        # the last run's window placement instead), and Ctrl+C can close it.
        profile = profiles_dir / name
        opened.append(subprocess.Popen(
            [browser, f"--app={url}", f"--window-size={w},{h}", f"--window-position={x},{y}",
             f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ))
    return opened


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", action="store_true", help="reset the database and load demo history")
    parser.add_argument("--camera", metavar="NAME_OR_INDEX",
                        help='use a real camera instead of the synthetic feed, e.g. "USB Camera" or 1')
    parser.add_argument("--list-cameras", action="store_true", help="show connected cameras and exit")
    parser.add_argument("--no-windows", action="store_true", help="don't open the app windows")
    parser.add_argument("--identify", action="store_true",
                        help="send new-item snapshots to Gemini (off by default while testing the camera)")
    parser.add_argument("--db", default="refridge.db")
    args = parser.parse_args()

    if args.list_cameras:
        names = camera_names()
        print("\n".join(f"  {i}: {n}" for i, n in enumerate(names or [])) if names
              else "No camera names available (needs Windows + pygrabber); try indexes 0, 1, 2.")
        return

    real_camera = args.camera is not None
    camera_index = resolve_camera(args.camera) if real_camera else 0

    # One weighed shelf (the real fridge has one scale); the rest of the fridge isn't weighed.
    base_env = {**os.environ, "PYTHONUNBUFFERED": "1", "DATABASE_PATH": args.db, "NUM_SHELVES": "1"}

    if args.seed:
        db_path = ROOT / args.db
        if db_path.exists():
            db_path.unlink()
        subprocess.run([sys.executable, "scripts/seed_demo.py"], cwd=ROOT, env=base_env, check=True)

    have_web_build = args.no_windows or ensure_web_build()

    backend_env = {
        **base_env,
        "SCALE_SOURCE": "network",
        "PI_AGENT_URL": f"http://127.0.0.1:{PI_PORT}",
        "ENABLE_FRIDGE_LOOP": "true",
        "API_PORT": str(BACKEND_PORT),
        "IDENTIFY_ITEMS": "on" if args.identify else "off",
        # Real camera: MediaPipe finds real hands/arms. The synthetic feed draws a cartoon hand that
        # MediaPipe (correctly) doesn't recognize, so it uses motion detection instead.
        "HAND_DETECTOR": "mediapipe" if real_camera else "motion",
    }
    pi_env = {
        **base_env,
        "PI_HARDWARE": "sim",
        "PI_CAMERA": "webcam" if real_camera else "sim",
        "CAMERA_INDEX": str(camera_index),
        "BACKEND_URL": f"http://127.0.0.1:{BACKEND_PORT}",
        "CAMERA_PORT": str(PI_PORT),
        "CONDITIONS_PUSH_S": "5",
    }

    procs = [
        subprocess.Popen([sys.executable, "main.py"], cwd=ROOT, env=backend_env),
        subprocess.Popen([sys.executable, "-m", "pi_node.agent"], cwd=ROOT, env=pi_env),
    ]
    windows: list[subprocess.Popen] = []
    profiles_dir = Path(tempfile.mkdtemp(prefix="refridge-windows-"))

    try:
        up = wait_until_up(
            [f"http://127.0.0.1:{BACKEND_PORT}/api/health", f"http://127.0.0.1:{PI_PORT}/health"], procs)
        if not up:
            print("Startup failed — see the errors above.")
            return
        print(
            "\n"
            f"  Fridge screen      http://127.0.0.1:{BACKEND_PORT}/kiosk\n"
            f"  Phone app          http://127.0.0.1:{BACKEND_PORT}/        (or: cd mobile && npx expo start)\n"
            f"  Simulated fridge   http://127.0.0.1:{PI_PORT}             <- put things in here\n"
            f"  Backend API        http://127.0.0.1:{BACKEND_PORT}/docs\n"
            "\n  Ctrl+C to stop.\n",
            flush=True,
        )
        if not args.no_windows:
            windows = open_windows(have_web_build, profiles_dir)

        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        print("A process exited — shutting down the other.")
    except KeyboardInterrupt:
        pass
    finally:
        for p in windows + procs:
            if p.poll() is None:
                p.terminate()
        for p in windows + procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        shutil.rmtree(profiles_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
