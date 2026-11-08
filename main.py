"""Backend entry point: runs the API server, and optionally the fridge loop.

With ENABLE_FRIDGE_LOOP=false only the API starts — enough to run the app
off seeded data (section 15's hardware-failure fallback). With it on, the
loop reads weights/door from the scale source (a Pi pushing over the network,
or the simulated Pi from `run_local.py`) and frames from the Pi's camera
server. When a shelf's weight settles somewhere new, the before and after photos go to Gemini
with the weight change to say what was put in or taken out.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("refridge.main")

def identify_items_enabled() -> bool:
    """IDENTIFY_ITEMS=off skips the Gemini call (testing the camera without AI)."""
    return os.getenv("IDENTIFY_ITEMS", "on").lower() not in ("off", "false", "0")


# A settled weight this far from the last one means something was put in or taken out.
CHANGE_MIN_G = float(os.getenv("CHANGE_MIN_G", "8"))
# Taken out: a drop at least this share of the item's weight is the whole item; less is some used.
WHOLE_ITEM_SHARE = 0.7


class WeightWatcher:
    """Watches each shelf's settled weight. A shelf that settles at least CHANGE_MIN_G away from
    its last weight has had something put in or taken out. Smaller settled drifts are folded into
    the baseline, so slow load-cell creep never adds up to a change."""

    def __init__(self, scale):
        self.scale = scale
        self.baseline: dict[int, float] = {}

    def reset(self) -> None:
        self.baseline = {}

    def steady(self) -> bool:
        """Every shelf has settled at its baseline: nothing is being put in or taken out."""
        for shelf in range(self.scale.num_shelves):
            now = self.scale.settled(shelf)
            if now is None and self.scale.read_latest(shelf) is not None:
                return False
            if now is not None and shelf in self.baseline and abs(now - self.baseline[shelf]) >= CHANGE_MIN_G:
                return False
        return True

    def changes(self) -> dict[int, tuple[float, float]]:
        """{shelf: (weight before, weight now)} for each shelf that settled somewhere new."""
        found = {}
        for shelf in range(self.scale.num_shelves):
            now = self.scale.settled(shelf)
            if now is None:
                continue
            before = self.baseline.setdefault(shelf, now)
            if abs(now - before) >= CHANGE_MIN_G:
                found[shelf] = (before, now)
            else:
                self.baseline[shelf] = now  # drift, or nothing happened
        return found

    def accept(self, shelf: int, grams: float) -> None:
        self.baseline[shelf] = grams


def _shelf_items(db, shelf: int):
    """Active fridge items that could be on this shelf: on it, or with no shelf (added by hand)."""
    return [i for i in db.active_items(location="fridge") if i["shelf"] in (shelf, None)]


def _which_was_taken(db, items, info: dict, grams: float):
    """The item taken out: the one Gemini picked from the list, else the one it named, else the
    only one there, else the one whose weight is closest to what left (within a quarter)."""
    if info.get("index") is not None:
        return items[info["index"]]
    named = (info.get("item_name") or "").strip().lower()
    for item in items:
        if named and db.get_product(item["product_id"])["name"].strip().lower() == named:
            return item
    if len(items) == 1:
        return items[0]
    if items:
        closest = min(items, key=lambda i: abs(i["grams"] - grams))
        if abs(closest["grams"] - grams) <= max(15.0, 0.25 * grams):
            return closest
    return None


def handle_change(db, shelf: int, before_frame, after_frame, grams_before: float, grams_after: float) -> None:
    """The scale says something was put in or taken out; the two whole photos and Gemini say what."""
    from intelligence.expiry import resolve_expiration
    from inventory import events as inv_events
    from vision import snapshots
    from vision.classifier import identify_change
    from vision.debug import view

    delta = grams_after - grams_before
    items = _shelf_items(db, shelf)
    names = [db.get_product(i["product_id"])["name"] for i in items]
    # The camera page keeps the photo that shows the item: after for put in, before for taken out.
    photo = snapshots.save(after_frame if delta > 0 else before_frame, grams=delta)
    log.info("Shelf %d: %+.0f g, asking what changed (%s)", shelf, delta, photo.name)
    if identify_items_enabled():
        info = identify_change(before_frame, after_frame, delta, names)
    else:
        info = {"item_name": "Unknown Item", "category": None, "visible_expiration_date": None,
                "days_until_expired": None, "confidence": 0.0, "needs_confirmation": True,
                "skipped": True, "index": None}
    view.gemini_result(info)

    if delta > 0:
        snapshots.record(photo, info)
        if info.get("needs_confirmation"):
            inv_events.apply_needs_review(db, shelf=shelf, meta={"candidate": info, "grams": delta})
            return
        expires, estimated = resolve_expiration(
            printed_date=info.get("visible_expiration_date"), estimated_days=info.get("days_until_expired"),
            name=info["item_name"], category=info.get("category"),
        )
        product_id = db.get_or_create_product(info["item_name"], category=info.get("category"))
        inv_events.apply_add(db, product_id, delta, shelf=shelf, expiration_date=expires,
                             expiration_estimated=estimated, confidence=info.get("confidence"))
        log.info("Put in: %s, %.0f g", info["item_name"], delta)
        return

    taken = -delta
    item = _which_was_taken(db, items, info, taken)
    if item is None:
        snapshots.record_removed(photo, None)
        inv_events.apply_needs_review(db, shelf=shelf, meta={"reason": "taken out, not sure what",
                                                             "grams": taken, "candidate": info})
        return
    name = db.get_product(item["product_id"])["name"]
    snapshots.record_removed(photo, name)
    if taken >= WHOLE_ITEM_SHARE * item["grams"]:
        inv_events.apply_remove(db, item["id"])
        log.info("Taken out: %s", name)
    else:
        inv_events.apply_consume(db, item["id"], taken, meta={"source": "scale"})
        log.info("Used %.0f g of %s", taken, name)


LOOP_INTERVAL_S = 0.1  # ~10 fps; a remote Pi camera is fetched over HTTP each tick


def _weights_text(scale) -> str:
    return "  ".join(f"shelf {s}: {g:.0f} g" for s, g in sorted(scale.snapshot().items()))


STILL_FRAMES = 5  # consecutive still frames, median-combined into the before/after photos
STILL_PIXEL_DIFF = 25  # per-pixel change between frames that counts as movement
STILL_FRACTION = 0.004  # under this share of pixels moving, the picture is still
STILL_TIMEOUT_S = 4.0  # after a weight change, wait at most this long for the hand to clear the picture
# When the door switch reports closed, the door has already been swinging shut (darkening the view,
# its edge crossing the picture) for about a second. The door-close check uses the still view from
# before that, and never a frame much darker than the scene it's compared with.
CLOSE_GUARD_S = 1.5
# The camera's auto-exposure and white balance keep shifting for a few seconds after the door opens
# and the light changes; before photos from then are only used if nothing better is taken.
LIGHT_SETTLE_S = float(os.getenv("LIGHT_SETTLE_S", "6"))
DARKER_THAN_REFERENCE = 0.7


def _is_still(prev, frame) -> bool:
    """Nothing moving between two frames (compared small, so sensor noise doesn't count)."""
    import cv2
    import numpy as np

    def small(f):
        h, w = f.shape[:2]
        return cv2.GaussianBlur(cv2.cvtColor(cv2.resize(f, (160, max(1, 160 * h // w))), cv2.COLOR_BGR2GRAY), (5, 5), 0)

    if prev is None:
        return False
    moved = cv2.absdiff(small(prev), small(frame)) > STILL_PIXEL_DIFF
    return float(np.mean(moved)) < STILL_FRACTION


def _open_view(history, reference_frame, now: float):
    """The still view of the open fridge for the door-close check, from `history` (time, frame)
    pairs of still frames: the last few from before the door began to close. None if there are
    none, so the check isn't run against a half-dark picture."""
    import numpy as np

    from vision.change import steady_frame

    floor = DARKER_THAN_REFERENCE * float(np.mean(reference_frame))
    usable = [f for t, f in history if t <= now - CLOSE_GUARD_S and float(np.mean(f)) >= floor]
    return steady_frame(usable[-STILL_FRAMES:]) if usable else None


def run_fridge_loop(stop_event: threading.Event) -> None:
    """The scale decides when: a shelf settling at least CHANGE_MIN_G from where it was. The camera's
    before photo (the latest still view while nothing was happening) and after photo (once the
    picture is still again) go to Gemini with the weight change, which says what it was."""
    from collections import deque

    from inventory.database import get_db
    from sensors.scale import get_scale_reader
    from vision.camera import make_camera
    from vision.change import steady_frame
    from vision.debug import view

    db = get_db(os.getenv("DATABASE_PATH", "refridge.db"))
    scale = get_scale_reader()  # same instance the /api/pi/* endpoints feed
    watcher = WeightWatcher(scale)

    with make_camera() as cam:
        before_frame = None
        before_settled = False  # the before photo was taken after the light settled
        still: deque = deque(maxlen=STILL_FRAMES)
        history: deque = deque(maxlen=60)  # (time, frame) of still frames, ~6 s, for the door-close check
        pending: dict[int, tuple[float, float]] = {}
        pending_since = 0.0
        prev = None
        door_was_open = False
        door_opened_at = 0.0
        log.info("Fridge loop started (scale: %s, camera: %s); changes of %g g or more are checked",
                 scale.source, type(cam).__name__, CHANGE_MIN_G)

        while not stop_event.is_set():
            try:
                door_open = scale.door_is_open()
                frame = cam.read_frame()
                now = time.monotonic()
                is_still = _is_still(prev, frame)
                prev = frame
                if is_still:
                    still.append(frame)
                    history.append((now, frame))
                else:
                    still.clear()

                if door_open and not door_was_open:
                    watcher.reset()
                    before_frame, before_settled = None, False
                    pending = {}
                    door_opened_at = now
                    status = "Door opened"

                elif door_open:
                    light_ok = now - door_opened_at >= LIGHT_SETTLE_S
                    if not pending:
                        pending = watcher.changes()
                        pending_since = now
                    if pending:
                        # Weight settled somewhere new: wait for the hand to clear the picture.
                        status = "Weight changed - waiting for a clear picture"
                        clear = len(still) == STILL_FRAMES
                        if clear or now - pending_since >= STILL_TIMEOUT_S:
                            after = steady_frame(list(still)) if clear else frame
                            for shelf, (w0, w1) in pending.items():
                                w1 = scale.settled(shelf) or w1  # the latest settled weight
                                handle_change(db, shelf, before_frame if before_frame is not None else after,
                                              after, w0, w1)
                                watcher.accept(shelf, w1)
                            before_frame, before_settled = after, light_ok
                            pending = {}
                            status = "Done - ready for the next one"
                    else:
                        # Nothing happening: keep the before photo fresh, so its light matches the after.
                        if len(still) == STILL_FRAMES and watcher.steady() and (light_ok or not before_settled):
                            before_frame, before_settled = steady_frame(list(still)), light_ok
                        status = ("Ready - put something in or take something out" if light_ok
                                  else "Adjusting to the light")

                elif door_was_open:
                    # Door just closed: a change the scale settled on while it closed still counts,
                    # photographed from the last still view before the door began to close.
                    found = pending or watcher.changes()
                    if found and before_frame is not None:
                        after = _open_view(history, before_frame, now)
                        for shelf, (w0, w1) in found.items():
                            handle_change(db, shelf, before_frame, after if after is not None else before_frame, w0, w1)
                    pending, before_frame = {}, None
                    history.clear()
                    status = "Door closed"
                else:
                    status = "Door closed"

                view.frame(frame, door_open=door_open, hand_boxes=[], status=f"{status}   |   {_weights_text(scale)}")
                door_was_open = door_open
            except Exception:
                # A dropped packet from the Pi shouldn't kill the loop.
                log.exception("Fridge loop tick failed; continuing")
            time.sleep(LOOP_INTERVAL_S)


def _open_camera_page(port: int) -> None:
    """Open the live camera page (/vision) once the server answers."""
    import urllib.request
    import webbrowser

    url = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{url}/api/health", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    log.info("Live camera: %s/vision", url)
    webbrowser.open(f"{url}/vision")


def clear_shelves(db) -> int:
    """Start each run with an empty shelf: what the camera put on a shelf last time is cleared,
    with the shelf's open "what is this?" prompts. Not logged as eaten or thrown out, so it never
    counts in the analytics. The freezer, the pantry and things added by hand (no shelf) stay."""
    items = [i for i in db.active_items(location="fridge") if i["shelf"] is not None]
    for item in items:
        db.mark_item_removed(item["id"])
    with db.cursor() as cur:
        cur.execute("SELECT id FROM events WHERE event_type = 'needs_review' AND resolved = 0 AND shelf IS NOT NULL")
        open_prompts = [row["id"] for row in cur.fetchall()]
    for event_id in open_prompts:
        db.resolve_event(event_id)
    return len(items)


def main() -> None:
    import sys

    import uvicorn

    from api.server import app

    port = int(os.getenv("API_PORT", "8000"))
    stop_event = threading.Event()
    if os.getenv("ENABLE_FRIDGE_LOOP", "false").lower() == "true":
        if os.getenv("CLEAR_SHELF_ON_START", "on").lower() not in ("off", "false", "0"):
            from inventory.database import get_db

            cleared = clear_shelves(get_db(os.getenv("DATABASE_PATH", "refridge.db")))
            log.info("Started with an empty shelf: cleared %d item(s) (CLEAR_SHELF_ON_START=off to keep them)", cleared)
        thread = threading.Thread(target=run_fridge_loop, args=(stop_event,), daemon=True)
        thread.start()
        # On a desktop, show what the camera sees and the photos it takes (VISION_WINDOW=off to skip).
        desktop = os.name == "nt" or sys.platform == "darwin"
        if desktop and os.getenv("VISION_WINDOW", "on").lower() not in ("off", "false", "0"):
            threading.Thread(target=_open_camera_page, args=(port,), daemon=True).start()
    else:
        log.info("Fridge sensor loop disabled (ENABLE_FRIDGE_LOOP=false) — serving the API only")

    # access_log off: the Pi posts weights ~10x/second, which would bury everything else.
    uvicorn.run(app, host=os.getenv("API_HOST", "0.0.0.0"), port=port, access_log=False)
    stop_event.set()


if __name__ == "__main__":
    main()
