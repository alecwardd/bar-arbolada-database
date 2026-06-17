"""
Parsers for Lightspeed POS master-data CSV exports.

These are simple flat CSVs (no title header, no multi-section):
  - Category List
  - Item List
  - Modifier Groups
  - Modifier List
  - Display Groups
"""

import csv
from io import StringIO
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from src.models import (
    PosCategory,
    PosItem,
    PosModifierGroup,
    PosModifier,
    PosDisplayGroup,
)
from src.importers.base import (
    file_hash,
    check_duplicate,
    create_import_log,
    parse_date_range_from_filename,
    read_csv_lines,
    safe_decimal,
    safe_int,
    safe_bool,
    parse_date_str,
)


def _parse_csv_with_header(lines: list[str]) -> list[dict]:
    """Parse CSV lines where line 0 is the header."""
    if not lines:
        return []
    reader = csv.DictReader(StringIO("\n".join(lines)))
    return [row for row in reader]


# ============================================================================
# Categories
# ============================================================================


def import_categories(session: Session, filepath: str | Path) -> int:
    """Import Category List CSV. Returns number of rows imported."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_filename(filepath.name)
    log = create_import_log(
        session, filepath.name, "categories", date_start, date_end, fhash
    )

    lines = read_csv_lines(filepath)
    rows = _parse_csv_with_header(lines)

    count = 0
    for row in rows:
        cat_id = row.get("Category ID", "").strip()
        if not cat_id:
            continue

        cat = session.get(PosCategory, cat_id)
        if cat is None:
            cat = PosCategory(id=cat_id)
            session.add(cat)

        cat.name = row.get("Category Name", "").strip()
        cat.default_printer_group = row.get("Default Printer Group", "").strip() or None
        cat.requires_position = safe_bool(row.get("Requires Position"))
        cat.tax_type = row.get("Tax Type", "").strip() or None
        cat.reset_stock_on_close = row.get("Reset Stock On Close", "").strip() or None
        cat.status = row.get("Status", "").strip() or None
        cat.import_log_id = log.id
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} categories from {filepath.name}")
    return count


# ============================================================================
# Items
# ============================================================================


def import_items(session: Session, filepath: str | Path) -> int:
    """Import Item List CSV. Returns number of rows imported."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_filename(filepath.name)
    log = create_import_log(
        session, filepath.name, "items", date_start, date_end, fhash
    )

    lines = read_csv_lines(filepath)
    rows = _parse_csv_with_header(lines)

    count = 0
    for row in rows:
        item_id = row.get("Item ID", "").strip()
        if not item_id:
            continue

        item = session.get(PosItem, item_id)
        if item is None:
            item = PosItem(id=item_id)
            session.add(item)

        item.name = row.get("Item Name", "").strip()
        item.online_menu_name = row.get("Online Menu Name", "").strip() or None
        item.chit_name = row.get("Chit Name", "").strip() or None
        item.receipt_name = row.get("Receipt Name", "").strip() or None
        item.description = row.get("Description", "").strip() or None
        item.online_menu_description = row.get("Online Menu Description", "").strip() or None
        item.sort_code = row.get("Sort Code", "").strip() or None
        item.price = safe_decimal(row.get("Price"))
        item.cost = safe_decimal(row.get("Cost"))
        item.tax_rate = row.get("Tax Rate", "").strip() or None
        item.printer_group = row.get("Printer Group", "").strip() or None
        item.category_name = row.get("Category", "").strip() or None
        item.item_contains_alcohol = safe_bool(row.get("Item Contains Alcohol"))
        item.course = row.get("Course", "").strip() or None
        item.allow_price_override = safe_bool(row.get("Allow Price Override"))
        item.min_sides = safe_int(row.get("Min Sides"))
        item.max_sides = safe_int(row.get("Max Sides"))
        item.status = row.get("Status", "").strip() or None
        item.reset_stock_on_close = row.get("Reset Stock On Close", "").strip() or None
        item.current_stock_level = safe_int(row.get("Current Stock Level"))
        item.reset_stock_value = safe_int(row.get("Reset Stock Value"))
        item.modifier_groups_raw = row.get("Modifier Groups", "").strip() or None
        item.display_groups_raw = row.get("Display Groups", "").strip() or None
        item.item_identifier = row.get("Item Identifier", "").strip() or None
        item.online_ordering_price = safe_decimal(row.get("Online Ordering Price"))
        item.include_preorders_in_stock = safe_bool(
            row.get("Include Preorders in Stock")
        )
        item.import_log_id = log.id
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} items from {filepath.name}")
    return count


