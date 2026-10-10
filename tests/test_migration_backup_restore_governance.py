from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from backend.app import db
from backend.app.db import SCHEMA_VERSION, connect, initialize_database
from backend.app.governance import database_content_sha256
from tests.conftest import csrf
from tests.test_write_workflow import create_user, login


def _database_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_backup(client) -> dict:
    response = client.post(
        "/api/admin/governance/backups",
        headers=csrf(client),
        json={"confirmation": "建立去內容備份"},
    )
    assert response.status_code == 200, response.text
    return response.json()["backup"]


def _login_admin(client) -> None:
    response = client.post(
        "/api/login",
        json={"username": "portfolio-admin", "password": "local-pass-1234"},
    )
    assert response.status_code == 200, response.text


def test_migration_ledger_is_applied_idempotent_and_visible(settings, authenticated):
    overview = authenticated.get("/api/admin/governance/migrations")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["current_schema"] == SCHEMA_VERSION
    assert body["pending_count"] == 0
    assert body["checksum_drift"] is False
    assert [item["migration_id"] for item in body["items"]] == [
        "001-p2c-core",
        "002-p2d1-retention",
        "003-p2d2-profile-versions",
        "004-p2d3-backup-restore",
    ]
    assert all(item["status"] == "applied" and item["checksum_matches"] for item in body["items"])

    with connect(settings) as conn:
        before = [tuple(row) for row in conn.execute("SELECT * FROM schema_migrations ORDER BY migration_id")]
    initialize_database(settings)
    with connect(settings) as conn:
        after = [tuple(row) for row in conn.execute("SELECT * FROM schema_migrations ORDER BY migration_id")]
    assert before == after


