"""Unit tests for importer money/number parsing helpers."""

from decimal import Decimal

from src.importers.base import safe_decimal, safe_int


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


def test_safe_decimal_never_uses_binary_float():
    # Classic float trap: 0.1 + 0.2 != 0.3 in binary float.
    # Parsing the string must stay exact.
    assert safe_decimal("0.1") + safe_decimal("0.2") == Decimal("0.3")
    assert safe_decimal("19.99") * 2 == Decimal("39.98")


def test_safe_decimal_passthrough_and_int():
    assert safe_decimal(Decimal("4.50")) == Decimal("4.50")
    assert safe_decimal(7) == Decimal("7")


def test_safe_int():
    assert safe_int("42") == 42
    assert safe_int("3.9") == 3
    assert safe_int("") is None
    assert safe_int(None) is None