# ============================================================================
# Modifier Groups
# ============================================================================


def import_modifier_groups(session: Session, filepath: str | Path) -> int:
    """Import Modifier Groups CSV."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_filename(filepath.name)
    log = create_import_log(
        session, filepath.name, "modifier_groups", date_start, date_end, fhash
    )

    lines = read_csv_lines(filepath)
    rows = _parse_csv_with_header(lines)

    count = 0
    for row in rows:
        mg_id = row.get("Modifier Group ID", "").strip()
        if not mg_id:
            continue

        mg = session.get(PosModifierGroup, mg_id)
        if mg is None:
            mg = PosModifierGroup(id=mg_id)
            session.add(mg)

        mg.name = row.get("Modifier Group Name", "").strip()
        mg.display_name = row.get("Display Name", "").strip() or None
        mg.print_on_ticket = safe_bool(row.get("Print Display Name On Ticket"))
        mg.sort_code = row.get("Sort Code", "").strip() or None
        mg.status = row.get("Status", "").strip() or None
        mg.min_selections = safe_int(row.get("Selections Possible Min"))
        mg.max_selections = safe_int(row.get("Selections Possible Max"))
        mg.import_log_id = log.id
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} modifier groups from {filepath.name}")
    return count


# ============================================================================
# Modifiers
# ============================================================================


def import_modifiers(session: Session, filepath: str | Path) -> int:
    """Import Modifier List CSV."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_filename(filepath.name)
    log = create_import_log(
        session, filepath.name, "modifiers", date_start, date_end, fhash
    )

    lines = read_csv_lines(filepath)
    rows = _parse_csv_with_header(lines)

    count = 0
    for row in rows:
        mod_id = row.get("Modifier ID", "").strip()
        if not mod_id:
            continue

        mod = session.get(PosModifier, mod_id)
        if mod is None:
            mod = PosModifier(id=mod_id)
            session.add(mod)

        mod.name = row.get("Modifier Name", "").strip()
        mod.chit_name = row.get("Chit Name", "").strip() or None
        mod.receipt_name = row.get("Receipt Name", "").strip() or None
        mod.sort_code = row.get("Sort Code", "").strip() or None
        mod.price = safe_decimal(row.get("Price"))
        mod.tax_rate = row.get("Tax Rate", "").strip() or None
        mod.status = row.get("Status", "").strip() or None
        mod.modifier_groups_raw = row.get("Modifier Groups", "").strip() or None
        mod.import_log_id = log.id
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} modifiers from {filepath.name}")
    return count


# ============================================================================
# Display Groups
# ============================================================================


def import_display_groups(session: Session, filepath: str | Path) -> int:
    """Import Display Groups CSV."""
    filepath = Path(filepath)
    fhash = file_hash(filepath)

    if check_duplicate(session, fhash):
        print(f"  [SKIP] Already imported: {filepath.name}")
        return 0

    date_start, date_end = parse_date_range_from_filename(filepath.name)
    log = create_import_log(
        session, filepath.name, "display_groups", date_start, date_end, fhash
    )

    lines = read_csv_lines(filepath)
    rows = _parse_csv_with_header(lines)

    count = 0
    for row in rows:
        dg_id = row.get("Display Group Id", "").strip()
        if not dg_id:
            continue

        dg = session.get(PosDisplayGroup, dg_id)
        if dg is None:
            dg = PosDisplayGroup(id=dg_id)
            session.add(dg)

        dg.name = row.get("Group Name", "").strip()
        dg.display_timing = row.get("Display Timing", "").strip() or None

        time_start = row.get("Time Start", "").strip()
        time_end = row.get("Time End", "").strip()
        if time_start:
            try:
                from datetime import time as time_type
                parts = time_start.split(":")
                dg.time_start = time_type(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass
        if time_end:
            try:
                from datetime import time as time_type
                parts = time_end.split(":")
                dg.time_end = time_type(int(parts[0]), int(parts[1]))
            except (ValueError, IndexError):
                pass

        dg.date_start = parse_date_str(row.get("Date Start", ""))
        dg.date_end = parse_date_str(row.get("Date End", ""))
        dg.repeat_days = row.get("Repeat", "").strip() or None
        dg.import_log_id = log.id
        count += 1

    log.row_count = count
    log.status = "success"
    session.commit()
    print(f"  [OK] Imported {count} display groups from {filepath.name}")
    return count
