# Local PostgreSQL Operations

This is the non-secret recovery guide for the Bar Arbolada PostgreSQL instance.
Never put a PostgreSQL password, connection URL containing a password, or
`pgpass` entry in this repository, shell history, the second-brain vault, or a
chat message.

## Current Local Installation

Verified on 2026-07-27:

```text
PostgreSQL version: 17
Host: localhost
Port: 5432
Application database: bar_arbolada
Application role: bar_arbolada
Administrator role: postgres
Administrator maintenance database: postgres
Data directory: C:\Program Files\PostgreSQL\17\data
psql: C:\Program Files\PostgreSQL\17\bin\psql.exe
pg_ctl: C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe
pgAdmin: C:\Program Files\PostgreSQL\17\pgAdmin 4\runtime\pgAdmin4.exe
pgAdmin registered server: PostgreSQL 17
```

The application role is not a PostgreSQL administrator and cannot create the
dedicated manager role. The PostgreSQL server is currently a manual
`pg_ctl` installation rather than a Windows service, so it must be started
after a reboot until the service registration is completed.

## Check, Start, And Stop

Run these from PowerShell. They never contain a credential.

```powershell
$pgRoot = "C:\Program Files\PostgreSQL\17"
$data = Join-Path $pgRoot "data"
$log = Join-Path $env:LOCALAPPDATA "BarArbolada\postgresql-start.log"

& (Join-Path $pgRoot "bin\pg_ctl.exe") status -D $data
& (Join-Path $pgRoot "bin\pg_ctl.exe") start -D $data -l $log -w
& (Join-Path $pgRoot "bin\pg_ctl.exe") stop -D $data -m fast -w
```

Use `stop` only during an intentional maintenance window. Imports, Streamlit,
and the manager site cannot read data while PostgreSQL is stopped.

## Administrator Login

This is the same interactive command previously used on this machine:

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" `
  -h localhost -p 5432 -U postgres -d postgres -W
```

`-W` prompts for the password without placing it in PowerShell history. A
successful session shows a `postgres=#` prompt. Run `\conninfo` to confirm the
host, port, user, and database, then `\q` to exit.

The corresponding URL shape is:

```text
postgresql://postgres:<URL-encoded-password>@localhost:5432/bar_arbolada
```

Do not construct or save that URL manually. The manager-role helper now asks
only for the administrator password and constructs the URL in process memory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\provision_manager_db_role.ps1 `
  -ApiHostname manager-api.internal
```

Use `-AdministratorInput Url` only for an unusual administrator connection.

## Where To Look For The Password

1. Search the password manager for `Bar Arbolada PostgreSQL`, `PostgreSQL 17`,
   `localhost postgres`, or the date PostgreSQL 17 was installed.
2. Open pgAdmin and select the registered **PostgreSQL 17** server. A saved
   credential may let pgAdmin connect, but pgAdmin is not a password viewer.
3. The current machine has no `%APPDATA%\postgresql\pgpass.conf` file. Do not
   create one merely to solve this setup step.
4. The PowerShell history contains the interactive `psql -U postgres` command,
   not the password; the password was entered at the prompt.

If the password is truly lost, stop and use a deliberate local administrator
password-reset procedure. Resetting requires a PostgreSQL outage and careful
single-user access; do not weaken `pg_hba.conf` or switch authentication to
`trust` as an improvised shortcut.

## Password-Manager Record

Keep one private password-manager record named
`Bar Arbolada - PostgreSQL 17 local administrator` with:

- password
- user `postgres`
- host `localhost`
- port `5432`
- maintenance database `postgres`
- application database `bar_arbolada`
- the installation and data-directory paths above
- a pointer to this runbook

The generated `bar_manager_read` password and manager API token remain in the
ACL-restricted `%LOCALAPPDATA%\BarArbolada\manager-api.env`; they should not be
copied into the administrator record.
