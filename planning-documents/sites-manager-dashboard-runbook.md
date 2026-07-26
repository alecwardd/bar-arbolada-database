# Sites Manager Dashboard Runbook

This runbook publishes a private, read-only manager dashboard through Sites
while PostgreSQL, imports, raw files, and the Streamlit operator console remain
on the local Windows host.

## Boundary

```text
Authorized Sites user
  -> private Sites deployment
  -> same-origin server proxy
  -> authenticated Cloudflare Worker relay
  -> one Workers VPC service through Cloudflare Tunnel
  -> FastAPI on 127.0.0.1:8600
  -> dedicated PostgreSQL read-only login
```

Never expose PostgreSQL, Windows file shares, raw report folders, invoice files,
RDP, or SSH. Do not copy production analytics into Sites D1 or R2.

The manager site is read-only. Streamlit remains a separate operator surface
because it contains invoice, expense, payroll, inventory, recipe, scheduling,
and employee write operations.

## Data Contract

The manager API is under `src/api/` and documents its response contracts in
`src/api/README.md`.

It exposes only:

- period-level sales and operating KPIs
- daily sales aggregates
- aggregate staffing efficiency without employee identity
- aggregate profitability and cost-data coverage
- inventory quantities from ledger `closing_qty`
- redacted import health and log summaries

Every response contains provenance with its generation time, data-as-of date,
source query IDs, and an explicit assumptions list.

The API excludes:

- employee names, IDs, contact details, shifts, roles, and individual pay
- owner distributions and retained cash
- raw filenames, file paths, staging directories, hashes, and error details
- invoice uploads or other raw documents
- arbitrary SQL or generic query endpoints

## Local Configuration

The managed production runner uses the ACL-restricted local file
`%LOCALAPPDATA%\BarArbolada\manager-api.env`. For a manual smoke test, put the
same keys in the ignored local `.env.manager-api` or set them only in the
launching PowerShell process:

```dotenv
MANAGER_API_TOKEN=<long random server-only token>
MANAGER_DATABASE_URL=postgresql://bar_manager_read:<password>@localhost:5432/bar_arbolada
MANAGER_API_ALLOWED_HOSTS=127.0.0.1,localhost,manager-api.internal
MANAGER_API_ALLOWED_ORIGINS=
MANAGER_API_ENABLE_DOCS=
MANAGER_API_READINESS_TIMEOUT_SECONDS=2
```

`MANAGER_API_TOKEN` must be at least 32 characters. Never use a
`NEXT_PUBLIC_*` variable for it.

Create a dedicated PostgreSQL login with:

- `CONNECT` on the Bar Arbolada database
- `USAGE` on the application schema
- `SELECT` only on the tables or reporting views used by `src/api/services.py`
- default read-only transactions
- a short statement timeout

Do not reuse the importer or Streamlit database credential. The startup helper
copies `MANAGER_DATABASE_URL` into the API process as `DATABASE_URL`; other
local jobs are unaffected.

An administrator can provision and live-verify the role without putting any
credential on the command line:

```powershell
powershell -ExecutionPolicy Bypass `
  -File scripts/provision_manager_db_role.ps1 `
  -ApiHostname manager-api.internal
```

The wrapper prompts securely only for a one-time administrator URL. It
generates the manager database password and API bearer token, writes the
resulting API environment to
`%LOCALAPPDATA%\BarArbolada\manager-api.env`, restricts its ACL, clears all
process secrets on exit, and never displays them. It grants only the exact
columns declared by
`src.api.read_model.MANAGER_READ_PRIVILEGES`. It fails if the role inherits
another role, a required table/column is missing, the transaction is not
read-only, or the login can read employee names, raw import filenames, or owner
distributions. The currently optional `import_run_snapshots` grant is skipped
when its migration has not been applied; rerun provisioning after adding it.

For a temporary local-only smoke test, the startup helper accepts
`-AllowSharedDatabaseCredential`. Never use that switch for the tunnel service.

## Start And Verify Locally

