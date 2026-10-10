from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.config import Settings
from backend.app.db import connect
from tests.conftest import csrf


def test_first_admin_setup_and_login_flow(client):
    assert client.get("/api/setup/status").json() == {"needs_setup": True}
    created = client.post(
        "/api/setup",
        json={"username": "portfolio-admin", "password": "local-pass-1234"},
    )
    assert created.status_code == 200
    assert created.json()["actor"]["roles"] == ["admin", "viewer"]
    assert client.get("/api/setup/status").json() == {"needs_setup": False}
    assert client.get("/api/me").status_code == 200
    logged_out = client.post("/api/logout", headers=csrf(client))
    assert logged_out.status_code == 200
    assert client.get("/api/me").status_code == 401
    logged_in = client.post(
        "/api/login",
        json={"username": "portfolio-admin", "password": "local-pass-1234"},
    )
    assert logged_in.status_code == 200


def test_csrf_is_required(authenticated):
    response = authenticated.post(
        "/api/tools/get_equipment_status/invoke",
        json={"profile_id": "service-v1", "arguments": {"equipment_id": "EQ-PUMP-001"}},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REQUIRED"


def test_environment_path_escape_is_rejected(tmp_path: Path):
    with pytest.raises(RuntimeError, match="escapes"):
        Settings(
            root=Path(__file__).resolve().parents[1],
            environment_kind="local_product",
            db_path=tmp_path / "escaped.db",
        ).validated()


def test_database_environment_mismatch_is_detected(settings: Settings, authenticated):
    with connect(settings) as conn:
        conn.execute("UPDATE app_meta SET value='development' WHERE key='environment_kind'")
    with pytest.raises(RuntimeError, match="environment mismatch"):
        from backend.app.db import initialize_database

        initialize_database(settings)

