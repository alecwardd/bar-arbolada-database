"""Provision and verify the dedicated Bar Arbolada manager read role.

Credentials are read from the process environment and are never printed:

    MANAGER_DB_ADMIN_URL
    MANAGER_DATABASE_PASSWORD

The administrator URL must connect to the target ``bar_arbolada`` database
with a PostgreSQL role that can create roles. Run this script again after a
schema migration adds an optional read-model table.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool

from src.api.read_model import MANAGER_READ_PRIVILEGES


DEFAULT_ROLE = "bar_manager_read"
DEFAULT_DATABASE = "bar_arbolada"
OPTIONAL_TABLES = frozenset({"import_run_snapshots"})
_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_HOSTNAME = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")


@dataclass(frozen=True)
class ProvisioningResult:
    role: str
    database: str
    role_created: bool
    granted_tables: tuple[str, ...]
    skipped_optional_tables: tuple[str, ...]
    login_verified: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "database": self.database,
            "role_created": self.role_created,
            "granted_tables": list(self.granted_tables),
            "skipped_optional_tables": list(self.skipped_optional_tables),
            "login_verified": self.login_verified,
        }


def validate_identifier(value: str, *, label: str) -> str:
    """Accept only simple PostgreSQL identifiers used by this fixed script."""

    if not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase PostgreSQL identifier")
    return value


def _require_secret(name: str, *, minimum_length: int = 1) -> str:
    value = os.getenv(name, "")
    if len(value) < minimum_length:
        raise RuntimeError(f"{name} is required")
    return value


def _validate_api_hostname(value: str) -> str:
    hostname = value.strip().lower()
    if not hostname:
        return ""
    if (
        len(hostname) > 253
        or "." not in hostname
        or ".." in hostname
        or not _HOSTNAME.fullmatch(hostname)
    ):
        raise ValueError("MANAGER_API_HOSTNAME must be one exact DNS hostname")
    return hostname


def _environment_output_path(raw_path: str) -> Path:
    if not raw_path:
        raise RuntimeError("MANAGER_ENV_OUTPUT_PATH is required")
    output_path = Path(raw_path)
    if not output_path.is_absolute():
        raise RuntimeError("MANAGER_ENV_OUTPUT_PATH must be absolute")

    local_appdata = os.getenv("LOCALAPPDATA", "")
    if not local_appdata:
        raise RuntimeError("LOCALAPPDATA is required")
    approved_root = (Path(local_appdata) / "BarArbolada").resolve()
    resolved_output = output_path.resolve()
    try:
        resolved_output.relative_to(approved_root)
    except ValueError as exc:
        raise RuntimeError(
            "manager environment output must stay under LocalAppData BarArbolada"
        ) from exc
    return resolved_output


def render_manager_environment(
    admin_url: str,
    *,
    role: str,
    database: str,
    password: str,
    api_token: str,
    api_hostname: str = "",
) -> str:
    """Render the local API environment without retaining administrator access."""

    if len(password) < 32:
        raise ValueError("manager database password must be at least 32 characters")
    if len(api_token) < 32 or any(character.isspace() for character in api_token):
        raise ValueError("manager API token must be at least 32 non-space characters")
    hostname = _validate_api_hostname(api_hostname)
    manager_url = make_url(admin_url).set(
        username=role,
        password=password,
        database=database,
    )
    rendered_url = manager_url.render_as_string(hide_password=False)
    if "\n" in rendered_url or "\r" in rendered_url:
        raise ValueError("manager database URL contains a newline")

    allowed_hosts = ["127.0.0.1", "localhost"]
    if hostname:
        allowed_hosts.append(hostname)
    return "\n".join(
        (
            f"MANAGER_DATABASE_URL={rendered_url}",
            f"MANAGER_API_TOKEN={api_token}",
            f"MANAGER_API_ALLOWED_HOSTS={','.join(allowed_hosts)}",
            "MANAGER_API_ALLOWED_ORIGINS=",
            "MANAGER_API_ENABLE_DOCS=",
            "MANAGER_API_READINESS_TIMEOUT_SECONDS=2",
            "",
        )
    )


def write_manager_environment(
    output_path: Path,
    contents: str,
) -> None:
    """Atomically write the ignored, ACL-restricted-at-wrapper environment file."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.name}.{os.getpid()}.tmp"
    )
    try:
        temporary_path.write_text(contents, encoding="utf-8", newline="\n")
        os.replace(temporary_path, output_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _role_memberships(connection: Connection, role: str) -> list[str]:
    return list(
        connection.scalars(
            text(
                """
                SELECT parent.rolname
                FROM pg_auth_members membership
                JOIN pg_roles member ON member.oid = membership.member
                JOIN pg_roles parent ON parent.oid = membership.roleid
                WHERE member.rolname = :role
                ORDER BY parent.rolname
                """
            ),
            {"role": role},
        )
    )


def _relation_exists(connection: Connection, table_name: str) -> bool:
    return (
        connection.scalar(
            text("SELECT to_regclass(:qualified_name) IS NOT NULL"),
            {"qualified_name": f"public.{table_name}"},
        )
        is True
    )


def _available_columns(connection: Connection, table_name: str) -> set[str]:
    return set(
        connection.scalars(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        )
    )


def _provision_grants(
    connection: Connection,
    *,
    role: str,
    database: str,
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    admin = connection.execute(
        text(
            """
            SELECT current_user, current_database(), role.rolsuper, role.rolcreaterole
            FROM pg_roles role
            WHERE role.rolname = current_user
            """
        )
    ).one()
    if admin.current_database != database:
        raise RuntimeError("MANAGER_DB_ADMIN_URL targets the wrong database")
    if not (admin.rolsuper or admin.rolcreaterole):
        raise RuntimeError("the database administrator cannot create roles")

    role_exists = bool(
        connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :role)"),
            {"role": role},
        )
    )
    if role_exists and _role_memberships(connection, role):
        raise RuntimeError("existing manager role has inherited memberships")

    password = _require_secret("MANAGER_DATABASE_PASSWORD", minimum_length=32)
    if not role_exists:
        connection.exec_driver_sql(
            f"CREATE ROLE {role} LOGIN PASSWORD %s",
            (password,),
        )
    else:
        connection.exec_driver_sql(
            f"ALTER ROLE {role} LOGIN PASSWORD %s",
            (password,),
        )

    connection.exec_driver_sql(
        f"""
        ALTER ROLE {role}
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
            NOINHERIT CONNECTION LIMIT 5
        """
    )
    connection.exec_driver_sql(
        f"ALTER ROLE {role} SET default_transaction_read_only = 'on'"
    )
    connection.exec_driver_sql(f"ALTER ROLE {role} SET statement_timeout = '10s'")
    connection.exec_driver_sql(f"ALTER ROLE {role} SET lock_timeout = '2s'")
    connection.exec_driver_sql(
        f"ALTER ROLE {role} SET idle_in_transaction_session_timeout = '15s'"
    )
    connection.exec_driver_sql(f"ALTER ROLE {role} SET search_path = 'public'")

    connection.exec_driver_sql(f"REVOKE ALL ON DATABASE {database} FROM {role}")
    connection.exec_driver_sql(f"GRANT CONNECT ON DATABASE {database} TO {role}")
    connection.exec_driver_sql(f"REVOKE CREATE ON SCHEMA public FROM {role}")
    connection.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
    connection.exec_driver_sql(
        f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {role}"
    )
    connection.exec_driver_sql(
        f"REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM {role}"
    )

    granted: list[str] = []
    skipped: list[str] = []
    for table_name, columns in sorted(MANAGER_READ_PRIVILEGES.items()):
        if not _relation_exists(connection, table_name):
            if table_name in OPTIONAL_TABLES:
                skipped.append(table_name)
                continue
            raise RuntimeError(f"required manager read table is missing: {table_name}")

        missing_columns = set(columns) - _available_columns(connection, table_name)
        if missing_columns:
            raise RuntimeError(
                f"manager read table {table_name} is missing required columns"
            )
        connection.exec_driver_sql(
            f"GRANT SELECT ({', '.join(columns)}) "
            f"ON TABLE public.{table_name} TO {role}"
        )
        granted.append(table_name)

    return not role_exists, tuple(granted), tuple(skipped)


