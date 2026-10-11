from collections.abc import Iterator
from typing import Any

import mongomock
import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app


class _FailingDatabase:
    def command(self, name: str) -> None:
        raise RuntimeError("boom")


def _in_memory_db() -> Any:
    return mongomock.MongoClient()["test"]


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_reports_up_when_ping_succeeds(client: TestClient) -> None:
    app.dependency_overrides[get_db] = _in_memory_db
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "up"}


def test_health_reports_down_when_ping_fails(client: TestClient) -> None:
    app.dependency_overrides[get_db] = _FailingDatabase
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "down"}
