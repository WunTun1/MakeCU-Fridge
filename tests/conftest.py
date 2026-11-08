import pytest

from inventory.database import Database


@pytest.fixture
def db():
    return Database(":memory:")


@pytest.fixture(autouse=True)
def _no_tiger(monkeypatch):
    """Tests never touch the real Tiger Data database, whatever .env says."""
    monkeypatch.delenv("TIGER_DATABASE_URL", raising=False)
