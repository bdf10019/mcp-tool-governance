from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import Settings  # noqa: E402
from backend.app.main import create_app  # noqa: E402


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings.automated_test(tmp_path / "app.db")


@pytest.fixture()
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def authenticated(client: TestClient) -> TestClient:
    response = client.post(
        "/api/setup",
        json={"username": "portfolio-admin", "password": "local-pass-1234"},
    )
    assert response.status_code == 200, response.text
    return client


def csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("mcp_csrf") or ""}

