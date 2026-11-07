from inventory import events as inv_events


def test_create_and_fetch_product(db):
    pid = db.create_product("Milk", category="Dairy", usual_package_size_g=1000, is_staple=True)
    product = db.get_product(pid)
    assert product["name"] == "Milk"
    assert product["is_staple"] == 1


def test_get_or_create_product_is_idempotent(db):
    pid1 = db.get_or_create_product("Milk")
    pid2 = db.get_or_create_product("milk")  # case-insensitive match
    assert pid1 == pid2


def test_apply_add_creates_item_and_event(db):
    pid = db.get_or_create_product("Milk")
    item_id = inv_events.apply_add(db, pid, grams=1000, shelf=0)
    item = db.get_item(item_id)
    assert item["grams"] == 1000
    assert item["status"] == "active"

    events = db.events_for_product(pid)
    assert len(events) == 1
    assert events[0]["event_type"] == "add"
    assert events[0]["grams_delta"] == 1000


def test_apply_consume_reduces_grams_without_removing(db):
    pid = db.get_or_create_product("Milk")
    item_id = inv_events.apply_add(db, pid, grams=1000)
    inv_events.apply_consume(db, item_id, 200)
    item = db.get_item(item_id)
    assert item["grams"] == 800
    assert item["status"] == "active"


def test_apply_consume_removes_item_when_fully_used(db):
    pid = db.get_or_create_product("Milk")
    item_id = inv_events.apply_add(db, pid, grams=100)
    inv_events.apply_consume(db, item_id, 150)  # more than available
    item = db.get_item(item_id)
    assert item["grams"] == 0
    assert item["status"] == "removed"


def test_apply_remove_then_return_reactivates_item(db):
    pid = db.get_or_create_product("Milk")
    item_id = inv_events.apply_add(db, pid, grams=1000)
    inv_events.apply_remove(db, item_id)
    assert db.get_item(item_id)["status"] == "removed"

    inv_events.apply_return(db, item_id, grams=1000)
    item = db.get_item(item_id)
    assert item["status"] == "active"
    assert item["grams"] == 1000

    events = [e["event_type"] for e in db.events_for_product(pid)]
    assert events == ["add", "remove", "return"]


def test_needs_review_starts_unresolved(db):
    event_id = inv_events.apply_needs_review(db, meta={"reason": "test"})
    pending = db.needs_review()
    assert len(pending) == 1
    assert pending[0]["id"] == event_id

    db.resolve_event(event_id)
    assert db.needs_review() == []


def test_waste_excludes_item_from_active_list(db):
    pid = db.get_or_create_product("Spinach")
    item_id = inv_events.apply_add(db, pid, grams=150)
    inv_events.apply_waste(db, item_id)
    assert db.get_item(item_id)["status"] == "removed"


def test_shared_connection_is_safe_across_threads(tmp_path):
    # The API's request threads and the fridge loop share one Database.
    import threading

    from inventory.database import Database

    db = Database(tmp_path / "t.db")
    pid = db.get_or_create_product("Milk", usual_package_size_g=1000)
    for _ in range(20):
        db.create_item(pid, grams=500)
    errors: list[BaseException] = []

    def reader():
        try:
            for _ in range(200):
                for item in db.active_items():
                    assert item["grams"] == 500
                    assert db.get_product(item["product_id"])["name"] == "Milk"
        except BaseException as e:  # noqa: BLE001 - surface any failure from the thread
            errors.append(e)

    threads = [threading.Thread(target=reader) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors[0]
