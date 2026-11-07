"""
vision/capture.py
Records automatically while a hand (or anything new) is in the camera's view,
saves the best frames, and sends them to GPT to identify the food.

How it knows a hand is there: for the first moment it learns what the empty
scene looks like, then measures how much of each frame differs from that.

Run from the fridge_bot folder:   python vision/capture.py
Keys (click the preview window first):
    SPACE = start recording manually    B = re-learn the empty scene    Q = quit
Keep your hands out of view for the first 2 seconds after starting.
"""
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from identify import identify_capture   # sends each capture to GPT

# ---- Settings you'll tweak ----
CAMERA_INDICES = [0]      # [overhead, side]. Change to [0, 1] once the second camera is plugged in
DETECT_CAMERA = 0         # which camera in the list decides when to record (0 = first)
START_FRAC = 0.05         # start recording when more than 5% of the view has changed
STOP_FRAC = 0.025         # stop counting as "present" below 2.5%
START_DELAY = 0.1         # something must be present this long to start (ignores flickers)
STOP_DELAY = 0.6          # stop after the view has been empty this long
MAX_RECORD_SECONDS = 6    # safety cap on clip length
MIN_RECORD_SECONDS = 0.4  # throw away clips shorter than this
WARMUP_SECONDS = 2.0      # time spent learning the empty scene
PRE_SECONDS = 1.0         # also keep frames from just BEFORE recording started
FRAME_STEP = 1            # while recording, keep every frame (fast motions need them all)
MIN_BRIGHTNESS = 40       # ignore frames darker than this (0-255)
MIN_OBJECT_FRAC = 0.03    # a frame counts as "object in view" if 3%+ of it differs from empty
AUTO_IDENTIFY = True      # send each capture to GPT automatically
FRAMES_TO_SAVE = 6        # how many frames per camera to keep from the motion, in order
SAVE_DIR = Path("captures")
SERIAL_PORT = None        # later: e.g. "/dev/cu.usbserial-0001" for the ESP32
SERIAL_BAUD = 115200
FPS_GUESS = 30


class Camera:
    """Reads frames nonstop in the background so we always have fresh ones."""

    def __init__(self, index, name):
        self.name = name
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"Could not open camera {index} ({name})")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.lock = threading.Lock()
        self.latest = None
        self.pre_buffer = deque(maxlen=int(FPS_GUESS * PRE_SECONDS) + 5)
        self.clip = None          # becomes a list while recording
        self.count = 0
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.01)
                continue
            with self.lock:
                self.count += 1
                self.latest = frame
                self.pre_buffer.append(frame)
                if self.clip is not None and self.count % FRAME_STEP == 0:
                    self.clip.append(frame)

    def start_clip(self):
        with self.lock:
            self.clip = list(self.pre_buffer)   # start with the frames from just before

    def stop_clip(self):
        with self.lock:
            clip, self.clip = self.clip or [], None
        return clip

    def get_latest(self):
        with self.lock:
            return None if self.latest is None else self.latest.copy()

    def stop(self):
        self.running = False
        time.sleep(0.05)
        self.cap.release()


class PresenceDetector:
    """Learns the empty scene, then reports what fraction of the view is 'new'."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.subtractor = cv2.createBackgroundSubtractorMOG2(
            history=300, varThreshold=50, detectShadows=False)
        self.warmup_until = time.time() + WARMUP_SECONDS

    def update(self, frame, learn):
        small = cv2.resize(frame, (320, int(320 * frame.shape[0] / frame.shape[1])))
        small = cv2.GaussianBlur(small, (5, 5), 0)
        # learn = keep updating the idea of the empty scene; don't learn while recording,
        # or a hand held still would slowly become "background"
        mask = self.subtractor.apply(small, learningRate=-1 if learn else 0)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        warming = time.time() < self.warmup_until
        frac = 0.0 if warming else cv2.countNonZero(mask) / mask.size
        return frac, mask, warming



        
def sharpness(frame):
    """Higher = sharper. Blurry frames have few hard edges, so a low score."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def _normalized(frame):
    """Small, blurred grayscale version with overall brightness and contrast
    removed, so the camera's automatic exposure changes don't count as 'different'."""
    g = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (5, 5), 0).astype(np.float32)
    return (g - g.mean()) / (g.std() + 1e-6)


def object_amount(frame, background):
    """Fraction of the frame that differs from the empty background (0 to 1)."""
    diff = np.abs(_normalized(frame) - _normalized(background))
    return float((diff > 0.8).mean())


