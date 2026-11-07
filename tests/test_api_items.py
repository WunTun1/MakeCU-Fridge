import pytest
from fastapi.testclient import TestClient

from inventory.database import Database


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SCALE_SOURCE", "mock")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "import.db"))  # never touch the real refridge.db
    server = pytest.importorskip("api.server")
    monkeypatch.setattr(server, "db", Database(tmp_path / "api.db"))
    return TestClient(server.app)


def _inventory(client):
    return {e["name"]: e for e in client.get("/api/summary").json()["inventory"]}


def test_add_by_count_stores_grams_and_reports_the_unit(client):
    res = client.post("/api/items", json={"name": "Eggs", "quantity": 12, "unit": "count", "location": "fridge"}).json()
    assert res["grams"] == 600 and res["unit"] == "count"
    eggs = _inventory(client)["Eggs"]
    assert (eggs["grams"], eggs["unit"], eggs["grams_per_unit"]) == (600, "count", 50)


def test_add_in_grams_still_works_and_needs_an_amount(client):
    assert client.post("/api/items", json={"name": "Rice", "grams": 500}).status_code == 200
    assert client.post("/api/items", json={"name": "Rice"}).status_code == 422


def test_undo_add_then_waste_and_undo(client):
    item = client.post("/api/items", json={"name": "Yogurt", "grams": 500, "location": "fridge"}).json()
    client.post(f"/api/items/{item['item_id']}/undo-add")
    assert "Yogurt" not in _inventory(client)

    item = client.post("/api/items", json={"name": "Yogurt", "grams": 500, "location": "fridge"}).json()
    events = client.post("/api/items/waste", json={"item_ids": [item["item_id"]]}).json()["event_ids"]
    assert "Yogurt" not in _inventory(client)
    client.post("/api/events/undo", json={"event_ids": events})
    assert _inventory(client)["Yogurt"]["grams"] == 500


def test_patch_item_sets_amount_and_printed_date(client):
    item = client.post("/api/items", json={"name": "Milk", "quantity": 1000, "unit": "ml", "location": "fridge"}).json()
    assert client.patch(f"/api/items/{item['item_id']}", json={"grams": 250, "expiration_date": "2030-01-02"}).status_code == 200
    usage = client.get(f"/api/products/{item['product_id']}/usage").json()
    assert usage["on_hand_g"] == 250
    assert (usage["expiration_date"], usage["expiry_estimated"]) == ("2030-01-02", False)


def test_grocery_endpoints_round_trip(client):
    ids = client.post("/api/grocery/items", json={"names": ["Lemon"]}).json()["ids"]
    client.patch(f"/api/grocery/items/{ids[0]}", json={"checked": True})
    listing = client.put("/api/grocery/horizon", json={"trip_in_days": 7}).json()
    assert listing["trip_in_days"] == 7
    assert [(i["name"], i["checked"]) for i in listing["items"]] == [("Lemon", True)]
    assert client.get("/api/grocery").json()["trip_in_days"] == 7
    client.post("/api/grocery/clear-checked")
    assert client.get("/api/grocery").json()["items"] == []


def test_adding_an_item_checks_it_off_the_list(client):
    [entry] = client.post("/api/grocery/items", json={"names": ["eggs"]}).json()["ids"]
    res = client.post("/api/items", json={"name": "Eggs", "quantity": 12, "unit": "count", "location": "fridge"}).json()
    assert res["checked_off"] == {"id": entry, "name": "eggs"}
    client.patch(f"/api/grocery/items/{entry}", json={"checked": False})
    assert client.get("/api/grocery").json()["items"][0]["checked"] is False


def test_remove_grocery_row_and_undo(client):
    [entry] = client.post("/api/grocery/items", json={"names": ["apples 6"]}).json()["ids"]
    client.patch(f"/api/grocery/items/{entry}", json={"hidden": True})
    assert client.get("/api/grocery").json()["items"] == []
    client.patch(f"/api/grocery/items/{entry}", json={"hidden": False})
    assert [(i["name"], i["amount"]) for i in client.get("/api/grocery").json()["items"]] == [("apples", "6")]


def test_summary_shows_the_soonest_package_and_the_saved_trip(client):
    client.post("/api/items", json={"name": "Milk", "quantity": 1000, "unit": "ml", "location": "fridge",
                                    "expiration_date": "2030-01-02"})
    client.post("/api/items", json={"name": "Milk", "quantity": 2000, "unit": "ml", "location": "fridge",
                                    "expiration_date": "2030-01-20"})
    milk = _inventory(client)["Milk"]
    assert milk["grams"] == 3000
    assert milk["soonest_batch"] == {"grams": 1000, "expiration_date": "2030-01-02"}
    grocery = client.put("/api/grocery/horizon", json={"trip_in_days": 7}).json()
    summary = client.get("/api/summary").json()
    assert (summary["next_trip_date"], summary["covers_until"]) == (grocery["trip_date"], grocery["covers_until"])


def test_cook_preview_takes_made_as_half_or_full(client):
    assert client.get("/api/recipes/1/cooked/preview?made=0.75").status_code == 422
