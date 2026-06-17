# Daily Email Import Handoff Runbook

This runbook is for owner/GM operations after deployment.

## Recommended Production Setup

- Primary mailbox pattern: business-owned inbox via IMAP (not a personal inbox).
- POS sends daily report emails to that inbox.
- Server runs `scripts/import_from_email.py` on a schedule (daily, after expected report delivery time).
- Dashboard operators monitor `Import Operations` page for status and missing days.

## Why This Is The Default

- Avoids frequent local desktop OAuth prompts.
- Works with most email providers that support IMAP.
- Keeps import pipeline provider-agnostic (you can later switch to AgentMail or another inbox provider without rewriting import parsing).

## One-Time Setup

1. Copy `.env.example` to `.env`.
2. Fill database values.
3. Fill email settings:
   - `EMAIL_SOURCE=imap`
   - `EMAIL_IMAP_HOST`
   - `EMAIL_IMAP_USER`
   - `EMAIL_IMAP_PASSWORD`
   - Optional: `EMAIL_SUBJECT_FILTER`
4. Verify manually:
   - `python scripts/import_from_email.py --source imap`
5. Open dashboard page:
   - `dashboards/pages/12_Import_Operations.py`

## Daily Automated Job

Run once per day after POS reports arrive.

Example cron/scheduler command:

```bash
python scripts/import_from_email.py --source imap
```

What it does:
- Fetches unread messages.
- Saves CSV attachments to staging.
- Reuses `scripts/import_all.py` import logic.
- Writes an import snapshot to the database for the `Import Operations` page.
- Writes status JSON to `reports/email_import_status.json` for local backward compatibility.

## Fallback (Manual)

If inbox integration is down:

1. Export/download reports manually.
2. Place CSVs in `raw-csvs-before-pos-changes`.
3. Run:

```bash
python scripts/import_from_email.py --source local --local-source-dir raw-csvs-before-pos-changes
```

This fallback uses the same import and dedupe path.

## Operator SOP (Owner/GM)

- Check `Import Operations` dashboard daily.
- Green condition:
  - Recent logs are `success`.
  - Missing day counts are zero (or expected close days).
- If red/missing:
  - Re-run import command once.
  - If still red, escalate with latest logs and email delivery evidence.

## Escalation Checklist

- Confirm POS email sent for missing day(s).
- Confirm attachment filenames include date ranges.
- Confirm inbox credentials still valid.
- Re-run command and capture console output.
- Share output and affected dates with support.

## Notes For Multi-User Server Migration

- Same ingestion design still applies.
- Use server-managed secrets (env/secret manager), not user desktop tokens.
- Restrict retry command access to admin-level users.
- Keep import log audit history for investor/owner reporting.

## Optional Future Extension

- Add alternate provider adapter (for example, AgentMail) while keeping the same `EmailSource` contract.
- Keep IMAP path as fallback in case provider API behavior changes.
