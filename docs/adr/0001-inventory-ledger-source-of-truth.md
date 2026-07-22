# ADR 0001 — Inventory ledger is the source of truth for on-hand quantity

- **Status:** Accepted
- **Date:** 2026-07-22
- **Deciders:** Alec (confirmed); follow-up to 2026-07-22 system audit item 4

## Context

Two parallel notions of "how much do we have?" existed:

1. **`inv_daily_ledger`** — theoretical daily stock from
   `opening + purchases - usage + adjustments`, with `closing_qty`,
   `days_of_cover`, and `reorder_alert`. Dashboards already read this via
   `queries.get_reorder_items`.
2. **`inv_items.current_qty`** — a manually edited convenience field, also
   written by `scripts/record_physical_count.py`, never wired into the
   ledger math.

Separately, `src/inventory/reorder.py` duplicated ledger-backed reorder
logic but was never imported by dashboards or scripts — dead code.
`scripts/reorder_report.py` read `current_qty`, so the CLI disagreed with
the Inventory Dashboard for the same question.

## Decision

**`inv_daily_ledger` is the source of truth for on-hand quantity and reorder
signals.** Operational views (dashboards, CLI reorder report) must read
ledger `closing_qty` / `reorder_alert`, not `inv_items.current_qty`.

Consequences for this change set:

- Delete unused `src/inventory/reorder.py`.
- Repoint `scripts/reorder_report.py` at the ledger (same store as
  `get_reorder_items`).
- Leave `current_qty` on the catalog model for now as a **non-authoritative
  convenience / UI field** — do not treat it as stock truth.
- **No quantity-math change** in this pass (ledger formula unchanged).

## Explicitly deferred (P1)

- **UOM conversion** in ledger usage/purchases (audit item 10) — required
  before trusting theoretical depletion across bottle/oz/case units.
- **Count → ledger wiring** — revive/call `ledger.set_opening_from_count`
  from physical-count flows so counts seed the ledger instead of only
  updating `current_qty`.

## Consequences

- Reorder CLI and Inventory Dashboard agree on stock source.
- Operators editing `current_qty` in the catalog UI does not change reorder
  alerts until counts are wired into the ledger (deferred above).
- Future inventory work should extend the ledger path, not revive a second
  on-hand engine.
