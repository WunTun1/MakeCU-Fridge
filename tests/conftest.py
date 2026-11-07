import pytest

from inventory.database import Database


@pytest.fixture
def db():
    return Database(":memory:")
