import inventory.database as database


def test_get_db_honors_database_path(tmp_path, monkeypatch):
    target = tmp_path / "configured.db"
    monkeypatch.setenv("DATABASE_PATH", str(target))
    monkeypatch.setattr(database, "_db", None)
    try:
        assert database.get_db().path == str(target)
    finally:
        database._db.close()
        monkeypatch.setattr(database, "_db", None)
