"""Round 5: one household clock. At 7:30 PM in New York it's already tomorrow in UTC, and every
screen must still agree on how many days are left."""
import ast
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from intelligence import clock
from intelligence.fridge_view import chat_inventory
from inventory import database as database_module
from inventory.database import Database

FROZEN = datetime(2026, 11, 8, 0, 30, tzinfo=timezone.utc)  # Saturday Nov 7, 7:30 PM in New York


@pytest.fixture
def evening(monkeypatch, tmp_path):
    monkeypatch.setenv("REFRIDGE_TZ", "America/New_York")
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "import.db"))
    monkeypatch.setattr(clock, "utc_now", lambda: FROZEN)
    monkeypatch.setattr(database_module, "now_iso", lambda: FROZEN.isoformat())
    server = pytest.importorskip("api.server")
    db = Database(tmp_path / "api.db")
    monkeypatch.setattr(server, "db", db)
    client = TestClient(server.app)
    item = client.post("/api/items", json={"name": "Baby Spinach", "grams": 300, "location": "fridge",
                                           "expiration_date": "2026-11-09"}).json()
    client.post("/api/items/consume", json={"item_id": item["item_id"], "grams": 50})
    return client, db, item["product_id"]


def test_local_today_is_the_household_day(evening):
    assert clock.local_today().isoformat() == "2026-11-07"


def test_every_view_agrees_on_days_and_waste(evening):
    client, db, product_id = evening
    summary = client.get("/api/summary").json()
    row = next(e for e in summary["inventory"] if e["product_id"] == product_id)
    detail = client.get(f"/api/products/{product_id}/usage").json()
    found = next(r for r in client.get("/api/search", params={"q": "spinach"}).json() if r["product_id"] == product_id)
    alert = next(a for a in summary["alerts"] if a["product_id"] == product_id)

    assert row["expires_in_days"] == detail["expires_in_days"] == found["expires_in_days"] == 2
    assert row["soonest_batch"]["expires_in_days"] == detail["items"][0]["expires_in_days"] == 2
    assert alert["days"] == 2
    assert row["likely_wasted_g"] == pytest.approx(150)
    assert row["likely_wasted_g"] == detail["likely_wasted_g"] == found["likely_wasted_g"]
    assert chat_inventory(db)["items"][0]["goes_bad"] == "goes bad Monday"


def test_today_meals_use_the_local_day(evening):
    client, _, _ = evening
    client.post("/api/meals", json={"name": "Yogurt", "calories": 150, "protein_g": 15,
                                    "occurred_at": "2026-11-07T15:00:00+00:00"})  # 10 AM local today
    client.post("/api/meals", json={"name": "Toast", "calories": 90,
                                    "occurred_at": "2026-11-07T03:00:00+00:00"})  # 10 PM local yesterday
    names = [m["name"] for m in client.get("/api/meals", params={"period": "today"}).json()]
    assert names == ["Yogurt"]


def test_no_utc_day_math_outside_the_clock():
    """No date.today() or UTC .date() day counts in intelligence/ outside clock.py."""
    root = Path(__file__).resolve().parent.parent / "intelligence"
    for path in root.glob("*.py"):
        if path.name == "clock.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (node.func.attr == "today" and getattr(node.func.value, "id", "") == "date"), path.name
                assert not (node.func.attr == "date" and not node.args), f"{path.name}: .date() on a timestamp"
