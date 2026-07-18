from collections.abc import Iterator

import pytest
from app.api import get_store
from app.main import app
from app.store import FoundationStore
from fastapi.testclient import TestClient


@pytest.fixture
def foundation_store() -> FoundationStore:
    return FoundationStore()


@pytest.fixture
def client(foundation_store: FoundationStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: foundation_store
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