@pytest.mark.parametrize("legacy_schema", ["p2c-1", "p2d1-1", "p2d2-1"])
def test_old_schema_marker_upgrades_to_latest_without_duplicate_seed(settings, legacy_schema):
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.execute("CREATE TABLE app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.executemany(
            "INSERT INTO app_meta(key, value) VALUES (?, ?)",
            (
                ("schema_version", legacy_schema),
                ("environment_kind", settings.environment_kind),
                ("environment_id", settings.environment_id),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    initialize_database(settings)
    initialize_database(settings)
    with connect(settings) as upgraded:
        assert upgraded.execute("SELECT value FROM app_meta WHERE key='schema_version'").fetchone()["value"] == SCHEMA_VERSION
        assert upgraded.execute("SELECT COUNT(*) AS n FROM schema_migrations WHERE status='applied'").fetchone()["n"] == 4
        assert upgraded.execute("SELECT COUNT(*) AS n FROM profiles").fetchone()["n"] == 2
        assert upgraded.execute("SELECT COUNT(*) AS n FROM profile_config_versions").fetchone()["n"] == 2
        columns = {row["name"] for row in upgraded.execute("PRAGMA table_info(proposals)")}
        assert {"retention_days", "content_expires_at", "content_state", "purged_at"}.issubset(columns)


def test_checksum_drift_and_failed_migration_are_recorded(settings):
    initialize_database(settings)
    with connect(settings) as conn:
        conn.execute(
            "UPDATE schema_migrations SET checksum_sha256=? WHERE migration_id='003-p2d2-profile-versions'",
            ("0" * 64,),
        )
    with pytest.raises(RuntimeError, match="Migration checksum drift"):
        initialize_database(settings)

    with connect(settings) as conn:
        expected = next(item for item in db.MIGRATIONS if item.migration_id == "003-p2d2-profile-versions")
        conn.execute(
            "UPDATE schema_migrations SET checksum_sha256=? WHERE migration_id=?",
            (expected.checksum_sha256, expected.migration_id),
        )

    def fail(_: sqlite3.Connection) -> None:
        raise RuntimeError("fixture migration failed")

    failing = db.Migration("999-test-failure", "p2d3-1", "p2d3-test", "測試失敗不得保存內容。", "fixture-v1", fail)
    original = db.MIGRATIONS
    db.MIGRATIONS = (*original, failing)
    try:
        with pytest.raises(RuntimeError, match="fixture migration failed"):
            initialize_database(settings)
    finally:
        db.MIGRATIONS = original
    with connect(settings) as conn:
        row = conn.execute("SELECT status, error_code FROM schema_migrations WHERE migration_id=?", (failing.migration_id,)).fetchone()
    assert dict(row) == {"status": "failed", "error_code": "MIGRATION_FAILED"}


def test_backup_is_content_free_verified_and_admin_only(settings, authenticated):
    create_user(authenticated, "backup-viewer", ["viewer"])
    login(authenticated, "backup-viewer")
    forbidden = authenticated.get("/api/admin/governance/backup-preview")
    assert forbidden.status_code == 403

    _login_admin(authenticated)
    preview = authenticated.get("/api/admin/governance/backup-preview")
    assert preview.status_code == 200, preview.text
    assert preview.json()["confirmation_phrase"] == "建立去內容備份"
    wrong_confirmation = authenticated.post(
        "/api/admin/governance/backups",
        headers=csrf(authenticated),
        json={"confirmation": "確定"},
    )
    assert wrong_confirmation.status_code == 409

    backup = _create_backup(authenticated)
    assert backup["authority_included"] is False
    path = settings.db_path.parent / "backups" / f"{backup['backup_id'].lower()}.json"
    assert path.is_file()
    assert _database_sha256(path) == backup["sha256"]
    envelope = json.loads(path.read_text(encoding="utf-8"))
    serialized = path.read_text(encoding="utf-8")
    assert "portfolio-admin" not in serialized
    assert "local-pass-1234" not in serialized
    assert envelope["manifest"]["authority_included"] is False
    assert set(envelope["payload"]) == {
        "schema",
        "seed_manifest",
        "identity_summary",
        "profile_versions",
        "business_records",
    }
    forbidden_keys = {
        "username",
        "password_hash",
        "password_salt",
        "session_hash",
        "csrf_hash",
        "token_hash",
        "parameters_json",
        "summary_json",
        "reason",
        "issue_summary",
        "idempotency_key",
        "payload_json",
    }

    def collect_keys(value):
        if isinstance(value, dict):
            yield from value.keys()
            for child in value.values():
                yield from collect_keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from collect_keys(child)

    assert not forbidden_keys.intersection(collect_keys(envelope["payload"]))


def test_restore_is_new_readonly_isolation_with_zero_authority(settings, authenticated):
    backup = _create_backup(authenticated)
    source_before = database_content_sha256(settings)
    response = authenticated.post(
        "/api/admin/governance/restores",
        headers=csrf(authenticated),
        json={"backup_id": backup["backup_id"], "confirmation": "建立唯讀隔離還原"},
    )
    assert response.status_code == 200, response.text
    receipt = response.json()["receipt"]
    assert receipt["source_db_unchanged"] is True
    assert database_content_sha256(settings) == source_before
    assert receipt["source_content_sha256"] == source_before
    assert receipt["read_only"] is True
    assert receipt["sessions"] == 0
    assert receipt["auth_contexts"] == 0
    assert receipt["active_approvals"] == 0
    assert receipt["auto_replay"] == 0
    assert receipt["mcp_calls"] == 0
    target = settings.db_path.parent / receipt["target_relative_path"]
    assert target.is_file()
    restored = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in restored.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"restore_meta", "restored_profile_candidates", "restored_business_records"}
        meta = dict(restored.execute("SELECT key, value FROM restore_meta"))
        assert meta["read_only"] == "true"
        assert meta["active_approvals"] == "0"
        assert meta["sessions"] == "0"
        assert meta["auth_contexts"] == "0"
        assert meta["auto_replay"] == "0"
        assert all(
            row[0] == "restored_readonly"
            for row in restored.execute("SELECT DISTINCT restore_state FROM restored_business_records")
        )
    finally:
        restored.close()
    listed = authenticated.get("/api/admin/governance/restores")
    assert listed.status_code == 200
    assert any(item["restore_id"] == receipt["restore_id"] for item in listed.json()["items"])
    receipt_path = target.parent / "restore-receipt.json"
    envelope = json.loads(receipt_path.read_text(encoding="utf-8"))
    envelope["receipt"]["sessions"] = 1
    receipt_path.write_text(json.dumps(envelope), encoding="utf-8")
    relisted = authenticated.get("/api/admin/governance/restores")
    assert relisted.status_code == 200
    assert all(item["restore_id"] != receipt["restore_id"] for item in relisted.json()["items"])


def test_restore_receipts_are_partitioned_by_source_environment(settings, authenticated, tmp_path):
    backup = _create_backup(authenticated)
    response = authenticated.post(
        "/api/admin/governance/restores",
        headers=csrf(authenticated),
        json={"backup_id": backup["backup_id"], "confirmation": "建立唯讀隔離還原"},
    )
    assert response.status_code == 200, response.text

    other = settings.automated_test(tmp_path / "other-environment" / "app.db")
    initialize_database(other)
    from backend.app.governance import list_restores
    from backend.app.services import Actor

    admin = Actor("fixture-admin", "fixture-admin", ("admin",), (), (), 1)
    assert list_restores(other, admin) == []


def test_tampered_backup_and_caller_selected_restore_path_are_rejected(settings, authenticated):
    backup = _create_backup(authenticated)
    path = settings.db_path.parent / "backups" / f"{backup['backup_id'].lower()}.json"
    path.write_text(path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    tampered = authenticated.post(
        "/api/admin/governance/restores",
        headers=csrf(authenticated),
        json={"backup_id": backup["backup_id"], "confirmation": "建立唯讀隔離還原"},
    )
    assert tampered.status_code == 409
    assert tampered.json()["error"]["code"] == "BACKUP_HASH_MISMATCH"

    arbitrary_path = authenticated.post(
        "/api/admin/governance/restores",
        headers=csrf(authenticated),
        json={
            "backup_id": backup["backup_id"],
            "confirmation": "建立唯讀隔離還原",
            "target_path": "C:/untrusted/app.db",
        },
    )
    assert arbitrary_path.status_code == 422
