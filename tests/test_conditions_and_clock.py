from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from intelligence import conditions
from inventory.database import Database


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "import.db"))
    server = pytest.importorskip("api.server")
    monkeypatch.setattr(server, "db", Database(tmp_path / "api.db"))
    return TestClient(server.app)


def test_demo_conditions_look_like_a_cold_fridge(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_CONDITIONS", "on")
    reading = conditions.latest(Database(tmp_path / "c.db"))
    assert 3 <= reading["temperature_c"] <= 4.2
    assert 40 <= reading["humidity_pct"] <= 50 and 1010 <= reading["pressure_hpa"] <= 1016
    assert datetime.fromisoformat(reading["occurred_at"])  # fresh, so screens don't hide it as stale


def test_without_demo_the_real_reading_is_shown(monkeypatch, tmp_path):
    monkeypatch.delenv("DEMO_CONDITIONS", raising=False)
    assert conditions.latest(Database(tmp_path / "c.db")) is None  # nothing reported yet


def test_demo_numbers_never_raise_the_too_warm_alert(monkeypatch, client):
    monkeypatch.setenv("DEMO_CONDITIONS", "on")
    summary = client.get("/api/summary").json()
    assert summary["conditions"]["temperature_c"] < 7
    assert not any(a["reason"] == "fridge_temp_high" for a in summary["alerts"])


def test_summary_carries_the_households_clock(client):
    summary = client.get("/api/summary").json()
    assert datetime.fromisoformat(summary["server_time"]).tzinfo is not None
    assert isinstance(summary["utc_offset_minutes"], int) and -720 <= summary["utc_offset_minutes"] <= 840


def test_household_time_is_eastern_unless_set(monkeypatch):
    from intelligence import clock

    monkeypatch.delenv("REFRIDGE_TZ", raising=False)
    assert str(clock.local_tz()) == "America/New_York"
    monkeypatch.setenv("REFRIDGE_TZ", "Europe/London")
    assert str(clock.local_tz()) == "Europe/London"
