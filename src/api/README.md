# Manager API contracts

The API is read-only. Every `/api/v1/**` request requires
`Authorization: Bearer <MANAGER_API_TOKEN>`. `/health` is unauthenticated and
returns only `{"status":"ok"}`. Date ranges default to the last 30 available
days and are capped at 366 inclusive days.

`/api/v1/overview` accepts `preset=30d|60d|90d|ytd` (default `30d`).
Presets are bounded to available sales history. An explicit `start` takes
precedence over the preset; `end` may still select the anchor date.

Public GET routes and top-level response keys:

- `/api/v1/overview`: `provenance`, `period`, `available_range`, `kpis`, `daily`, `pnl`,
  `reorder_alerts`, `reorder_alerts_truncated`
- `/api/v1/daily-sales`: `provenance`, `period`, `totals`, `daily`
- `/api/v1/staffing-rush`: `provenance`, `period`, `kpis`, `daily`, `hourly`
- `/api/v1/profitability`: `provenance`, `period`, `pnl`, `categories`, `cost_health`
- `/api/v1/inventory/health`: `provenance`, `requested_as_of`, `data_as_of`, `summary`,
  `items`, `truncated`
- `/api/v1/import-operations`: `provenance`, `latest_run`, `coverage`, `missing_reports`,
  `recent_imports`

Every business response has
`provenance:{generated_at,data_as_of,source_query_ids,assumptions}`. Query IDs
are stable code/query-layer identifiers rather than raw SQL, and `assumptions`
is empty for these direct query results.

The generated OpenAPI schema documents every nested field. Response DTOs use
`extra="forbid"` and are populated field by field; query/dataframe columns are
never passed through wholesale.

Deliberately excluded:

- employee names, IDs, contact information, roles, shifts, and individual pay
- owner distributions and retained cash
- raw filenames, paths, staging directories, hashes, and error messages
- `inv_items.current_qty`; on-hand inventory comes from ledger `closing_qty`

The bearer token is a server secret. A Sites frontend must call this API through
a server-side function/proxy and must not embed the token in browser JavaScript.
