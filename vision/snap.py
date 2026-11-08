"""Press SPACE, put something in the fridge, take your hand out -> see the item.

A standalone test bench for the camera, separate from the backend's fridge
loop (main.py): no server, scale, door, or database. It reuses
  vision/people.py   MediaPipe's hand skeleton model: is a hand in view?
  vision/change.py   steady_frame + detect_changes: clean before/after photos -> what's new

"Someone is reaching in" here = a hand skeleton is found, or the picture is
moving. It deliberately ignores people.py's body-segmentation mask: in testing
it marked skin-coloured food (oranges, shallots) as "person" — 10-30% of a
hand-free frame — so with a few items on the shelf it never saw the hand leave.
Food doesn't move; an arm reaching in always does.

Run from the fridge_bot folder:
    python -m vision.snap              # camera 0
    python -m vision.snap --camera 1   # another camera
    python -m vision.snap --open       # also open each crop in VS Code
    python -m vision.snap --gpt        # name each item with GPT and add it to the kiosk
                                       # (needs OPENAI_API_KEY in .env and the backend running)

Keys (click the preview window first):
    SPACE  take the "before" photo and start watching (again, to cancel)
    Q/ESC  quit

Crops are saved to data/snaps/. To send each one somewhere (e.g. GPT), fill in
`on_capture` below.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import requests

from vision.camera import Camera
from vision.change import detect_changes, steady_frame
from vision.people import make_detector

SAVE_DIR = Path(__file__).resolve().parent.parent / "data" / "snaps"
STEADY_FRAMES = 5        # hand-free frames median-combined into each photo (removes noise and blur)
CROP_PADDING = 0.20      # grow the item's box by this share on each side, so it isn't cut off
MERGE_GAP = 0.06         # changed patches closer than this share of the frame are one item
                         # (a bagged or shiny item breaks into several patches)
MIN_CROP = 0.35          # never crop smaller than this share of the frame's short side; detection often
                         # catches only part of a bagged item (you see the shelf through clear plastic)
TOP_EDGE_WEIGHT = 0.25   # a patch touching the top of the frame is usually a bag flap hanging into view,
                         # not the item on the shelf: it counts for this much of its area
UNSURE_BELOW = 0.70      # GPT confidence under this: add as "Unknown" with its photo
SNAP_DISPLAY_PX = 400    # longest side of the snapshot window
CAMERA_DROPOUT_S = 3.0   # no frames this long: show "not responding" and keep reopening the camera
CAMERA_SIZE = (1280, 720)  # plenty for naming food; full 1080p stalled over a USB hub in testing
DEFAULT_API = "http://localhost:8000"
NOT_WEIGHED = 0          # no scale in this test bench; the kiosk shows "Not weighed" for 0 g
CAMERA_SHELF = 0         # everything the camera sees is on the shelf (the kiosk's "Shelf" row)
ENTER_FRAMES = 2         # present this many frames in a row = hand came in (ignores one-frame flickers)
HAND_GONE_S = 0.8        # nothing in view this long = hand left...
HAND_GONE_FRAMES = 8     # ...across at least this many frames actually seen clear (a camera that
                         # freezes for a few seconds must not count as "the hand left")
MOTION_WIDTH = 320       # motion is measured on a frame shrunk to this width (fast, ignores sensor noise)
MOTION_PIXEL_DIFF = 25   # per-pixel brightness change that counts as movement
MOTION_FRACTION = 0.01   # share of the (shrunk) frame that must move to count as someone there
PREVIEW_WINDOW = "ReFridge camera"
SNAP_WINDOW = "Snapshot"

ORANGE, CYAN, GREEN, WHITE, RED = (0, 140, 255), (255, 220, 0), (0, 200, 0), (255, 255, 255), (60, 60, 230)

Box = tuple[int, int, int, int]


def on_capture(item: np.ndarray, full_after: np.ndarray, path: Path) -> None:
    """Called once per snapshot with the cropped item (BGR), the whole "after"
    photo, and where the crop was saved. Hook GPT (or anything else) in here."""


def open_in_editor(path: Path) -> None:
    """Show a file in VS Code: its `code` command if installed, else (macOS) hand it
    to the running VS Code by its app id, which works without the command set up."""
    if cli := shutil.which("code"):
        cmd = [cli, "--reuse-window", str(path)]
    elif sys.platform == "darwin":
        cmd = ["open", "-b", "com.microsoft.VSCode", str(path)]
    else:
        print(f"Can't find VS Code's `code` command; open {path} yourself.")
        return
    subprocess.run(cmd, check=False)


class Status:
    """The preview's status line; the GPT thread updates it too."""

    def __init__(self):
        self._lock = threading.Lock()
        self.text, self.color = "SPACE: start   Q: quit", WHITE

    def set(self, text: str, color=WHITE) -> None:
        with self._lock:
            self.text, self.color = text, color

    def get(self) -> tuple[str, tuple]:
        with self._lock:
            return self.text, self.color


