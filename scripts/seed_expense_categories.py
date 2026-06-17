"""
Seed default operating expense categories for Bar Arbolada.

Run once to populate op_expense_categories with the agreed-upon categories.
Safe to re-run -- uses INSERT ... ON CONFLICT DO NOTHING.

Usage:
    python scripts/seed_expense_categories.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from src.config import engine

CATEGORIES = [
    # (name, expense_type, description, typical_frequency, is_fixed)
    (
        "Building Rent / Lease",
        "occupancy",
        "Monthly rent or lease payment for the building",
        "monthly",
        True,
    ),
    (
        "Electric (OG&E)",
        "energy_utility",
        "Monthly electric bill",
        "monthly",
        False,  # varies by season
    ),
    (
        "Gas (ONG)",
        "energy_utility",
        "Monthly natural gas bill",
        "monthly",
        False,
    ),
    (
        "Water / Sewer",
        "energy_utility",
        "Monthly water and sewer charges",
        "monthly",
        False,
    ),
    (
        "Internet / WiFi",
        "internet_telecom",
        "Monthly internet service",
        "monthly",
        True,
    ),
    (
        "Cox Communications (TV & Internet)",
        "internet_telecom",
        "Monthly TV and Internet connection",
        "monthly",
        True,
    ),
    (
        "Lightspeed POS Subscription",
        "pos_technology",
        "Monthly POS software subscription",
        "monthly",
        True,
    ),
    (
        "Payment Terminal Fees",
        "pos_technology",
        "Monthly fees for payment terminals / hardware",
        "monthly",
        True,
    ),
    (
        "Google Nest (Indoor Cameras)",
        "pos_technology",
        "Monthly subscription for indoor security cameras",
        "monthly",
        True,
    ),
    (
        "Credit Card Processing Fees",
        "cc_processing",
        "Merchant services fees on credit card transactions (typically 2.5-3.5%)",
        "monthly",
        False,  # varies with sales volume
    ),
    (
        "Grease / Kitchen Cleaning",
        "cleaning",
        "Grease trap and kitchen hood cleaning service",
        "monthly",
        True,
    ),
    (
        "Trash / Dumpster Service",
        "trash_waste",
        "Waste removal and dumpster rental",
        "monthly",
        True,
    ),
    (
        "General Liability Insurance",
        "insurance",
        "General business liability insurance",
        "monthly",
        True,
    ),
    (
        "Liquor Liability Insurance",
        "insurance",
        "Liquor-specific liability coverage",
        "monthly",
        True,
    ),
    (
        "Property Insurance",
        "insurance",
        "Building/contents property insurance",
        "monthly",
        True,
    ),
    (
        "Workers Compensation Insurance",
        "insurance",
        "Workers comp coverage for employees",
        "monthly",
        True,
    ),
    (
        "Liquor License Renewal",
        "licensing",
        "Annual liquor license renewal fee",
        "annual",
        True,
    ),
    (
        "Health Permits",
        "licensing",
        "Health department permits and inspections",
        "annual",
        True,
    ),
    (
        "Music Licensing (ASCAP/BMI)",
        "licensing",
        "Annual music performance licensing fees",
        "annual",
        True,
    ),
    (
        "Repairs & Maintenance",
        "repairs_maintenance",
        "Equipment repairs, plumbing, HVAC, facility maintenance",
        "as_needed",
        False,
    ),
    (
        "Smallwares & Equipment",
        "repairs_maintenance",
        "Replacement glassware, bar tools, kitchen utensils, small equipment",
        "as_needed",
        False,
    ),
    (
        "Marketing & Advertising",
        "marketing",
        "Social media ads, event promotion, print materials",
        "as_needed",
        False,
    ),
    (
        "Accounting / Bookkeeping",
        "professional_services",
        "Monthly accounting or bookkeeping services",
        "monthly",
        True,
    ),
    (
        "Cleaning Supplies",
        "supplies_non_inventory",
        "Cleaning products, sanitizers, paper goods not tracked in inventory",
        "as_needed",
        False,
    ),
    (
        "Ice Machine Lease & Service (IceTech)",
        "equipment_lease",
        "Monthly ice machine lease, servicing, and maintenance from IceTech",
        "monthly",
        True,
    ),
    (
        "Miscellaneous Operating Expense",
        "miscellaneous",
        "Catch-all for expenses that don't fit other categories",
        "as_needed",
        False,
    ),
]


def seed():
    """Insert default expense categories (skip duplicates)."""
    inserted = 0
    skipped = 0

    with engine.begin() as conn:
        for name, exp_type, desc, freq, is_fixed in CATEGORIES:
            result = conn.execute(
                text("""
                    INSERT INTO op_expense_categories
                    (name, expense_type, description, typical_frequency, is_fixed, status)
                    VALUES (:name, :type, :desc, :freq, :fixed, 'active')
                    ON CONFLICT (name) DO NOTHING
                """),
                {
                    "name": name,
                    "type": exp_type,
                    "desc": desc,
                    "freq": freq,
                    "fixed": is_fixed,
                },
            )
            if result.rowcount > 0:
                inserted += 1
                print(f"  + {name}")
            else:
                skipped += 1
                print(f"  - {name} (already exists)")

    print(f"\nDone: {inserted} inserted, {skipped} skipped.")


if __name__ == "__main__":
    print("Seeding expense categories for Bar Arbolada...\n")
    seed()
