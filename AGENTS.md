# AGENTS.md — bar-arbolada-database

Read `README.md` first (architecture, data boundaries), then the runbooks in
`planning-documents/` for the task at hand. Schema lives under `alembic/`.
Accepted architecture decisions live under `docs/adr/` (e.g. inventory ledger SoT).

Core rules: production data, credentials (`.env`), raw CSVs/invoices, and
QuickBooks exports are local-only and never leave this repo. SQL-backed facts
are separated from assumptions — cite the query behind any claim.

## Second Brain

Durable cross-project memory lives at `C:\Users\alecw\Claude\Projects\second-brain`
(project page: `projects/bar-arbolada.md`). Check it for prior decisions and open
questions before large tasks. This repo is authoritative for all operational data,
schema, ingestion, and dashboards — never copy credentials, production query
results, or financial details into the vault; dated analysis summaries with exact
query pointers only. Vault-routed sessions are read-only against the database
unless Alec explicitly says otherwise. After significant sessions, append a
≤20-line after-session note per the vault's AGENTS.md.
