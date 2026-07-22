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


def test_liter_to_bottle():
    got = qty_to_stock_units(Decimal("0.75"), "liter", stock_uom="bottle", bottle_size_ml=750)
    assert got == Decimal("1")


def test_bottle_to_oz():
    got = qty_to_stock_units(1, "bottle", stock_uom="oz", bottle_size_ml=750)
    expected = Decimal("750") / ML_PER_OZ
    assert got == expected


def test_each_bottle_quirk_allowed():
    assert qty_to_stock_units(2, "each", stock_uom="bottle") == Decimal("2")
    assert qty_to_stock_units(2, "bottle", stock_uom="each") == Decimal("2")


def test_mismatched_discrete_fails_closed():
    # slice → bottle must NOT silently count as bottles
    assert qty_to_stock_units(12, "slice", stock_uom="bottle") is None
    assert qty_to_stock_units(1, "can", stock_uom="bottle") is None
    assert qty_to_stock_units(1, "piece", stock_uom="can") is None
