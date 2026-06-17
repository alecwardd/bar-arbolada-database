"""
Bar Arbolada - Import All CSVs

Scans a directory for Lightspeed CSV exports and imports them
into the database using the appropriate parser for each file type.

Usage:
    # Import from default directory (raw-csvs-before-pos-changes/)
    python scripts/import_all.py

    # Import from a specific directory
    python scripts/import_all.py path/to/csv/folder

    # Import a single file
    python scripts/import_all.py path/to/file.csv
"""

import sys
from pathlib import Path
import argparse
import shutil

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_session, RAW_CSVS_DIR
from src.importers.base import detect_report_type, file_hash, check_duplicate
from src.importers.master_data import (
    import_categories,
    import_items,
    import_modifier_groups,
    import_modifiers,
    import_display_groups,
)
from src.importers.sales_report import import_sales_report
from src.importers.checks_report import import_checks_report
from src.importers.product_mix_report import import_product_mix_report
from src.importers.comps_voids_report import import_comps_report, import_voids_report
from src.importers.payments_report import import_payments_report
from src.importers.labor_report import import_labor_report


# Map report types to their import functions
IMPORTERS = {
    "categories": import_categories,
    "items": import_items,
    "modifier_groups": import_modifier_groups,
    "modifiers": import_modifiers,
    "display_groups": import_display_groups,
    "sales": import_sales_report,
    "checks": import_checks_report,
    "product_mix": import_product_mix_report,
    "comps": import_comps_report,
    "voids": import_voids_report,
    "payments": import_payments_report,
    "labor": import_labor_report,
}

# Import order matters: master data first, then transactional data
IMPORT_ORDER = [
    "categories",
    "display_groups",
    "modifier_groups",
    "modifiers",
    "items",
    "sales",
    "checks",
    "product_mix",
    "comps",
    "voids",
    "payments",
    "labor",
]


def _archive_file(filepath: Path, archive_dir: Path) -> Path:
    """Move a file into archive_dir, avoiding name collisions."""
    archive_dir.mkdir(parents=True, exist_ok=True)

    dest = archive_dir / filepath.name
    if dest.exists():
        stem = filepath.stem
        suffix = filepath.suffix
        i = 1
        while True:
            candidate = archive_dir / f"{stem}__{i}{suffix}"
            if not candidate.exists():
                dest = candidate
                break
            i += 1

    shutil.move(str(filepath), str(dest))
    return dest


def import_file(session, filepath: Path, *, archive_dir: Path | None = None) -> bool:
    """Import a single CSV file. Returns True if successful."""
    # Compute hash up front so we can verify import success before archiving.
    fhash = file_hash(filepath)

    report_type = detect_report_type(filepath)

    if report_type == "unknown":
        print(f"  [SKIP] Unknown report type: {filepath.name}")
        return False

    importer = IMPORTERS.get(report_type)
    if not importer:
        print(f"  [SKIP] No importer for type '{report_type}': {filepath.name}")
        return False

    try:
        count = importer(session, filepath)
        ok = count >= 0  # 0 is OK (duplicate skip)

        # Archive only when we can confirm a successful prior/current import
        # exists for this exact file content hash.
        if ok and archive_dir is not None:
            log = check_duplicate(session, fhash)
            if log and log.status == "success":
                dest = _archive_file(filepath, archive_dir)
                print(f"  [ARCHIVE] Moved to: {dest}")

        return ok
    except Exception as e:
        print(f"  [ERROR] Failed to import {filepath.name}: {e}")
        import traceback
        traceback.print_exc()
        session.rollback()
        return False


def import_directory(directory: Path, *, archive: bool = True, archive_subdir: str = "imported"):
    """Import all CSV files from a directory in the correct order."""
    if not directory.exists():
        print(f"[ERROR] Directory not found: {directory}")
        return

    csv_files = list(directory.glob("*.csv"))
    if not csv_files:
        print(f"[WARN] No CSV files found in: {directory}")
        return

    print(f"\nFound {len(csv_files)} CSV files in {directory}")
    print("=" * 60)

    # Classify files by type
    files_by_type = {}
    for f in csv_files:
        rtype = detect_report_type(f)
        files_by_type.setdefault(rtype, []).append(f)

    # Import in order
    session = get_session()
    total_success = 0
    total_failed = 0
    archive_dir = (directory / archive_subdir) if archive else None

    for rtype in IMPORT_ORDER:
        files = files_by_type.pop(rtype, [])
        for f in sorted(files):
            print(f"\n[{rtype.upper()}] {f.name}")
            if import_file(session, f, archive_dir=archive_dir):
                total_success += 1
            else:
                total_failed += 1

    # Handle any remaining unclassified files
    for rtype, files in files_by_type.items():
        for f in files:
            print(f"\n[{rtype.upper()}] {f.name}")
            if import_file(session, f, archive_dir=archive_dir):
                total_success += 1
            else:
                total_failed += 1

    session.close()

    print("\n" + "=" * 60)
    print(f"Import complete: {total_success} succeeded, {total_failed} failed")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import Lightspeed CSV exports into the database.")
    parser.add_argument("target", nargs="?", default=None, help="Directory or CSV file to import")
    parser.add_argument(
        "--archive",
        dest="archive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="After successful import, move CSVs into an 'imported/' subfolder (default: enabled).",
    )
    parser.add_argument(
        "--archive-subdir",
        default="imported",
        help="Subfolder name used for archiving (default: imported).",
    )

    args = parser.parse_args()

    if args.target is not None:
        target = Path(args.target)
        if target.is_file():
            session = get_session()
            print(f"\nImporting single file: {target.name}")
            archive_dir = (target.parent / args.archive_subdir) if args.archive else None
            import_file(session, target, archive_dir=archive_dir)
            session.close()
        elif target.is_dir():
            import_directory(target, archive=args.archive, archive_subdir=args.archive_subdir)
        else:
            print(f"[ERROR] Not found: {target}")
            sys.exit(1)
    else:
        import_directory(RAW_CSVS_DIR, archive=args.archive, archive_subdir=args.archive_subdir)
