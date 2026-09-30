from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture()
def client(tmp_path: Path):
    application = create_app(database_path=tmp_path / "test_sessions.db")
    with TestClient(application) as test_client:
        yield test_client

