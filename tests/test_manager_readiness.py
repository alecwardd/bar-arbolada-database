from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import app as app_module


TOKEN = "manager-readiness-token-that-is-at-least-32-characters"
ROOT = Path(__file__).resolve().parents[1]
SERVICE_SCRIPT = ROOT / "scripts" / "install_manager_services.ps1"


@pytest.fixture(autouse=True)
def manager_environment(monkeypatch):
    monkeypatch.setenv("MANAGER_API_TOKEN", TOKEN)
    monkeypatch.setenv("MANAGER_API_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver")
    monkeypatch.delenv("MANAGER_API_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("MANAGER_API_ENABLE_DOCS", raising=False)
    monkeypatch.setenv("MANAGER_API_READINESS_TIMEOUT_SECONDS", "0.10")


def _client(monkeypatch, probe):
    monkeypatch.setattr(app_module, "_probe_database", probe)
    return TestClient(app_module.create_app())


def test_liveness_is_independent_of_database_readiness(monkeypatch):
    def should_not_run():
        raise AssertionError("liveness must not touch the database")

    with _client(monkeypatch, should_not_run) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "private, no-store"


def test_readiness_success_is_minimal_and_unauthenticated(monkeypatch):
    with _client(monkeypatch, lambda: None) as client:
        response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "probe",
    [
        lambda: (_ for _ in ()).throw(RuntimeError("private database detail")),
        lambda: time.sleep(0.30),
    ],
)
def test_readiness_failure_is_bounded_and_discloses_no_details(monkeypatch, probe):
    started = time.perf_counter()
    with _client(monkeypatch, probe) as client:
        response = client.get("/ready")
    elapsed = time.perf_counter() - started

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert "private database detail" not in response.text
    assert elapsed < 0.25


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("not-a-number", app_module.DEFAULT_READINESS_TIMEOUT_SECONDS),
        ("0", app_module.MIN_READINESS_TIMEOUT_SECONDS),
        ("999", app_module.MAX_READINESS_TIMEOUT_SECONDS),
        ("1.25", 1.25),
    ],
)
def test_readiness_timeout_configuration_is_strictly_bounded(
    monkeypatch,
    configured,
    expected,
):
    monkeypatch.setenv("MANAGER_API_READINESS_TIMEOUT_SECONDS", configured)
    assert app_module._readiness_timeout_seconds() == expected


def test_database_probe_forces_read_only_short_transaction(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.statements = []
            self.rolled_back = False
            self.closed = False

        def execute(self, statement):
            self.statements.append(str(statement))

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    session = FakeSession()
    monkeypatch.setattr(app_module, "get_session", lambda: session)

    app_module._probe_database()

    assert session.statements == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '1500ms'",
        "SELECT 1",
    ]
    assert session.rolled_back is True
    assert session.closed is True


def test_service_launcher_has_fail_closed_security_controls():
    source = SERVICE_SCRIPT.read_text(encoding="utf-8")

    assert '--host "127.0.0.1"' in source
    assert "[string]$Host" not in source
    assert "PGCONNECT_TIMEOUT" in source
    assert "default_transaction_read_only=on" in source
    assert "--no-access-log" in source
    assert "-RestartCount 999" in source
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in source
    assert "http://127\\.0\\.0\\.1:8600" in source
    assert "http_status:404" in source
    assert "$meaningfulLines[-1]" in source
    assert "-ConfigPath $details.CredentialsPath" in source
    assert "Refusing to replace or remove a same-named task" in source


def test_manager_service_environment_filename_is_gitignored():
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", "--", ".env.manager-api"],
        check=False,
    )
    assert result.returncode == 0
