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
    assert row["cost"] == 28.0
    assert row["tier"] == "A"
    assert row["vendor_name"] == "RNDC"
    assert row["delivery_days"] == "thursday"


def test_row_mapper_handles_get_reorder_items_shape():
    """Fields that used to be missing from get_reorder_items must not become $0.00."""
    from scripts.reorder_report import _format_item_line, _row_from_mapping

    # Historical / minimal dashboard shape before unit_cost/tier/delivery were added.
    row = _row_from_mapping(
        {
            "item_name": "Espolon Blanco",
            "category": "Spirits",
            "unit_of_measure": "bottle",
            "par_level": 6,
            "reorder_point": 2,
            "closing_qty": 1.5,
            "days_of_cover": 3.0,
            "ledger_date": "2026-07-22",
            "vendor_name": "RNDC",
            "order_deadline_day": "tuesday",
            "lead_time_days": 2,
        }
    )
    assert row["name"] == "Espolon Blanco"
    assert row["qty"] == 1.5
    assert row["par"] == 6.0
    assert row["cost"] is None
    assert row["tier"] is None
    assert row["delivery_days"] is None
    assert "$0.00" not in _format_item_line(row)
    assert "$?.??" in _format_item_line(row)


def test_default_and_threshold_sql_share_report_columns():
    """
    Both load paths must expose the columns the printer needs.

    Catches the regression where get_reorder_items omitted unit_cost /
    inventory_tier / delivery_days while the threshold SQL selected them.
    """
    queries_src = (ROOT / "src" / "analytics" / "queries.py").read_text(encoding="utf-8")
    report_src = (ROOT / "scripts" / "reorder_report.py").read_text(encoding="utf-8")

    # Slice get_reorder_items body (between its def and the next def).
    start = queries_src.index("def get_reorder_items")
    end = queries_src.index("\ndef get_payroll_date_range", start)
    reorder_fn = queries_src[start:end]

    required = ("i.unit_cost", "i.inventory_tier", "v.delivery_days", "i.status = 'active'")
    for col in required:
        assert col in reorder_fn, f"get_reorder_items missing {col}"
        assert col in report_src, f"threshold SQL path missing {col}"

    # Normalized print-row keys both paths produce via _row_from_mapping.
    from scripts.reorder_report import _row_from_mapping

    shared = {
        "item_name": "X",
        "closing_qty": 1,
        "unit_cost": 2,
        "inventory_tier": "A",
        "par_level": 3,
        "vendor_name": "V",
        "order_deadline_day": "monday",
        "delivery_days": "wednesday",
        "lead_time_days": 1,
        "days_of_cover": 2,
    }
    assert set(_row_from_mapping(shared).keys()) == {
        "name",
        "category",
        "qty",
        "cost",
        "tier",
        "par",
        "vendor_name",
        "order_deadline_day",
        "delivery_days",
        "lead_time_days",
        "days_of_cover",
    }
