"""
Inventory engine modules:
  - ledger: Daily theoretical inventory calculations (source of truth for on-hand qty)

Reorder alerts for dashboards and CLI read ``inv_daily_ledger`` (see
``docs/adr/0001-inventory-ledger-source-of-truth.md``). The unused
``reorder.py`` alert engine was removed; use ``queries.get_reorder_items``.
"""
