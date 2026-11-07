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


def shelf_band(shelf: int, num_shelves: int) -> tuple[float, float]:
    """Vertical slice of the camera frame (normalized y0, y1) that a shelf
    occupies. Equal bands by default; override with SHELF_BANDS="0-0.45,0.45-1"
    once the real camera is mounted and you can see where each shelf lands."""
    spec = os.getenv("SHELF_BANDS", "").strip()
    if spec:
        y0, y1 = spec.split(",")[shelf].split("-")
        return float(y0), float(y1)
    return shelf / num_shelves, (shelf + 1) / num_shelves


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
    from inventory import events as inv_events
    from vision import tracking
    from vision.camera import crop
    from vision.change import detect_changes
    from vision.classifier import identify_item

    band = shelf_band(shelf, num_shelves)
    frame_h = after_frame.shape[0]
    regions = [r for r in detect_changes(before_frame, after_frame) if _in_band(r.bbox, frame_h, band)]
    known = _known_items_for_shelf(db, shelf, before_frame)
    result = tracking.match(known, regions, before_frame, after_frame)

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
            region_crop = crop(after_frame, d.region.bbox) if d.region and d.region.bbox else after_frame
            info = identify_item(region_crop, after_frame, d.grams)
            if info.get("needs_confirmation"):
                inv_events.apply_needs_review(db, shelf=shelf, meta={"candidate": info, "grams": d.grams, "position": d.position})
            else:
                product_id = db.get_or_create_product(info["item_name"], category=info.get("category"))
                inv_events.apply_add(
                    db, product_id, d.grams, shelf=shelf, position=d.position,
                    expiration_date=info.get("visible_expiration_date"), confidence=info.get("confidence"),
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


def run_fridge_loop(stop_event: threading.Event) -> None:
    from inventory.database import get_db
    from sensors.scale import get_scale_reader
    from vision.camera import make_camera
    from vision.hands import TripDetector

    db = get_db(os.getenv("DATABASE_PATH", "refridge.db"))
    scale = get_scale_reader()  # same instance the /api/pi/* endpoints feed
    trip_detector = TripDetector()

    with make_camera() as cam:
        reference_frame = reference_weights = last_quiet_frame = None
        door_was_open = False
        log.info("Fridge loop started (scale source: %s, camera: %s)", scale.source, type(cam).__name__)

        while not stop_event.is_set():
            try:
                door_open = scale.door_is_open()

                if door_open and not door_was_open:
                    trip_detector.on_door_open()
                    reference_frame = last_quiet_frame = cam.read_frame()
                    reference_weights = scale.snapshot()

                elif door_open:
                    frame = cam.read_frame()
                    signal = trip_detector.process_frame(frame)
                    if not signal["hand_present"]:
                        last_quiet_frame = frame
                    if signal["hand_left"]:
                        reference_frame, reference_weights = _measure_trip(
                            db, cam, scale, reference_frame, reference_weights
                        )

                elif door_was_open and reference_frame is not None:
                    # Door just closed: final weight check. The camera is inside a now-dark
                    # fridge, so compare against the last hand-free frame from while it was open.
                    _measure_trip(db, cam, scale, reference_frame, reference_weights, after_frame=last_quiet_frame)
                    reference_frame = reference_weights = last_quiet_frame = None

                door_was_open = door_open
            except Exception:
                # A dropped Wi-Fi packet to the Pi shouldn't kill the loop.
                log.exception("Fridge loop tick failed; continuing")
            time.sleep(LOOP_INTERVAL_S)


def main() -> None:
    import uvicorn

    from api.server import app

    stop_event = threading.Event()
    if os.getenv("ENABLE_FRIDGE_LOOP", "false").lower() == "true":
        thread = threading.Thread(target=run_fridge_loop, args=(stop_event,), daemon=True)
        thread.start()
    else:
        log.info("Fridge sensor loop disabled (ENABLE_FRIDGE_LOOP=false) — serving the API only")

    # access_log off: the Pi posts weights ~10x/second, which would bury everything else.
    uvicorn.run(app, host=os.getenv("API_HOST", "0.0.0.0"), port=int(os.getenv("API_PORT", "8000")), access_log=False)
    stop_event.set()


if __name__ == "__main__":
    main()