def identify_and_add(item: np.ndarray, full: np.ndarray, box: Box, api: str, status: Status,
                     before: np.ndarray | None = None) -> None:
    """GPT names the item (from the crop plus the whole photo with the item boxed), then
    the backend's add-item API puts it on the kiosk's Shelf. If GPT isn't sure, it goes on
    as "Unknown" with the crop attached, so the kiosk shows what was seen instead of a guess.
    Runs on a background thread: the call takes a few seconds."""
    from vision.gpt_identify import identify, model_name

    status.set(f"Asking {model_name()}...", WHITE)
    try:
        info = identify(item, full, box, before)
    except Exception as e:  # no key, network, bad model name, ...
        print(f"GPT failed: {e}")
        status.set(f"GPT failed: {str(e)[:70]}", RED)
        return
    print(f"GPT: {json_line(info)}")
    confidence = float(info.get("confidence") or 0)
    unsure = confidence < UNSURE_BELOW or not info.get("item_name")
    if unsure:
        # Its own product per sighting (with the time), so two unknowns don't merge into one tile;
        # no expiry either — a low-confidence guess about what it is says nothing about when it goes bad.
        name = f"Unknown ({time.strftime('%-I:%M %p')})"
        body = {"name": name, "grams": NOT_WEIGHED, "location": "fridge", "shelf": CAMERA_SHELF}
    else:
        name = info["item_name"]
        body = {"name": name, "grams": NOT_WEIGHED, "location": "fridge", "shelf": CAMERA_SHELF,
                "category": info.get("category"), "expiration_date": info.get("expiration_date")}
    try:
        r = requests.post(f"{api}/api/items", timeout=5, json=body)
        r.raise_for_status()
        if unsure:
            ok, jpg = cv2.imencode(".jpg", item, [cv2.IMWRITE_JPEG_QUALITY, 85])
            requests.post(f"{api}/api/items/{r.json()['item_id']}/image", data=jpg.tobytes(), timeout=5,
                          headers={"Content-Type": "image/jpeg"}).raise_for_status()
    except requests.RequestException as e:
        print(f"Couldn't add to the kiosk ({api}): {e}")
        status.set(f"GPT: {name} - but the backend at {api} isn't reachable", RED)
        return
    if unsure:
        guess = info.get("item_name") or "nothing"
        status.set(f"Not sure ({guess}? {confidence:.0%}) - added as Unknown with its photo", ORANGE)
    else:
        expires = f", good until {info['expiration_date']}" if info.get("expiration_date") else ""
        status.set(f"Added {name} ({confidence:.0%}){expires}. SPACE for the next item", GREEN)


def json_line(info: dict) -> str:
    keys = ("item_name", "category", "days_until_expired", "expiration_date", "confidence", "reasoning")
    return ", ".join(f"{k}={info.get(k)}" for k in keys)


