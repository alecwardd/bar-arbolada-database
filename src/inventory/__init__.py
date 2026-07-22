"""
Inventory engine modules:
  - ledger: Daily theoretical inventory calculations (source of truth for on-hand qty)
  - uom: Convert recipe/invoice quantities into each item's stock unit

Reorder alerts for dashboards and CLI read ``inv_daily_ledger`` (see
``docs/adr/0001-inventory-ledger-source-of-truth.md``).
"""
