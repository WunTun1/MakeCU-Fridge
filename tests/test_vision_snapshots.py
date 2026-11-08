import numpy as np
import pytest
from fastapi.testclient import TestClient

from vision import snapshots


@pytest.fixture
def shots(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    return snapshots


def test_a_snapshot_is_pending_until_gemini_answers(shots):
    photo = shots.save(np.zeros((20, 20, 3), np.uint8), grams=250)
    assert shots.recent()[0]["status"] == "pending" and shots.recent()[0]["grams"] == 250
    shots.record(photo, {"item_name": "Milk", "confidence": 0.92, "needs_confirmation": False})
    latest = shots.recent()[0]
    assert (latest["status"], latest["item_name"], latest["confidence"]) == ("named", "Milk", 0.92)


def test_two_snapshots_in_one_second_both_kept_newest_first(shots):
    a = shots.save(np.zeros((4, 4, 3), np.uint8))
    b = shots.save(np.zeros((4, 4, 3), np.uint8))
    assert a != b and [s["name"] for s in shots.recent()][:2] == [b.name, a.name]


def test_only_our_photos_can_be_fetched(shots):
    photo = shots.save(np.zeros((4, 4, 3), np.uint8))
    assert shots.path_for(photo.name) == photo
    assert shots.path_for("../.env") is None and shots.path_for("x.jpg") is None


def test_the_camera_page_and_its_endpoints(shots, monkeypatch, tmp_path):
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    server = pytest.importorskip("api.server")
    client = TestClient(server.app)
    assert "ShelfLife camera" in client.get("/vision").text
    photo = shots.save(np.zeros((8, 8, 3), np.uint8), grams=100)
    assert client.get("/api/vision/snapshots").json()[0]["name"] == photo.name
    assert client.get(f"/api/vision/snapshots/{photo.name}").headers["content-type"] == "image/jpeg"
    assert client.get("/api/vision/snapshots/..%2F.env").status_code == 404


def test_clear_empties_the_photo_list(shots, monkeypatch, tmp_path):
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    server = pytest.importorskip("api.server")
    client = TestClient(server.app)
    shots.save(np.zeros((4, 4, 3), np.uint8))
    shots.save(np.zeros((4, 4, 3), np.uint8))
    assert client.delete("/api/vision/snapshots").json() == {"removed": 2}
    assert client.get("/api/vision/snapshots").json() == []
    assert list(shots.SNAPSHOT_DIR.iterdir()) == []  # the .json files went too


def test_scale_endpoint_reports_weights_and_door(monkeypatch, tmp_path):
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "api.db"))
    server = pytest.importorskip("api.server")
    body = TestClient(server.app).get("/api/scale").json()
    assert set(body) == {"weights", "door_open"} and isinstance(body["door_open"], bool)
