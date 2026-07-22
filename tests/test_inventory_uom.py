"""Pure unit tests for inventory UOM conversion."""

from decimal import Decimal

from src.inventory.uom import ML_PER_OZ, normalize_uom, qty_to_stock_units


def test_normalize_aliases():
    assert normalize_uom("Bottles") == "bottle"
    assert normalize_uom("OZ") == "oz"
    assert normalize_uom("cs") == "case"
    assert normalize_uom("dash") is None


def test_oz_to_bottle_uses_bottle_size():
    # 2 oz of a 750ml bottle → fraction of a bottle
    got = qty_to_stock_units(
        Decimal("2"),
        "oz",
        stock_uom="bottle",
        bottle_size_ml=750,
    )
    expected = (Decimal("2") * ML_PER_OZ) / Decimal("750")
    assert got == expected


def test_case_to_bottle_uses_pack_size():
    assert qty_to_stock_units(1, "case", stock_uom="bottle", pack_size=12) == Decimal("12")


def test_identity_bottle_to_bottle():
    assert qty_to_stock_units(Decimal("3.5"), "bottle", stock_uom="bottle") == Decimal("3.5")


def test_missing_bottle_size_fails_closed():
    assert qty_to_stock_units(2, "oz", stock_uom="bottle", bottle_size_ml=None) is None


def test_missing_pack_size_fails_closed():
    assert qty_to_stock_units(1, "case", stock_uom="bottle", pack_size=None) is None


def test_missing_line_uom_assumes_stock_units():
    assert qty_to_stock_units(Decimal("4"), None, stock_uom="bottle") == Decimal("4")


def test_ml_oz_volume_identity():
    oz = qty_to_stock_units(Decimal("29.5735"), "ml", stock_uom="oz")
    assert oz == Decimal("1")