def _verify_login(
    admin_url: str,
    *,
    role: str,
    password: str,
) -> None:
    role_url = make_url(admin_url).set(username=role, password=password)
    role_engine = create_engine(role_url, poolclass=NullPool, pool_pre_ping=True)
    try:
        with role_engine.connect() as connection:
            read_only = connection.scalar(text("SHOW transaction_read_only"))
            if read_only != "on":
                raise RuntimeError("manager login is not transaction read-only")
            connection.execute(
                text(
                    """
                    SELECT trading_day, net_sales
                    FROM public.pos_daily_sales
                    LIMIT 1
                    """
                )
            ).all()

        forbidden_queries = (
            "SELECT filename FROM public.import_logs LIMIT 0",
            "SELECT first_name FROM public.pos_labor LIMIT 0",
            "SELECT 1 FROM public.owner_distributions LIMIT 0",
        )
        for query in forbidden_queries:
            denied = False
            try:
                with role_engine.connect() as connection:
                    connection.execute(text(query)).all()
            except Exception:
                denied = True
            if not denied:
                raise RuntimeError("manager login can read a forbidden field")
    finally:
        role_engine.dispose()


def provision_manager_role(
    admin_url: str,
    *,
    role: str = DEFAULT_ROLE,
    database: str = DEFAULT_DATABASE,
) -> ProvisioningResult:
    """Create, grant, and live-verify the manager database login."""

    role = validate_identifier(role, label="role")
    database = validate_identifier(database, label="database")
    admin_engine: Engine = create_engine(
        admin_url,
        poolclass=NullPool,
        pool_pre_ping=True,
    )
    try:
        with admin_engine.begin() as connection:
            created, granted, skipped = _provision_grants(
                connection,
                role=role,
                database=database,
            )
    finally:
        admin_engine.dispose()

    password = _require_secret("MANAGER_DATABASE_PASSWORD", minimum_length=32)
    _verify_login(admin_url, role=role, password=password)
    return ProvisioningResult(
        role=role,
        database=database,
        role_created=created,
        granted_tables=granted,
        skipped_optional_tables=skipped,
        login_verified=True,
    )


def main() -> int:
    try:
        admin_url = _require_secret("MANAGER_DB_ADMIN_URL")
        role = os.getenv("MANAGER_DATABASE_ROLE", DEFAULT_ROLE)
        database = os.getenv("MANAGER_DATABASE_NAME", DEFAULT_DATABASE)
        output_path = _environment_output_path(
            _require_secret("MANAGER_ENV_OUTPUT_PATH")
        )
        api_token = _require_secret("MANAGER_API_TOKEN", minimum_length=32)
        api_hostname = os.getenv("MANAGER_API_HOSTNAME", "")
        result = provision_manager_role(
            admin_url,
            role=role,
            database=database,
        )
        contents = render_manager_environment(
            admin_url,
            role=role,
            database=database,
            password=_require_secret(
                "MANAGER_DATABASE_PASSWORD",
                minimum_length=32,
            ),
            api_token=api_token,
            api_hostname=api_hostname,
        )
        write_manager_environment(output_path, contents)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": type(exc).__name__,
                    "message": "manager database role was not changed safely",
                }
            ),
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "status": "ok",
                **result.as_dict(),
                "environment_written": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
