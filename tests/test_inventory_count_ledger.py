"""
sqlite tests: physical counts seed ledger openings and survive recompute.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.inventory.ledger import _compute_item_ledger, set_opening_from_count
from src.models import (
    Base,
    InvAdjustment,
    InvCount,
    InvCountLine,
    InvDailyLedger,
    InvInvoice,
    InvInvoiceLine,
    InvItem,
    PosProductMix,
    Recipe,
    RecipeLine,
)


@pytest.fixture
def inv_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            InvItem.__table__,
            InvDailyLedger.__table__,
            InvCount.__table__,
            InvCountLine.__table__,
            InvInvoice.__table__,
            InvInvoiceLine.__table__,
            InvAdjustment.__table__,
            Recipe.__table__,
            RecipeLine.__table__,
            PosProductMix.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _item(session, **kwargs) -> InvItem:
    defaults = dict(
        name="Espolon Blanco",
        unit_of_measure="bottle",
        bottle_size_ml=750,
        pack_size=12,
        inventory_tier="A",
        status="active",
    )
    defaults.update(kwargs)
    item = InvItem(**defaults)
    session.add(item)
    session.flush()
    return item


def test_set_opening_from_count_does_not_commit_caller_session(inv_session):
    item = _item(inv_session)
    set_opening_from_count(item.id, date(2026, 7, 22), Decimal("6"), session=inv_session)
    # Not committed — a rollback must discard the ledger row.
    inv_session.rollback()
    assert inv_session.query(InvDailyLedger).count() == 0


def test_count_opening_survives_ledger_recompute(inv_session):
    item = _item(inv_session)
    count_day = date(2026, 7, 22)

    # Prior day closing = 10 (would be used if count ignored)
    inv_session.add(
        InvDailyLedger(
            inv_item_id=item.id,
            ledger_date=date(2026, 7, 21),
            opening_qty=Decimal("10"),
            purchases_qty=Decimal("0"),
            theoretical_usage=Decimal("0"),
            adjustments_qty=Decimal("0"),
            closing_qty=Decimal("10"),
        )
    )

    count = InvCount(
        count_date=count_day,
        count_type="full",
        counted_by="test",
        status="completed",
    )
    inv_session.add(count)
    inv_session.flush()
    inv_session.add(
        InvCountLine(
            count_id=count.id,
            inv_item_id=item.id,
            counted_qty=Decimal("4.5"),
            unit_of_measure="bottle",
        )
    )
    inv_session.flush()

    status, skipped = _compute_item_ledger(inv_session, item, count_day)
    assert status in ("created", "updated")
    assert skipped == 0

    row = (
        inv_session.query(InvDailyLedger)
        .filter_by(inv_item_id=item.id, ledger_date=count_day)
        .one()
    )
    assert row.opening_qty == Decimal("4.5")
    assert row.closing_qty == Decimal("4.5")


def test_count_opening_with_purchase_activity(inv_session):
    item = _item(inv_session)
    count_day = date(2026, 7, 22)

    count = InvCount(
        count_date=count_day, count_type="spot", counted_by="test", status="completed"
    )
    inv_session.add(count)
    inv_session.flush()
    inv_session.add(
        InvCountLine(
            count_id=count.id,
            inv_item_id=item.id,
            counted_qty=Decimal("5"),
            unit_of_measure="bottle",
        )
    )

    invoice = InvInvoice(invoice_date=count_day, status="verified", invoice_number="T-1")
    inv_session.add(invoice)
    inv_session.flush()
    inv_session.add(
        InvInvoiceLine(
            invoice_id=invoice.id,
            inv_item_id=item.id,
            quantity=Decimal("2"),
            unit_of_measure="bottle",
            line_type="item",
        )
    )
    inv_session.flush()

    _compute_item_ledger(inv_session, item, count_day)
    row = (
        inv_session.query(InvDailyLedger)
        .filter_by(inv_item_id=item.id, ledger_date=count_day)
        .one()
    )
    assert row.opening_qty == Decimal("5")
    assert row.purchases_qty == Decimal("2")
    assert row.closing_qty == Decimal("7")


def test_next_day_chains_from_count_closing(inv_session):
    item = _item(inv_session)
    count_day = date(2026, 7, 22)
    next_day = date(2026, 7, 23)

    count = InvCount(
        count_date=count_day, count_type="full", counted_by="test", status="completed"
    )
    inv_session.add(count)
    inv_session.flush()
    inv_session.add(
        InvCountLine(
            count_id=count.id,
            inv_item_id=item.id,
            counted_qty=Decimal("8"),
            unit_of_measure="bottle",
        )
    )
    inv_session.flush()

    _compute_item_ledger(inv_session, item, count_day)
    _compute_item_ledger(inv_session, item, next_day)

    nxt = (
        inv_session.query(InvDailyLedger)
        .filter_by(inv_item_id=item.id, ledger_date=next_day)
        .one()
    )
    assert nxt.opening_qty == Decimal("8")


def test_create_count_from_dict_seeds_ledger_and_updates_current_qty(inv_session):
    from src.inventory.counts import create_count_from_dict

    item = _item(inv_session, current_qty=Decimal("2"))
    count_day = date(2026, 7, 22)

    count = create_count_from_dict(
        inv_session,
        {item.id: Decimal("5.5")},
        counted_by="Dashboard",
        count_type="spot",
        count_date=count_day,
        verbose=False,
    )

    assert count.status == "completed"
    assert count.count_type == "spot"
    line = inv_session.query(InvCountLine).one()
    assert line.theoretical_qty == Decimal("2")
    assert line.counted_qty == Decimal("5.5")
    assert line.variance == Decimal("3.5")

    inv_session.refresh(item)
    assert item.current_qty == Decimal("5.5")

    ledger = (
        inv_session.query(InvDailyLedger)
        .filter_by(inv_item_id=item.id, ledger_date=count_day)
        .one()
    )
    assert ledger.opening_qty == Decimal("5.5")
    assert ledger.closing_qty == Decimal("5.5")


def test_dashboard_edit_omits_current_qty_when_spot_counting():
    """Catalog edit must not commit current_qty before create_count_from_dict."""
    from pathlib import Path

    source = Path("dashboards/views/inventory_items.py").read_text(encoding="utf-8")
    assert "qty_changing = new_qty is not None and old_qty != new_qty" in source
    assert "if not qty_changing:" in source
    assert 'fields["current_qty"] = new_qty' in source


def test_record_script_wires_set_opening_from_count():
    from pathlib import Path

    script = Path("scripts/record_physical_count.py").read_text(encoding="utf-8")
    assert "create_count_from_dict" in script
    assert "10|" not in script

    counts_mod = Path("src/inventory/counts.py").read_text(encoding="utf-8")
    assert "set_opening_from_count" in counts_mod


def test_dashboard_save_quantities_uses_create_count_from_dict():
    from pathlib import Path

    source = Path("dashboards/views/inventory_items.py").read_text(encoding="utf-8")
    assert "create_count_from_dict" in source
    assert "Save Quantities" in source