def configure_camera(cam: Camera) -> None:
    """Ask for 1280x720 MJPEG: far less USB bandwidth than raw 1080p, so fewer stalls."""
    cap = cam._cap  # vision.camera.Camera has no settings API; this bench owns the device
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_SIZE[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_SIZE[1])
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


def read_frame_retrying(cam: Camera) -> np.ndarray | None:
    """Ride out camera dropouts without quitting: retry, and while the camera is stuck,
    reopen it every CAMERA_DROPOUT_S and show "Camera not responding" in the preview, so
    it picks up again by itself once the camera is replugged. Returns None if Q/Esc is
    pressed while waiting."""
    start = last_reopen = time.monotonic()
    announced = False
    while True:
        try:
            frame = cam.read_frame()
            if announced:
                print("Camera is back.")
            return frame
        except RuntimeError:
            pass
        now = time.monotonic()
        if now - start > CAMERA_DROPOUT_S:
            if not announced:
                print(f"Camera {cam.index} isn't sending video - waiting for it (unplug/replug it if this lasts)...")
                announced = True
            screen = np.zeros((360, 640, 3), np.uint8)
            cv2.putText(screen, "Camera not responding", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 1.0, RED, 2, cv2.LINE_AA)
            cv2.putText(screen, "Unplug and replug it - this picks up by itself.", (20, 210),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 1, cv2.LINE_AA)
            cv2.imshow(PREVIEW_WINDOW, screen)
            if now - last_reopen > CAMERA_DROPOUT_S:
                last_reopen = now
                try:
                    cam.close()
                    cam.open()
                    configure_camera(cam)
                except RuntimeError:
                    pass  # still unplugged; try again shortly
        if (cv2.waitKey(100) & 0xFF) in (ord("q"), 27):
            return None


# ------------------------------------------------------------------ helpers
def padded_crop(frame: np.ndarray, box: Box, padding: float = CROP_PADDING) -> tuple[np.ndarray, Box]:
    """Crop around `box` with some margin, and at least MIN_CROP of the frame's short side
    (a sliver tells GPT nothing)."""
    x, y, w, h = box
    fh, fw = frame.shape[:2]
    least = int(MIN_CROP * min(fh, fw))
    cw, ch = max(int(w * (1 + 2 * padding)), least), max(int(h * (1 + 2 * padding)), least)
    cx, cy = x + w / 2, y + h / 2
    x0, y0 = int(max(min(cx - cw / 2, fw - cw), 0)), int(max(min(cy - ch / 2, fh - ch), 0))
    x1, y1 = min(x0 + cw, fw), min(y0 + ch, fh)
    return frame[y0:y1, x0:x1].copy(), (x0, y0, x1 - x0, y1 - y0)


def _union(a: Box, b: Box) -> Box:
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


def _near(a: Box, b: Box, gap: float) -> bool:
    return (a[0] - gap <= b[0] + b[2] and b[0] - gap <= a[0] + a[2]
            and a[1] - gap <= b[1] + b[3] and b[1] - gap <= a[1] + a[3])


def merge_nearby(boxes: list[tuple[Box, int]], gap: float) -> list[tuple[Box, int]]:
    """Join (box, area) pairs that touch or sit within `gap` px of each other, until none do."""
    groups = list(boxes)
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if _near(groups[i][0], groups[j][0], gap):
                    groups[i] = (_union(groups[i][0], groups[j][0]), groups[i][1] + groups[j][1])
                    del groups[j]
                    merged = True
                    break
            if merged:
                break
    return groups


def find_new_item(before: np.ndarray, after: np.ndarray) -> Box | None:
    """Where the new item is: changed patches close together are merged into one (a bagged
    or shiny item breaks into several), and the group that changed the most wins — except
    that patches touching the top of the frame (bag flaps hanging into view) count for less."""
    regions = detect_changes(before, after)
    if not regions:
        return None
    gap = MERGE_GAP * max(after.shape[:2])
    weighted = [(r.bbox, r.area * (TOP_EDGE_WEIGHT if r.bbox[1] <= 2 else 1)) for r in regions]
    groups = merge_nearby(weighted, gap)
    return max(groups, key=lambda g: g[1])[0]