def pick_best(clip):
    """Find the stretch where something (hand and/or object) is in view, split it
    into FRAMES_TO_SAVE equal parts, and keep the sharpest frame from each part.
    GPT then looks at all of them and works out which ones show the food."""
    if len(clip) < 3:
        return {}
    before, after = clip[0], clip[-1]   # empty scene before the hand arrived and after it left
    # A frame only counts if it differs from BOTH empty scenes
    scores = [min(object_amount(f, before), object_amount(f, after)) for f in clip]
    peak = max(scores)
    if peak < MIN_OBJECT_FRAC:
        print("    Nothing clearly in view")
        return {}
    cutoff = max(MIN_OBJECT_FRAC, 0.5 * peak)
    keep = [i for i, s in enumerate(scores) if s >= cutoff]
    first, last = keep[0], keep[-1]
    usable = clip[first:last + 1]
    print(f"    Something in view in frames {first}-{last} ({len(usable)} of {len(clip)})")
    n = len(usable)
    parts = min(FRAMES_TO_SAVE, n)
    picks = {}
    for p in range(parts):
        chunk = usable[p * n // parts:(p + 1) * n // parts]
        if chunk:
            picks[f"{p + 1:02d}"] = max(chunk, key=sharpness)
    return picks


def save_capture(results):
    folder = SAVE_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for cam_name, frames in results.items():
        for label, frame in frames.items():
            path = folder / f"{cam_name}_{label}.jpg"
            cv2.imwrite(str(path), frame)
            paths.append(path)
    return folder, paths


def start_serial_listener(trigger):
    """Later: the ESP32 prints 'TRIGGER' over USB when its sensor fires."""
    if not SERIAL_PORT:
        return
    try:
        import serial
    except ImportError:
        print("pyserial not installed, so the sensor trigger is off. Run: pip install pyserial")
        return

    def loop():
        with serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=1) as ser:
            while True:
                line = ser.readline().decode(errors="ignore").strip()
                if line == "TRIGGER":
                    trigger.set()

    threading.Thread(target=loop, daemon=True).start()
    print(f"Listening for sensor triggers on {SERIAL_PORT}")


def draw_preview(cams, status, frac, mask):
    frames = [f for f in (c.get_latest() for c in cams) if f is not None]
    if not frames:
        return
    h = 360
    tiles = [cv2.resize(f, (int(f.shape[1] * h / f.shape[0]), h)) for f in frames]
    preview = cv2.hconcat(tiles)
    color = (0, 0, 255) if status == "RECORDING" else (0, 200, 255)
    cv2.putText(preview, f"{status}   change: {frac * 100:.1f}%", (15, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)
    if mask is not None:  # small black-and-white view of what it thinks is "new"
        m = cv2.cvtColor(cv2.resize(mask, (160, 90)), cv2.COLOR_GRAY2BGR)
        preview[h - 95:h - 5, preview.shape[1] - 165:preview.shape[1] - 5] = m
    cv2.imshow("fridge capture", preview)


def main():
    names = ["overhead", "side"]
    cams = []
    for i, idx in enumerate(CAMERA_INDICES):
        try:
            cams.append(Camera(idx, names[i] if i < len(names) else f"cam{i}"))
        except RuntimeError as e:
            print("Warning:", e)
    if not cams:
        raise SystemExit("No cameras opened. Check CAMERA_INDICES and camera permissions.")
    detect_cam = cams[min(DETECT_CAMERA, len(cams) - 1)]

    trigger = threading.Event()
    start_serial_listener(trigger)
    presence = PresenceDetector()
    print("Learning the empty scene... keep hands out of view for 2 seconds.")

    recording = False
    started_at = present_since = quiet_since = None
    frac, mask, status = 0.0, None, "LEARNING"

    while True:
        now = time.time()
        frame = detect_cam.get_latest()
        if frame is not None:
            frac, mask, warming = presence.update(frame, learn=not recording)
            status = "RECORDING" if recording else ("LEARNING" if warming else "WAITING")

        draw_preview(cams, status, frac, mask)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("b"):
            presence.reset()
            print("Re-learning the empty scene...")
        if key == ord(" "):
            trigger.set()

        if not recording:
            # Something new in view? It must stay a moment so flickers don't count.
            if frac > START_FRAC:
                present_since = present_since or now
            else:
                present_since = None
            started_by_presence = present_since and now - present_since >= START_DELAY
            if started_by_presence or trigger.is_set():
                trigger.clear()
                for c in cams:
                    c.start_clip()
                recording, started_at, quiet_since = True, now, None
                print("Hand detected, recording...")
        else:
            trigger.clear()
            # Stop once the view has been empty for STOP_DELAY, or the clip is too long
            if frac < STOP_FRAC:
                quiet_since = quiet_since or now
            else:
                quiet_since = None
            empty_long_enough = quiet_since and now - quiet_since >= STOP_DELAY
            if empty_long_enough or now - started_at >= MAX_RECORD_SECONDS:
                recording, present_since = False, None
                clips = {c.name: c.stop_clip() for c in cams}
                duration = now - started_at
                if duration < MIN_RECORD_SECONDS:
                    print(f"Too short ({duration:.1f}s), ignored.")
                else:
                    results = {name: pick_best(clip) for name, clip in clips.items()}
                    folder, paths = save_capture(results)
                    print(f"Recorded {duration:.1f}s. Saved {len(paths)} frames to {folder}/")
                    for p in paths:
                        print("   ", p)
                    if AUTO_IDENTIFY and paths:
                        # Run GPT in the background so the camera preview doesn't freeze
                        threading.Thread(target=identify_capture, args=(folder,), daemon=True).start()
                presence.reset()  # re-learn in case an item was left in view

    for c in cams:
        c.stop()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()