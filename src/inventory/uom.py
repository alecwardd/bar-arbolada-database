"""
Inventory unit-of-measure conversion.

Ledger quantities are stored in each item's stock unit
(``InvItem.unit_of_measure``). Recipe lines and invoice lines often use a
different UOM (oz pours, case purchases). Convert into stock units before
summing — never invent bottle/pack sizes when they are missing, and never
treat mismatched discrete units (e.g. slice→bottle) as 1:1.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Optional

ML_PER_OZ = Decimal("29.5735")
ZERO = Decimal("0")

# Normalize common Lightspeed / vendor spellings to a small canonical set.
_ALIASES: dict[str, str] = {
    "bottle": "bottle",
    "bottles": "bottle",
    "btl": "bottle",
    "each": "each",
    "ea": "each",
    "can": "can",
    "cans": "can",
    "piece": "piece",
    "pieces": "piece",
    "slice": "slice",
    "slices": "slice",
    "oz": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "ml": "ml",
    "milliliter": "ml",
    "milliliters": "ml",
    "millilitre": "ml",
    "l": "liter",
    "liter": "liter",
    "litre": "liter",
    "liters": "liter",
    "case": "case",
    "cases": "case",
    "cs": "case",
}

_DISCRETE = frozenset({"bottle", "each", "can", "piece", "slice"})
_VOLUME = frozenset({"oz", "ml", "liter"})


def normalize_uom(uom: Optional[str]) -> Optional[str]:
    """Return canonical UOM token, or None if empty/unknown."""
    if uom is None:
        return None
    key = str(uom).strip().lower()
    if not key:
        return None
    return _ALIASES.get(key)


def _as_decimal(qty) -> Optional[Decimal]:
    if qty is None:
        return None
    try:
        return Decimal(str(qty))
    except (InvalidOperation, ValueError):
        return None


def _ml_per_bottle(bottle_size_ml) -> Optional[Decimal]:
    if bottle_size_ml is None:
        return None
    try:
        ml = Decimal(str(bottle_size_ml))
    except (InvalidOperation, ValueError):
        return None
    if ml <= 0:
        return None
    return ml


def _to_ml(qty: Decimal, uom: str) -> Optional[Decimal]:
    if uom == "ml":
        return qty
    if uom == "oz":
        return qty * ML_PER_OZ
    if uom == "liter":
        return qty * Decimal("1000")
    return None


def _from_ml(ml: Decimal, uom: str) -> Optional[Decimal]:
    if uom == "ml":
        return ml
    if uom == "oz":
        return ml / ML_PER_OZ
    if uom == "liter":
        return ml / Decimal("1000")
    return None


def qty_to_stock_units(
    qty,
    from_uom: Optional[str],
    *,
    stock_uom: Optional[str],
    bottle_size_ml=None,
    pack_size=None,
) -> Optional[Decimal]:
    """
    Convert ``qty`` expressed in ``from_uom`` into ``stock_uom``.

    Returns ``None`` when conversion is unsafe (missing bottle size / pack size,
    unsupported unit pair). Callers should skip that line rather than inventing
    sizes — silent wrong depletion is worse than under-counting with a skip flag.
    """
    amount = _as_decimal(qty)
    if amount is None:
        return None

    src = normalize_uom(from_uom)
    dst = normalize_uom(stock_uom)

    # Missing line UOM: assume already in stock units (common on invoice lines).
    if src is None and dst is not None:
        return amount
    if dst is None:
        # No stock UOM configured — pass through only when source also missing/same raw.
        return amount if src is None else None
    if src is None:
        return None

    if src == dst:
        return amount

    # Volume ↔ volume
    if src in _VOLUME and dst in _VOLUME:
        ml = _to_ml(amount, src)
        if ml is None:
            return None
        return _from_ml(ml, dst)

    # Volume → bottle (spirits/wine stocked by bottle)
    if src in _VOLUME and dst == "bottle":
        ml_bottle = _ml_per_bottle(bottle_size_ml)
        if ml_bottle is None:
            return None
        ml = _to_ml(amount, src)
        if ml is None:
            return None
        return ml / ml_bottle

    # Bottle → volume (rare in ledger; supported for completeness)
    if src == "bottle" and dst in _VOLUME:
        ml_bottle = _ml_per_bottle(bottle_size_ml)
        if ml_bottle is None:
            return None
        return _from_ml(amount * ml_bottle, dst)

    # Case ↔ discrete stock units
    if src == "case" and dst in _DISCRETE:
        try:
            units = Decimal(str(pack_size)) if pack_size is not None else None
        except (InvalidOperation, ValueError):
            units = None
        if units is None or units <= 0:
            return None
        return amount * units

    if src in _DISCRETE and dst == "case":
        try:
            units = Decimal(str(pack_size)) if pack_size is not None else None
        except (InvalidOperation, ValueError):
            units = None
        if units is None or units <= 0:
            return None
        return amount / units

    # Discrete mismatches fail closed — except each↔bottle, a common catalog
    # naming quirk for the same physical unit. Never treat slice/can/piece as
    # bottles (that would silently inflate depletion).
    if {src, dst} == {"each", "bottle"}:
        return amount

    # Unsupported (dash, keg, lb, slice→bottle, …) — fail closed
    return None