class Presence:
    """Is someone reaching in: a hand skeleton, or movement. Reports when a hand
    came in (ENTER_FRAMES in a row) and when it left (nothing for HAND_GONE_S)."""

    def __init__(self, people):
        self.people = people  # vision.people.PeopleDetector, or None (motion only)
        self.reset()

    def reset(self) -> None:
        self._prev: np.ndarray | None = None
        self._streak = 0
        self._clear = 0                # consecutive frames with nobody in view
        self._inside = False
        self._last_seen = 0.0
        self.hands: list = []          # for drawing
        self.motion_boxes: list[Box] = []
        self.present = False           # this frame

    def _motion(self, frame: np.ndarray) -> bool:
        scale = MOTION_WIDTH / frame.shape[1]
        small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
        prev, self._prev = self._prev, gray
        self.motion_boxes = []
        if prev is None:
            return False
        mask = cv2.threshold(cv2.absdiff(prev, gray), MOTION_PIXEL_DIFF, 255, cv2.THRESH_BINARY)[1]
        if cv2.countNonZero(mask) < MOTION_FRACTION * mask.size:
            return False
        contours, _ = cv2.findContours(cv2.dilate(mask, np.ones((7, 7), np.uint8)), cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        self.motion_boxes = [tuple(int(v / scale) for v in cv2.boundingRect(c)) for c in contours
                             if cv2.contourArea(c) >= 0.002 * mask.size]
        return True

    def update(self, frame: np.ndarray) -> dict:
        """Returns {"entered", "left"} for this frame; each fires once per trip."""
        self.hands = self.people.detect(frame).hands if self.people is not None else []
        moving = self._motion(frame)
        self.present = bool(self.hands) or moving
        now = time.monotonic()
        entered = left = False
        if self.present:
            self._last_seen = now
            self._streak += 1
            self._clear = 0
            if not self._inside and self._streak >= ENTER_FRAMES:
                self._inside = entered = True
        else:
            self._streak = 0
            self._clear += 1
            if self._inside and now - self._last_seen >= HAND_GONE_S and self._clear >= HAND_GONE_FRAMES:
                self._inside, left = False, True
        return {"entered": entered, "left": left}


def fit(img: np.ndarray, longest: int) -> np.ndarray:
    h, w = img.shape[:2]
    scale = longest / max(h, w)
    return cv2.resize(img, (max(int(w * scale), 1), max(int(h * scale), 1)),
                      interpolation=cv2.INTER_CUBIC if scale > 1 else cv2.INTER_AREA)


def draw_preview(frame: np.ndarray, presence: Presence, status: str, color, last_box: Box | None) -> np.ndarray:
    img = frame.copy()
    for points in presence.hands:  # hand skeleton joints
        for p in points:
            cv2.circle(img, p, 4, ORANGE, -1)
    for x, y, w, h in presence.motion_boxes:  # where things are moving
        cv2.rectangle(img, (x, y), (x + w, y + h), ORANGE, 2)
    if last_box is not None:
        x, y, w, h = last_box
        cv2.rectangle(img, (x, y), (x + w, y + h), CYAN, 2)
    cv2.rectangle(img, (0, 0), (img.shape[1], 34), (0, 0, 0), -1)
    cv2.putText(img, status, (10, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
    return img


def save(item: np.ndarray, full: np.ndarray, before: np.ndarray | None = None) -> Path:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = SAVE_DIR / f"{stamp}-item.jpg"
    cv2.imwrite(str(path), item)
    cv2.imwrite(str(SAVE_DIR / f"{stamp}-full.jpg"), full)
    if before is not None:  # lets a miss be replayed exactly
        cv2.imwrite(str(SAVE_DIR / f"{stamp}-before.jpg"), before)
    return path


# --------------------------------------------------------------- main loop
IDLE, BEFORE, WAIT_IN, WAIT_OUT, AFTER = "idle", "before", "wait_in", "wait_out", "after"


def run(camera_index: int, open_crops: bool = False, use_gpt: bool = False, api: str = DEFAULT_API) -> None:
    print("Loading hand detection (downloads ~8 MB of models the first time)...")
    people = make_detector()
    print(f"Hand detection: {'MediaPipe' if people else 'motion (MediaPipe unavailable)'}")

    state = IDLE
    presence = Presence(people)
    frames: deque[np.ndarray] = deque(maxlen=STEADY_FRAMES)
    before: np.ndarray | None = None
    last_box: Box | None = None
    status = Status()
    if use_gpt:
        from vision.gpt_identify import model_name

        print(f"GPT on ({model_name()}); items go to the kiosk at {api}")

    with Camera(camera_index) as cam:
        configure_camera(cam)
        h, w = cam.read_frame().shape[:2]
        print(f"Camera {camera_index}: {w}x{h}")
        cv2.namedWindow(PREVIEW_WINDOW)
        while True:
            frame = read_frame_retrying(cam)
            if frame is None:  # quit while waiting for the camera
                break
            event = presence.update(frame)
            present = presence.present

            if state == BEFORE:
                # The "before" photo must be hand-free, or the hand would count as a change.
                if present:
                    frames.clear()
                    status.set("Take your hand out first...", ORANGE)
                else:
                    frames.append(frame)
                    if len(frames) == STEADY_FRAMES:
                        before = steady_frame(list(frames))
                        state = WAIT_IN
                        status.set("Ready - put the item in", GREEN)
            elif state == WAIT_IN and event["entered"]:
                state = WAIT_OUT
                status.set("Hand in - place the item, then take your hand out", ORANGE)
            elif state == WAIT_OUT and event["left"]:
                frames.clear()
                state = AFTER
                status.set("Hand out - taking the picture...", WHITE)
            elif state == AFTER:
                if present:  # reached back in before the photo was taken: wait for it to leave again
                    state = WAIT_OUT
                    status.set("Hand back in - waiting for it to leave", ORANGE)
                else:
                    frames.append(frame)
                    if len(frames) == STEADY_FRAMES:
                        after = steady_frame(list(frames))
                        box = find_new_item(before, after)
                        if box is None:
                            last_box = None
                            status.set("Nothing new found. SPACE to try again", RED)
                        else:
                            item, last_box = padded_crop(after, box)
                            path = save(item, after, before)
                            print(f"Saved {path}")
                            cv2.imshow(SNAP_WINDOW, fit(item, SNAP_DISPLAY_PX))
                            if open_crops:
                                open_in_editor(path)
                            on_capture(item, after, path)
                            status.set(f"Saved {path.name}. SPACE for the next item", GREEN)
                            if use_gpt:  # after the "Saved" line, so GPT's progress messages replace it
                                threading.Thread(target=identify_and_add, args=(item, after, last_box, api, status, before), daemon=True).start()
                        state = IDLE

            cv2.imshow(PREVIEW_WINDOW, draw_preview(frame, presence, *status.get(), last_box))
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                if state == IDLE:
                    presence.reset()  # forget any hand seen before SPACE
                    frames.clear()
                    last_box = None
                    state = BEFORE
                    status.set("Taking the 'before' photo...", WHITE)
                else:
                    state = IDLE
                    status.set("Cancelled. SPACE: start   Q: quit", WHITE)

    cv2.destroyAllWindows()
    if people is not None:
        people.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--camera", type=int, default=0, help="camera index (0, 1, 2...)")
    parser.add_argument("--open", action="store_true", help="open each cropped item in VS Code")
    parser.add_argument("--gpt", action="store_true", help="name each item with GPT and add it to the kiosk")
    parser.add_argument("--api", default=DEFAULT_API, help=f"backend for --gpt (default {DEFAULT_API})")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    run(args.camera, open_crops=args.open, use_gpt=args.gpt, api=args.api.rstrip('/'))


if __name__ == "__main__":
    main()
