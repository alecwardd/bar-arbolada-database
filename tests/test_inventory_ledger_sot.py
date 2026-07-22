"""
Guards for inventory source-of-truth: ledger, not inv_items.current_qty / dead reorder engine.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_dead_reorder_engine_removed():
    assert not (ROOT / "src" / "inventory" / "reorder.py").exists()
    with pytest.raises(ModuleNotFoundError):
        __import__("src.inventory.reorder")


def test_reorder_report_script_is_ledger_backed():
    source = (ROOT / "scripts" / "reorder_report.py").read_text(encoding="utf-8")
    # May mention current_qty in docs as the field we deliberately ignore.
    assert "i.current_qty" not in source
    assert "get_reorder_items" in source
    assert "inv_daily_ledger" in source
    assert "closing_qty" in source


def test_row_mapper_prefers_closing_qty():
    from scripts.reorder_report import _row_from_mapping

    row = _row_from_mapping(
        {
            "item_name": "Espolon Blanco",
            "closing_qty": 1.5,
            "par_level": 6,
            "unit_cost": 28.0,
            "inventory_tier": "A",
            "vendor_name": "RNDC",
            "order_deadline_day": "tuesday",
            "delivery_days": "thursday",
            "lead_time_days": 2,
            "days_of_cover": 3.0,
        }
    )
    assert row["name"] == "Espolon Blanco"
    assert row["qty"] == 1.5
    assert row["par"] == 6.0
    assert row["vendor_name"] == "RNDC"
