"""HTTP server on the Pi node. The backend pulls camera frames from here
(GET /frame.jpg). With simulated hardware it also serves a control page at /
for driving the fake fridge: open the door, put items in, take some out."""
from __future__ import annotations

import json

import cv2
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from pi_node.hardware import Hardware, SimHardware
from pi_node.sim_page import SIM_PAGE

JPEG_QUALITY = 80


class DoorIn(BaseModel):
    open: bool


class PlaceIn(BaseModel):
    name: str
    grams: float
    shelf: int = 0


class UseIn(BaseModel):
    grams: float


class TempIn(BaseModel):
    temperature_c: float | None  # null clears the override


def create_app(hw: Hardware, backend_url: str = "") -> FastAPI:
    app = FastAPI(title="ShelfLife Pi node")
    # json.dumps gives a safely quoted JS string for the page's backend address.
    page = SIM_PAGE.replace('"__BACKEND__"', json.dumps(backend_url.rstrip("/")))

    @app.get("/frame.jpg")
    def frame():
        img = hw.frame()
        if img is None:
            raise HTTPException(503, "no camera frame available")
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not ok:
            raise HTTPException(500, "JPEG encode failed")
        return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/health")
    def health():
        return {"ok": True, "hardware": type(hw).__name__, "shelves": hw.num_shelves, "camera": hw.frame() is not None}

    if isinstance(hw, SimHardware):
        sim = hw

        @app.get("/", response_class=HTMLResponse)
        def control_page():
            return page

        @app.get("/sim/state")
        def sim_state():
            return sim.state()

        @app.post("/sim/door")
        def sim_door(body: DoorIn):
            sim.set_door(body.open)
            return sim.state()

        @app.post("/sim/place")
        def sim_place(body: PlaceIn):
            try:
                sim.place(body.name, body.grams, body.shelf)
            except ValueError as e:
                raise HTTPException(400, str(e))
            return sim.state()

        @app.post("/sim/items/{item_id}/remove")
        def sim_remove(item_id: int):
            try:
                sim.remove(item_id)
            except KeyError as e:
                raise HTTPException(404, str(e))
            return sim.state()

        @app.post("/sim/items/{item_id}/use")
        def sim_use(item_id: int, body: UseIn):
            try:
                sim.use(item_id, body.grams)
            except KeyError as e:
                raise HTTPException(404, str(e))
            return sim.state()

        @app.post("/sim/temperature")
        def sim_temperature(body: TempIn):
            sim.temp_override_c = body.temperature_c
            return sim.state()

    return app
