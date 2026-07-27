from pathlib import Path

import pytest

from scripts import provision_manager_db_role as provisioning


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "provision_manager_db_role.ps1"


def test_manager_role_defaults_are_fixed_and_safe():
    assert provisioning.DEFAULT_ROLE == "bar_manager_read"
    assert provisioning.DEFAULT_DATABASE == "bar_arbolada"
    assert provisioning.OPTIONAL_TABLES == {"import_run_snapshots"}


@pytest.mark.parametrize(
    "value",
    [
        "BarManager",
        "bar-manager",
        "bar manager",
        "bar_manager;DROP ROLE postgres",
        "",
    ],
)
def test_identifier_validation_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        provisioning.validate_identifier(value, label="role")


def test_result_serialization_never_contains_credentials():
    result = provisioning.ProvisioningResult(
        role="bar_manager_read",
        database="bar_arbolada",
        role_created=True,
        granted_tables=("pos_daily_sales",),
        skipped_optional_tables=("import_run_snapshots",),
        login_verified=True,
    )

    payload = result.as_dict()

    assert payload["role"] == "bar_manager_read"
    assert payload["login_verified"] is True
    assert "password" not in payload
    assert "url" not in payload


def test_provisioning_source_never_names_sensitive_allowed_columns():
    granted_columns = {
        column
        for columns in provisioning.MANAGER_READ_PRIVILEGES.values()
        for column in columns
    }

    assert {
        "first_name",
        "last_name",
        "filename",
        "file_hash",
        "error_message",
        "staging_root",
        "run_staging_dir",
    }.isdisjoint(granted_columns)
    assert "owner_distributions" not in provisioning.MANAGER_READ_PRIVILEGES


def test_manager_environment_uses_only_dedicated_credentials():
    contents = provisioning.render_manager_environment(
        "postgresql://postgres:administrator-secret@localhost:5432/bar_arbolada",
        role="bar_manager_read",
        database="bar_arbolada",
        password="manager-password-that-is-longer-than-32-characters",
        api_token="manager-api-token-that-is-longer-than-32-characters",
        api_hostname="api.example.com",
    )

    assert "postgres:administrator-secret" not in contents
    assert "bar_manager_read:" in contents
    assert "api.example.com" in contents
    assert "MANAGER_API_ALLOWED_ORIGINS=\n" in contents


def test_environment_output_must_stay_under_local_appdata(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    allowed = tmp_path / "BarArbolada" / "manager-api.env"
    outside = tmp_path / "manager-api.env"

    assert provisioning._environment_output_path(str(allowed)) == allowed.resolve()
    with pytest.raises(RuntimeError):
        provisioning._environment_output_path(str(outside))


def test_wrapper_defaults_to_a_password_only_administrator_prompt():
    source = WRAPPER.read_text(encoding="utf-8")

    assert '[string]$AdministratorInput = "Password"' in source
    assert '[string]$AdministratorHost = "localhost"' in source
    assert '[string]$AdministratorUser = "postgres"' in source
    assert "[Uri]::EscapeDataString($administratorPassword)" in source
    assert "Password for PostgreSQL administrator" in source
    assert "$env:MANAGER_DB_ADMIN_URL = $adminUrl" in source
    assert "Write-Output $adminUrl" not in source
