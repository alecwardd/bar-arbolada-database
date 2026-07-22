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

## Explicitly deferred (follow-ups)

- Broader UOM coverage (keg, lb, dash→oz heuristics) beyond the v1 converter
  in `src/inventory/uom.py`.
- Dashboard catalog “Save Quantities” still only updates `current_qty` —
  physical counts should go through `scripts/record_physical_count.py`
  (or a future UI that creates `InvCount` rows) so openings seed the ledger.

## Done (P1, 2026-07-22)

- Ledger purchases/usage/adjustments convert into `InvItem.unit_of_measure`
  via `src/inventory/uom.py` (fail closed when bottle/pack size missing).
- Physical counts call `set_opening_from_count`; ledger recompute prefers a
  completed count on that date as start-of-day opening.

## Consequences

- Reorder CLI and Inventory Dashboard agree on stock source.
- Operators editing `current_qty` in the catalog UI does not change reorder
  alerts until counts are wired into the ledger (deferred above).
- Future inventory work should extend the ledger path, not revive a second
  on-hand engine.
