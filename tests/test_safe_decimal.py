"""Unit tests for importer money/number parsing helpers."""

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.importers.base import safe_decimal, safe_int
from src.importers.product_mix_report import import_product_mix_report
from src.models import Base, ImportLog, PosItem, PosProductMix


def test_safe_decimal_parses_money_strings():
    assert safe_decimal("12.34") == Decimal("12.34")
    assert safe_decimal("1,234.56") == Decimal("1234.56")
    assert safe_decimal(" 0.01 ") == Decimal("0.01")
    assert safe_decimal("-3.50") == Decimal("-3.50")


def test_safe_decimal_rejects_empty_and_invalid():
    assert safe_decimal(None) is None
    assert safe_decimal("") is None
    assert safe_decimal("   ") is None
    assert safe_decimal("abc") is None
    assert safe_decimal(True) is None


def test_safe_decimal_rejects_non_finite():
    assert safe_decimal("NaN") is None
    assert safe_decimal("nan") is None
    assert safe_decimal("Infinity") is None
    assert safe_decimal("-inf") is None
    assert safe_decimal(Decimal("NaN")) is None
    assert safe_decimal(Decimal("Infinity")) is None


def test_safe_decimal_never_uses_binary_float():
    # Classic float trap: 0.1 + 0.2 != 0.3 in binary float.
    # Parsing the string must stay exact.
    assert safe_decimal("0.1") + safe_decimal("0.2") == Decimal("0.3")
    assert safe_decimal("19.99") * 2 == Decimal("39.98")


def test_safe_decimal_passthrough_int_and_float_input():
    assert safe_decimal(Decimal("4.50")) == Decimal("4.50")
    assert safe_decimal(7) == Decimal("7")
    assert safe_decimal(3.14) == Decimal("3.14")


def test_safe_int():
    assert safe_int("42") == 42
    assert safe_int("3.9") == 3
    assert safe_int("") is None
    assert safe_int(None) is None
    assert safe_int("NaN") is None


def test_product_mix_db_cost_override_gross_profit_is_decimal(tmp_path):
    """qty_sold * unit_cost and net - cost must stay Decimal (no float mix)."""
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[ImportLog.__table__, PosItem.__table__, PosProductMix.__table__],
    )
    session = sessionmaker(bind=engine)()
    try:
        session.add(
            PosItem(
                id="item-uuid-1",
                name="House Margarita",
                cost=Decimal("2.50"),
            )
        )
        session.commit()

        path = tmp_path / "product-mix-report--2026-02-04-to-2026-02-04--bar.csv"
        path.write_text(
            "\n".join(
                [
                    "Product Mix Report - Bar Arbolada",
                    "02-04-2026 to 02-04-2026",
                    "Type,ID,Name,Sold,Void,Comp,Price,Cost,Gross,Comps,Total Tax,Net,Gross Profit,Receipt Total,Category Name,Category ID,Identifier",
                    "Item,item-uuid-1,House Margarita,4,0,0,12.00,9.99,48.00,0.00,0.00,48.00,38.01,48.00,Cocktails,cat-1,",
                ]
            ),
            encoding="utf-8",
        )

        assert import_product_mix_report(session, path) == 1
        row = session.query(PosProductMix).one()
        assert row.cost == Decimal("10.00")  # 4 * 2.50 from pos_items
        assert row.gross_profit == Decimal("38.00")  # 48.00 - 10.00
        assert isinstance(row.cost, Decimal)
        assert isinstance(row.gross_profit, Decimal)
    finally:
        session.close()
        engine.dispose()
