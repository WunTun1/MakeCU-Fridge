"""Backend entry point: runs the API server, and optionally the fridge loop.

With ENABLE_FRIDGE_LOOP=false only the API starts — enough to run the app
off seeded data (section 15's hardware-failure fallback). With it on, the
loop reads weights/door from the scale source (a Pi pushing over the network,
or the simulated Pi from `run_local.py`) and frames from the Pi's camera
server, then runs vision + fusion once per hand trip.
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

CONSUME_MATCH_TOLERANCE_G = 20.0  # an item "heavy enough" to have lost X grams may read slightly under X


def identify_items_enabled() -> bool:
    """IDENTIFY_ITEMS=off skips the Gemini call for new items (testing the camera without AI)."""
    return os.getenv("IDENTIFY_ITEMS", "on").lower() not in ("off", "false", "0")


def shelf_band(shelf: int, num_shelves: int) -> tuple[float, float]:
    """Vertical slice of the camera frame (normalized y0, y1) that a shelf
    occupies. Equal bands by default; override with SHELF_BANDS="0-0.45,0.45-1"
    once the real camera is mounted and you can see where each shelf lands."""
    spec = os.getenv("SHELF_BANDS", "").strip()
    if spec:
        y0, y1 = spec.split(",")[shelf].split("-")
        return float(y0), float(y1)
    return shelf / num_shelves, (shelf + 1) / num_shelves


# A new patch smaller than this share of the frame isn't a food someone put in (a reflection, a
# speck): the camera alone decides what was added, so it has to be something item-sized.
MIN_FOOD_FRACTION = 0.01


def _in_band(bbox, frame_h: int, band: tuple[float, float]) -> bool:
    _, y, _, h = bbox
    center = (y + h / 2) / frame_h
    return band[0] <= center < band[1]


def _known_items_for_shelf(db, shelf: int, frame):
    from vision.tracking import KnownItem, color_histogram, patch_box

    known = []
    for item in db.active_items(shelf=shelf):
        if item["position_x"] is None:
            continue
        position = (item["position_x"], item["position_y"])
        known.append(KnownItem(
            item_id=item["id"], position=position,
            color_hist=color_histogram(frame, patch_box(position, frame.shape)),
        ))
    return known


def _handle_trip(
    db, shelf: int, num_shelves: int, before_frame, after_frame, weight_before: float, weight_after: float
) -> None:
    from fusion.reconcile import CameraObservation, MovedItem, NewRegion, VanishedItem, reconcile_shelf
    from intelligence.expiry import resolve_expiration
    from inventory import events as inv_events
    from vision import tracking
    from vision.camera import crop
    from vision.change import detect_changes
    from vision import snapshots
    from vision.classifier import identify_item

    from vision.debug import view

    band = shelf_band(shelf, num_shelves)
    frame_h = after_frame.shape[0]
    regions = [r for r in detect_changes(before_frame, after_frame) if _in_band(r.bbox, frame_h, band)]
    if regions:
        view.changes([r.bbox for r in regions])
    known = _known_items_for_shelf(db, shelf, before_frame)
    result = tracking.match(known, regions, before_frame, after_frame)
    min_area = MIN_FOOD_FRACTION * after_frame.shape[0] * after_frame.shape[1]
    result.new_regions = [r for r in result.new_regions if r.bbox[2] * r.bbox[3] >= min_area]

    observation = CameraObservation(
        moved=[MovedItem(item_id, tracking.normalized_position(r.bbox, after_frame.shape))
               for item_id, r in result.moved],
        vanished=[
            VanishedItem(item_id=i, product_id=db.get_item(i)["product_id"], grams=db.get_item(i)["grams"])
            for i in result.vanished_item_ids
        ],
        new_regions=[NewRegion(index=i, position=tracking.normalized_position(r.bbox, after_frame.shape), bbox=r.bbox)
                     for i, r in enumerate(result.new_regions)],
    )

    decisions = reconcile_shelf(shelf, weight_before, weight_after, observation)
    if decisions:
        log.info("Shelf %d: %+.0f g -> %s", shelf, weight_after - weight_before, ", ".join(d.kind for d in decisions))
    for d in decisions:
        if d.kind == "move":
            inv_events.apply_move(db, d.item_id, shelf, d.position)
        elif d.kind == "remove":
            inv_events.apply_remove(db, d.item_id)
        elif d.kind == "consume":
            visible = [i for i in db.active_items(shelf=shelf) if i["grams"] + CONSUME_MATCH_TOLERANCE_G >= d.grams]
            if len(visible) == 1:
                inv_events.apply_consume(db, visible[0]["id"], d.grams)
            else:
                inv_events.apply_needs_review(db, shelf=shelf, meta={"reason": d.note, "grams": d.grams})
        elif d.kind == "add":
            box = d.region.bbox if d.region and d.region.bbox else None
            region_crop = crop(after_frame, box) if box else after_frame
            view.gemini_sending(box)
            # Every snapshot is kept (data/snapshots), with what came of it, for the live camera page.
            photo = snapshots.save(region_crop, grams=d.grams)
            log.info("Snapshot of the new item: %s", photo)
            if identify_items_enabled():
                info = identify_item(region_crop, after_frame, d.grams)
            else:
                # Testing without AI: the snapshot shows what Gemini would get, and the
                # person names the item in the phone app instead.
                info = {"item_name": "Unknown Item", "category": None, "visible_expiration_date": None,
                        "days_until_expired": None, "confidence": 0.0, "needs_confirmation": True, "skipped": True}
            snapshots.record(photo, info)
            view.gemini_result(info)
            if info.get("needs_confirmation"):
                inv_events.apply_needs_review(db, shelf=shelf, meta={"candidate": info, "grams": d.grams, "position": d.position})
            else:
                expires, estimated = resolve_expiration(
                    printed_date=info.get("visible_expiration_date"),
                    estimated_days=info.get("days_until_expired"),
                    name=info["item_name"], category=info.get("category"),
                )
                product_id = db.get_or_create_product(info["item_name"], category=info.get("category"))
                inv_events.apply_add(
                    db, product_id, d.grams, shelf=shelf, position=d.position,
                    expiration_date=expires, expiration_estimated=estimated, confidence=info.get("confidence"),
                )
        elif d.kind == "restock_hidden":
            inv_events.apply_needs_review(db, shelf=shelf, meta={"reason": d.note, "grams": d.grams})
        elif d.kind == "needs_review":
            inv_events.apply_needs_review(db, shelf=shelf, meta={**d.meta, "note": d.note})
        # "noop" needs nothing


LOOP_INTERVAL_S = 0.1  # ~10 fps; a remote Pi camera is fetched over HTTP each tick


def _measure_trip(db, cam, scale, reference_frame, reference_weights, after_frame=None):
    """Weigh + photograph, reconcile every shelf against the reference, and
    return the new reference for the next trip."""
    new_weights = scale.weigh_all()
    if after_frame is None:
        after_frame = cam.read_frame()
    for shelf, before_w in reference_weights.items():
        _handle_trip(
            db, shelf, scale.num_shelves, reference_frame, after_frame, before_w, new_weights.get(shelf, before_w)
        )
    return after_frame, new_weights


def _weights_text(scale) -> str:
    return "  ".join(f"shelf {s}: {g:.0f} g" for s, g in sorted(scale.snapshot().items()))


QUIET_FRAMES = 5  # recent hand-free frames, median-combined into the "before"/"after" photos
# When the door switch reports closed, the door has already been swinging shut (darkening the view,
# its edge crossing the picture) for about a second. The door-close check uses the steady view from
# before that, and never a frame much darker than the scene it's compared with.
CLOSE_GUARD_S = 1.5
# The camera's auto-exposure and white balance keep shifting for a few seconds after the door opens
# and the light changes, so the before photo waits this long: taken sooner, the whole picture reads
# as changed next to the after photo, and the new food is lost among the differences.
LIGHT_SETTLE_S = float(os.getenv("LIGHT_SETTLE_S", "6"))
DARKER_THAN_REFERENCE = 0.7


def _open_view(history, reference_frame, now: float):
    """The steady view of the open fridge for the door-close check, from `history` (time, frame)
    pairs of hand-free frames: the last few from before the door began to close. None if there
    are none, so the check is skipped rather than run against a half-dark picture."""
    import numpy as np

    from vision.change import steady_frame

    floor = DARKER_THAN_REFERENCE * float(np.mean(reference_frame))
    usable = [f for t, f in history if t <= now - CLOSE_GUARD_S and float(np.mean(f)) >= floor]
    return steady_frame(usable[-QUIET_FRAMES:]) if usable else None


def run_fridge_loop(stop_event: threading.Event) -> None:
    from collections import deque

    from inventory.database import get_db
    from sensors.scale import get_scale_reader
    from vision.camera import make_camera
    from vision.change import steady_frame
    from vision.debug import view
    from vision.hands import TripDetector
    from vision.people import make_detector

    db = get_db(os.getenv("DATABASE_PATH", "refridge.db"))
    scale = get_scale_reader()  # same instance the /api/pi/* endpoints feed
    # HAND_DETECTOR=motion for the simulator's drawn hand, which MediaPipe rightly doesn't see as a hand.
    people = make_detector() if os.getenv("HAND_DETECTOR", "mediapipe").lower() == "mediapipe" else None
    trip_detector = TripDetector(people)

    with make_camera() as cam:
        reference_frame = reference_weights = None
        quiet: deque = deque(maxlen=QUIET_FRAMES)  # hand-free frames since the last time someone was in view
        history: deque = deque(maxlen=60)  # (time, frame) for the same frames, ~6 s, for the door-close check
        door_was_open = False
        door_opened_at = 0.0
        log.info("Fridge loop started (scale: %s, camera: %s, hands: %s)",
                 scale.source, type(cam).__name__, trip_detector.method)

        while not stop_event.is_set():
            try:
                door_open = scale.door_is_open()
                frame = cam.read_frame()

                if door_open and not door_was_open:
                    trip_detector.on_door_open()
                    quiet.clear()
                    history.clear()
                    reference_frame = None  # taken once the camera has adjusted and the scene is steady (below)
                    reference_weights = scale.snapshot()
                    door_opened_at = time.monotonic()
                    status = "Door opened - learning the scene"

                elif door_open:
                    signal = trip_detector.process_frame(frame)
                    if signal["hand_present"] or trip_detector.motion_boxes:
                        quiet.clear()
                        history.clear()
                    else:
                        quiet.append(frame)
                        history.append((time.monotonic(), frame))
                    adjusting = time.monotonic() - door_opened_at < LIGHT_SETTLE_S
                    if reference_frame is None and not adjusting and len(quiet) == QUIET_FRAMES:
                        reference_frame = steady_frame(list(quiet))
                    status = ("Hand in view - waiting for it to leave" if signal["hand_present"]
                              else "Adjusting to the light" if reference_frame is None and adjusting
                              else "Ready - put something in or take something out")
                    if signal["hand_left"]:
                        # The one photo for this trip: the steady view once the hand is gone.
                        after = steady_frame(list(quiet)) if quiet else frame
                        view.frame(after, door_open=True, hand_boxes=[],
                                   status="Hand left - weighing and comparing photos...")
                        reference_frame, reference_weights = _measure_trip(
                            db, cam, scale, reference_frame if reference_frame is not None else after,
                            reference_weights, after_frame=after,
                        )
                        status = "Done - ready for the next one"

                elif door_was_open and reference_frame is not None:
                    # Door just closed: final weight check. The camera is inside a now-dark
                    # fridge, so compare against the last steady view from before it began closing.
                    after = _open_view(history, reference_frame, time.monotonic())
                    if after is not None:
                        _measure_trip(db, cam, scale, reference_frame, reference_weights, after_frame=after)
                    else:
                        log.info("Door closed with no clear view since the last check; weight change left for review")
                        _measure_trip(db, cam, scale, reference_frame, reference_weights, after_frame=reference_frame)
                    reference_frame = reference_weights = None
                    quiet.clear()
                    history.clear()
                    status = "Door closed - final check done"
                else:
                    status = "Door closed"

                view.frame(frame, door_open=door_open, hand_boxes=trip_detector.motion_boxes if door_open else [],
                           people=trip_detector.last_people if door_open else None,
                           status=f"{status}   |   {_weights_text(scale)}")
                door_was_open = door_open
            except Exception:
                # A dropped Wi-Fi packet to the Pi shouldn't kill the loop.
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


def main() -> None:
    import sys

    import uvicorn

    from api.server import app

    port = int(os.getenv("API_PORT", "8000"))
    stop_event = threading.Event()
    if os.getenv("ENABLE_FRIDGE_LOOP", "false").lower() == "true":
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