Start PostgreSQL, then:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_manager_api.ps1
```

Expected listeners:

- FastAPI: `127.0.0.1:8600`
- Streamlit fallback: `127.0.0.1:8501`

`GET /health` is unauthenticated and returns only process liveness. `GET
/ready` is a separate, non-disclosing database-readiness probe: it returns only
`{"status":"ready"}` with HTTP 200 or `{"status":"unavailable"}` with HTTP
503. It never returns an exception, host, database name, role, SQL, or timing
detail. The request wait is capped at five seconds even if misconfigured; the
default is two seconds and the probe's read-only `SELECT 1` has a 1.5-second
PostgreSQL statement timeout.

All `/api/v1/**` routes require the server-only bearer token. API
documentation is disabled unless `MANAGER_API_ENABLE_DOCS=true`.

Verify:

- missing or incorrect bearer token is rejected
- unsupported methods are rejected
- a range longer than 366 days is rejected
- responses have `Cache-Control: private, no-store`
- `/health` can remain healthy while `/ready` reports a database outage
- `/ready` returns within the configured bounded deadline and discloses only
  `ready` or `unavailable`
- no employee identity, owner distributions, filenames, paths, hashes, or
  errors appear in responses
- the read-only PostgreSQL login cannot execute `INSERT`, `UPDATE`, or `DELETE`

## Protected Cloudflare Tunnel And Relay

Use the named, remotely managed `bar-arbolada-managers` Cloudflare Tunnel, not
a quick/public tunnel and not router port forwarding. The tunnel has no public
hostname route. One Workers VPC service is bound to the tunnel and can reach
only `127.0.0.1:8600`; PostgreSQL and the rest of the host are outside its
routing scope.

`cloudflare/manager-api-relay/` is the only public edge. It accepts `GET` for
the six manager resources plus `/health` and `/ready`, rejects every other
path or method, validates two long relay credentials, and then fetches the
fixed private origin `http://manager-api.internal` through the VPC binding.
The Worker strips the relay credentials before forwarding and never receives a
database credential.

This route avoids a custom domain and does not require the Zero Trust checkout.
Workers VPC is still beta, so review the integration and pricing before its
general-availability transition. If the project later moves to a managed
custom domain, Cloudflare Access Service Auth can replace the Worker relay
without changing the Sites request-header contract.

The Sites server proxy sends:

- `CF-Access-Client-Id`
- `CF-Access-Client-Secret`
- the API bearer token

The current relay reuses those header names as private server-to-server
credentials; it is not a Cloudflare Access policy. Browser JavaScript never
receives any of these values. Production CORS remains disabled because
browsers call the same-origin Sites proxy.

Deploy and provision the relay:

```powershell
Set-Location cloudflare\manager-api-relay
npm test
npx wrangler deploy
Set-Location ..\..
powershell -ExecutionPolicy Bypass `
  -File scripts/provision_cloudflare_relay_secrets.ps1
```

The provisioning helper creates or reuses
`%LOCALAPPDATA%\BarArbolada\cloudflare-relay.env`, restricts its ACL, and
uploads `RELAY_CLIENT_ID` and `RELAY_CLIENT_SECRET` without displaying their
values. Sites receives the matching values as `CF_ACCESS_CLIENT_ID` and
`CF_ACCESS_CLIENT_SECRET`.

## Sites Runtime Values

Set these through Sites, never in `.openai/hosting.json`:

```text
BAR_API_BASE_URL=https://bar-arbolada-manager-relay.alecwardd.workers.dev
MANAGER_API_TOKEN=<same server-only API token>
CF_ACCESS_CLIENT_ID=<same value as Worker RELAY_CLIENT_ID>
CF_ACCESS_CLIENT_SECRET=<same value as Worker RELAY_CLIENT_SECRET>
BAR_AUDIT_HASH_KEY=<random HMAC key for pseudonymous read audit IDs>
BAR_MANAGER_ROLES=<email=viewer,email=manager,email=owner>
```

Mark all values except `BAR_API_BASE_URL` as secrets. `BAR_MANAGER_EMAILS`
remains a compatibility fallback that assigns the `manager` role, but new
deployments should use `BAR_MANAGER_ROLES`.

Use Sites custom access. Add only active users in the owning OpenAI workspace.
Managers who are not workspace users continue through the separately protected
Streamlit hostname until an approved external-identity path exists.

The Sites proxy fails closed unless the user has an exact configured role and
all service/audit secrets are present. Successful and failed upstream reads log
only a request ID, HMAC-pseudonymous actor ID, role, route allowlist key, status,
and latency. It never logs email addresses, headers, query strings, response
data, SQL, or credentials.

## Deployment And Live Editing

The live Sites version remains available while source changes are developed and
tested. A new version replaces it only after:

1. Python tests pass.
2. The Sites production build and rendered-shell tests pass.
3. Source is reviewed for secrets and local-only files.
4. The exact source commit is saved as a Sites version.
5. The private version is deployed.

Runtime environment changes also require deploying a saved version to take
effect.

Prefer backward-compatible API and schema changes:

1. deploy additive database/API support
2. deploy the compatible Sites version
3. remove obsolete fields only in a later release

Rollback by redeploying the prior Sites version. To revoke remote data access
immediately, rotate or remove either Worker relay secret, disable the Worker
route, or remove the VPC service binding. Streamlit and local ingestion remain
unchanged.

## Service Operation

The repository uses two narrowly scoped Windows Scheduled Tasks rather than a
third-party service wrapper. They provide auto-start and restart-on-failure
without placing a database URL, bearer token, tunnel token, or credential JSON
in the task command line:

- `\BarArbolada\BarArboladaManagerApi`
- `\BarArbolada\BarArboladaManagerTunnel`

The API runner hardcodes `127.0.0.1:8600`, one worker, bounded concurrency,
libpq's two-second connection timeout, read-only transactions, and finite
statement/lock timeouts. Uvicorn access logging is disabled so query strings
and request headers are not written locally. The tunnel runner accepts either
a remotely managed named-tunnel token file or a locally managed YAML file with
an absolute credentials-file reference, an exact hostname routed to
`127.0.0.1:8600`, and a final `http_status:404` ingress. It does not accept a
quick-tunnel URL or a token value on its command line.

### Prepare local-only service configuration

Generate the API process values with `provision_manager_db_role.ps1`. The
service runner defaults to the generated local-only file:

```text
%LOCALAPPDATA%\BarArbolada\manager-api.env
```

For a deliberate manual override, `-EnvironmentFile` may point to an ignored
`.env.manager-api` in the repository. Never force-add it and do not include
unrelated importer or email settings.

For the preferred remotely managed tunnel, put the copied connector token in
one ACL-restricted local file outside the repository:

```text
%LOCALAPPDATA%\BarArbolada\cloudflared\tunnel-token.txt
```

The file contains only the tunnel token and a trailing newline. Restrict it and
`manager-api.env` to the service operator, Administrators, and SYSTEM before
using system-start mode. The task passes only `--token-file <path>`; the token
does not appear in the task definition or process arguments.

A locally managed tunnel remains supported as an alternative. Put its
`config.yml` and credential JSON under the same local directory. The YAML
`credentials-file` must be the absolute path to that JSON and its final ingress
must be `http_status:404`. Never replace these local files with
`ops/cloudflared/config.example.yml`; that tracked file is a template only.

Validate all paths, required values, Git-ignore status, exact API hostname,
credentials-file presence, Cloudflare binary, and virtual environment without
registering or starting anything:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/install_manager_services.ps1 `
  -Action Validate `
  -ApiHostname manager-api.internal
```

Validation fails before making changes when either local config is missing,
the API token is short, CORS/docs are enabled, hosts contain a wildcard, the
local and remote-managed credential modes are both present, the local
Cloudflare ingress is not fail-closed, or the exact API hostname is absent from
`MANAGER_API_ALLOWED_HOSTS`.

### Install, inspect, restart, and remove

For an always-on production host, open an elevated PowerShell window and
register both tasks under SYSTEM at machine startup:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/install_manager_services.ps1 `
  -Action Install `
  -ApiHostname manager-api.internal `
  -StartupMode AtStartup `
  -StartNow
```

If elevation is unavailable during setup, `-StartupMode AtLogOn` registers
limited current-user tasks instead; remote analytics then require that user to
be logged in. Both modes restart a failed process after one minute, allow start
on battery power, and do not stop merely because power changes. Keep the host
awake during required access hours.

Inspect the exact task states, API binding, liveness HTTP status, and readiness
HTTP status without displaying local config values:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/install_manager_services.ps1 `
  -Action Status
```

`ApiBinding` must be `LoopbackOnly`, liveness must be 200, and readiness must
be 200 before activating the Sites API runtime values. `ReadinessHttpStatus`
503 with liveness 200 specifically means the API process is up but PostgreSQL
did not pass the bounded probe.

After a local config or executable change, restart only the two exact tasks:

```powershell
Stop-ScheduledTask -TaskPath "\BarArbolada\" -TaskName "BarArboladaManagerApi"
Stop-ScheduledTask -TaskPath "\BarArbolada\" -TaskName "BarArboladaManagerTunnel"
Start-ScheduledTask -TaskPath "\BarArbolada\" -TaskName "BarArboladaManagerApi"
Start-ScheduledTask -TaskPath "\BarArbolada\" -TaskName "BarArboladaManagerTunnel"
```

The installer refuses to overwrite same-named tasks it did not create. If the
second task cannot be registered, it restores both prior managed definitions.
To remove only these managed tasks while retaining all local configuration:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/install_manager_services.ps1 `
  -Action Uninstall
```

Monitor:

- `GET http://127.0.0.1:8600/health` for process liveness
- `GET http://127.0.0.1:8600/ready` for bounded database readiness
- tunnel health
- latest data-as-of timestamp
- last successful import snapshot/log
- Sites worker errors without logging headers, emails, query strings, SQL
  parameters, response data, or secrets

If the site reports that local analytics are unavailable:

1. confirm the Windows host and internet connection
2. confirm PostgreSQL is running
3. confirm FastAPI is listening only on `127.0.0.1:8600`
4. confirm the named tunnel service is running
5. confirm the Worker relay secrets and VPC service binding
6. confirm Sites runtime variables are present
7. use Streamlit only if the viewer is authorized for its write-capable surface

## Future Writes

Remain read-only through production validation. Any future manager write route
is a separate architecture decision requiring:

- role-specific authorization
- CSRF protection
- idempotency and conflict handling
- user-attributed audit records
- transaction and rollback tests
- an explicit decision on which roles may perform the action

Do not add writes by extending the read API casually.
