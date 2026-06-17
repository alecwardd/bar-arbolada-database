# Cloudflare Local Dashboard Runbook

This runbook exposes the Streamlit dashboard through Cloudflare while keeping PostgreSQL and the import automation on the local Windows host.

## Architecture

- Cloudflare publishes a single hostname such as `analytics.yourdomain.com`.
- Cloudflare Access requires login and only allows explicitly approved email addresses.
- `cloudflared` forwards approved requests to `http://localhost:8501`.
- Streamlit reads from the existing local PostgreSQL database.
- The IMAP importer continues to run locally on the same machine.

## What Is And Is Not Exposed

- Exposed: the Cloudflare hostname for the dashboard only.
- Not exposed: PostgreSQL, Windows file shares, RDP, SSH, or other local services.
- Required on the host: PostgreSQL, Python virtualenv, Streamlit, and Task Scheduler.

## Prerequisites

- One Windows machine that will stay on during the hours you want the dashboard and imports available.
- A domain name that you can place under Cloudflare DNS.
- A Cloudflare account with Zero Trust enabled.
- A shortlist of allowed email addresses for owners, investors, and the GM.
- Working local app startup:

```powershell
.venv\Scripts\python.exe -m streamlit run dashboards/app.py
```

- Working local import command:

```powershell
.venv\Scripts\python.exe scripts/import_from_email.py --source imap
```

## Phase 1: Domain And Access

1. Buy a domain from any registrar you prefer.
2. Add the domain to Cloudflare.
3. Move the domain's nameservers to Cloudflare.
4. In Cloudflare Zero Trust, create a team.
5. Choose the dashboard hostname, for example `analytics.yourdomain.com`.
6. Create an initial allowlist with the exact email addresses that should reach the dashboard.

Recommended starter allowlist:

- your owner email
- the GM's email
- any specific investor or owner email that should have read access

## Phase 2: Prepare The Windows Host

1. Use one machine as the permanent host.
2. Confirm the project lives in a stable path.
3. Set Windows power settings so the machine does not sleep overnight.
4. Confirm PostgreSQL starts automatically after reboot.
5. Confirm the Python virtualenv exists and dependencies are installed.
6. Confirm Streamlit starts locally.
7. Confirm the importer runs manually against IMAP.
8. Do not configure any router port forwarding.

## Phase 3: Install Cloudflared

1. Install `cloudflared` on the Windows host.
2. Sign in and authenticate it with your Cloudflare account.
3. Create a named tunnel.
4. Create a public hostname that points to the tunnel.
5. Map that hostname to the local Streamlit app.

Use the example config in [ops/cloudflared/config.example.yml](../ops/cloudflared/config.example.yml) as the starting point.

## Phase 4: Run Streamlit Locally

Start the dashboard with the helper script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_dashboard.ps1
```

Why this script is recommended:

- binds Streamlit to `127.0.0.1`
- keeps the command consistent for the host machine
- avoids accidentally exposing the app on all interfaces

## Phase 5: Publish Only The Dashboard

Once Streamlit is running locally:

1. Point tunnel ingress to `http://localhost:8501`.
2. Keep the final catch-all ingress rule returning `404`.
3. Visit the public hostname and confirm you are routed to the Streamlit app.
4. Verify that only the published hostname resolves through the tunnel.

## Phase 6: Add Cloudflare Access

1. Create a self-hosted Access application for the dashboard hostname.
2. Enable email-based login.
3. Add an `Allow` policy for the exact email addresses you chose earlier.
4. Leave everyone else denied by default.
5. Test with:
   - one allowed email
   - one non-allowed email

Expected result:

- allowed users reach the dashboard after login
- non-allowed users are blocked before they ever hit Streamlit

## Phase 7: Keep Imports Automatic

The importer does not need Cloudflare. It should keep running locally.

Use the helper script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_email_import.ps1
```

Create a Windows Task Scheduler job that:

- runs whether you are logged in or not
- starts in the project root
- runs after the POS report emails are normally delivered
- retries once later in the day if reports sometimes arrive late

Suggested schedule:

- primary run: once per day after the expected email delivery time
- fallback run: 30 to 90 minutes later if delivery can be delayed

## Phase 8: Verify Import Health

After a scheduled run:

1. Open the dashboard through the Cloudflare URL.
2. Visit `Import Operations`.
3. Confirm:
   - recent logs show `success`
   - latest snapshot time updates
   - missing day counts look correct

The importer now writes its run snapshot to both:

- the database, for dashboard visibility
- `reports/email_import_status.json`, for backward compatibility

## Recommended Operating Model

- Use the local-host-plus-Cloudflare setup first.
- Keep the database and importer on the same machine.
- Treat this as the stage-one business deployment.
- Add hosted Postgres or a dedicated worker later only if uptime or scale becomes a problem.

## Failure Modes To Expect

- If the host machine is off, the dashboard is unavailable.
- If the internet connection is down, users cannot reach the dashboard.
- If IMAP credentials expire, imports will stop until updated.
- If PostgreSQL is down, both the dashboard and imports will fail.

## Recovery Checklist

1. Confirm the Windows host is on and awake.
2. Confirm PostgreSQL is running.
3. Restart the dashboard with `scripts/start_dashboard.ps1`.
4. Restart the tunnel service if needed.
5. Re-run the importer with `scripts/run_email_import.ps1`.
6. Check `Import Operations` for new success rows and snapshot updates.
