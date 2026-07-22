"""
Bar Arbolada Analytics System - SQLAlchemy Models

All 21 database tables across 5 domains:
  - Import Tracking (1)
  - POS Master Data (6)
  - Sales Data (8)
  - Inventory (6)
  - Recipes + Theoretical Inventory (3)

Note: UUIDs from Lightspeed are stored as strings (not native UUID type)
to simplify import/export and avoid driver-specific issues.
"""

from datetime import datetime, date, time
from decimal import Decimal
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Numeric,
    Boolean,
    Date,
    Time,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Index,
    text as sql_text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


# ============================================================================
# IMPORT TRACKING
# ============================================================================


class ImportLog(Base):
    """Tracks every CSV/PDF import for auditability and deduplication."""

    __tablename__ = "import_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(500), nullable=False)
    import_type = Column(
        String(50), nullable=False
    )  # 'items', 'checks', 'sales', 'product_mix', etc.
    report_date_start = Column(Date, nullable=True)
    report_date_end = Column(Date, nullable=True)
    imported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    row_count = Column(Integer, nullable=True)
    status = Column(
        String(20), default="pending", nullable=False
    )  # pending, success, error, duplicate
    error_message = Column(Text, nullable=True)
    file_hash = Column(String(64), nullable=True)  # SHA-256 for dedup

    __table_args__ = (Index("ix_import_logs_file_hash", "file_hash"),)


class ImportRunSnapshot(Base):
    """Stores one summary snapshot per import_from_email run."""

    __tablename__ = "import_run_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)
    staging_root = Column(String(500), nullable=True)
    run_staging_dir = Column(String(500), nullable=True)
    messages_fetched = Column(Integer, nullable=False, server_default="0")
    csv_attachments_saved = Column(Integer, nullable=False, server_default="0")
    lookback_days = Column(Integer, nullable=False, server_default="7")
    coverage_max_dates_json = Column(Text, nullable=True)
    missing_report_days_json = Column(Text, nullable=True)
    generated_on = Column(Date, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=sql_text("CURRENT_TIMESTAMP"))

    __table_args__ = (Index("ix_import_run_snapshots_created_at", "created_at"),)


# ============================================================================
# POS MASTER DATA
# ============================================================================


class PosCategory(Base):
    """
    POS category hierarchy.
    Sourced from: Category List CSV + Product Mix Report hierarchy.
    """

    __tablename__ = "pos_categories"

    id = Column(String(36), primary_key=True)  # Lightspeed UUID
    name = Column(String(200), nullable=False)
    default_printer_group = Column(String(100), nullable=True)
    requires_position = Column(Boolean, nullable=True)
    tax_type = Column(String(50), nullable=True)
    reset_stock_on_close = Column(String(50), nullable=True)
    status = Column(String(20), nullable=True)
    parent_category_id = Column(
        String(36), ForeignKey("pos_categories.id"), nullable=True
    )
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    parent = relationship("PosCategory", remote_side=[id], backref="children")


class PosDisplayGroup(Base):
    """
    Display group definitions (how items are organized on POS screens).
    Sourced from: Display Groups CSV.
    """

    __tablename__ = "pos_display_groups"

    id = Column(String(36), primary_key=True)  # Lightspeed UUID
    name = Column(String(200), nullable=False)
    display_timing = Column(String(10), nullable=True)  # 'Yes' or 'No'
    time_start = Column(Time, nullable=True)
    time_end = Column(Time, nullable=True)
    date_start = Column(Date, nullable=True)
    date_end = Column(Date, nullable=True)
    repeat_days = Column(String(100), nullable=True)  # 'mon, tue, wed, ...'
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)


class PosItem(Base):
    """
    POS menu item catalog (712+ items).
    Sourced from: Item List CSV.
    """

    __tablename__ = "pos_items"

    id = Column(String(36), primary_key=True)  # Lightspeed UUID
    name = Column(String(300), nullable=False)
    online_menu_name = Column(String(300), nullable=True)
    chit_name = Column(String(300), nullable=True)
    receipt_name = Column(String(300), nullable=True)
    description = Column(Text, nullable=True)
    online_menu_description = Column(Text, nullable=True)
    sort_code = Column(String(100), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    cost = Column(Numeric(10, 2), nullable=True)
    tax_rate = Column(String(200), nullable=True)  # semicolon-separated tax names
    printer_group = Column(String(100), nullable=True)
    category_name = Column(String(200), nullable=True)  # denormalized from POS
    item_contains_alcohol = Column(Boolean, nullable=True)
    course = Column(String(50), nullable=True)
    allow_price_override = Column(Boolean, nullable=True)
    min_sides = Column(Integer, nullable=True)
    max_sides = Column(Integer, nullable=True)
    status = Column(String(20), nullable=True)
    reset_stock_on_close = Column(String(50), nullable=True)
    current_stock_level = Column(Integer, nullable=True)
    reset_stock_value = Column(Integer, nullable=True)
    modifier_groups_raw = Column(Text, nullable=True)  # raw semicolon-separated list
    display_groups_raw = Column(Text, nullable=True)  # raw semicolon-separated list
    item_identifier = Column(String(200), nullable=True)
    online_ordering_price = Column(Numeric(10, 2), nullable=True)
    include_preorders_in_stock = Column(Boolean, nullable=True)

    # Our enrichments (not from Lightspeed)
    inventory_tier = Column(
        String(1), nullable=True
    )  # 'A', 'B', 'C' -- set by us for inventory tracking priority

    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (Index("ix_pos_items_category", "category_name"),)


class PosItemAlias(Base):
    """
    Maps old item UUIDs/names to new ones after POS restructure.
    Enables historical data to connect through renames, merges, and replacements.

    Example: 'House Wine' (old_item_id=abc123) -> 'Red Wine Glass' (new_item_id=def456)
    """

    __tablename__ = "pos_item_aliases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    old_item_id = Column(String(36), nullable=False)  # original Lightspeed UUID
    old_item_name = Column(String(300), nullable=False)
    new_item_id = Column(
        String(36), ForeignKey("pos_items.id"), nullable=True
    )  # new UUID (null if deleted with no replacement)
    new_item_name = Column(String(300), nullable=True)
    alias_type = Column(
        String(20), nullable=False
    )  # 'rename', 'merge', 'replace', 'delete'
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_pos_item_aliases_old_id", "old_item_id"),)


class PosModifierGroup(Base):
    """
    Modifier group definitions (e.g., 'Whiskey Upcharge', 'Meat Temp', 'Bread').
    Sourced from: Modifier Groups CSV.
    """

    __tablename__ = "pos_modifier_groups"

    id = Column(String(36), primary_key=True)  # Lightspeed UUID
    name = Column(String(200), nullable=False)
    display_name = Column(String(200), nullable=True)
    print_on_ticket = Column(Boolean, nullable=True)
    sort_code = Column(String(100), nullable=True)
    status = Column(String(20), nullable=True)
    min_selections = Column(Integer, nullable=True)
    max_selections = Column(Integer, nullable=True)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)


class PosModifier(Base):
    """
    Individual modifiers (e.g., 'Premium Spirit +$8', 'Medium-Rare', 'Bagel').
    Sourced from: Modifier List CSV.
    """

    __tablename__ = "pos_modifiers"

    id = Column(String(36), primary_key=True)  # Lightspeed UUID
    name = Column(String(300), nullable=False)
    chit_name = Column(String(300), nullable=True)
    receipt_name = Column(String(300), nullable=True)
    sort_code = Column(String(100), nullable=True)
    price = Column(Numeric(10, 2), nullable=True)
    tax_rate = Column(String(200), nullable=True)
    status = Column(String(20), nullable=True)
    modifier_groups_raw = Column(
        Text, nullable=True
    )  # raw semicolon-separated group names
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)


# ============================================================================
# SALES DATA
# ============================================================================


class PosDailySales(Base):
    """
    One row per trading day -- aggregated totals from Sales Report.
    The high-level daily snapshot.
    """

    __tablename__ = "pos_daily_sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trading_day = Column(Date, nullable=False, unique=True)

    # Sales totals
    total_receipts = Column(Numeric(10, 2), nullable=True)
    gross_sales = Column(Numeric(10, 2), nullable=True)
    gross_without_tax = Column(Numeric(10, 2), nullable=True)
    net_sales = Column(Numeric(10, 2), nullable=True)

    # Tax breakdown
    liquor_tax = Column(Numeric(10, 2), nullable=True)
    sales_tax = Column(Numeric(10, 2), nullable=True)
    fees = Column(Numeric(10, 2), nullable=True)
    total_tax = Column(Numeric(10, 2), nullable=True)
    tax_on_comps = Column(Numeric(10, 2), nullable=True)

    # Guest/check metrics
    total_guests = Column(Integer, nullable=True)
    total_checks = Column(Integer, nullable=True)
    guest_avg = Column(Numeric(10, 2), nullable=True)
    check_avg = Column(Numeric(10, 2), nullable=True)

    # Payment breakdown
    cash_payments = Column(Numeric(10, 2), nullable=True)
    credit_payments = Column(Numeric(10, 2), nullable=True)
    cash_tips = Column(Numeric(10, 2), nullable=True)
    credit_tips = Column(Numeric(10, 2), nullable=True)
    total_tips = Column(Numeric(10, 2), nullable=True)

    # Comps/voids
    total_comps = Column(Numeric(10, 2), nullable=True)
    total_voids = Column(Numeric(10, 2), nullable=True)

    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)


class PosDailySalesByDaypart(Base):
    """
    Sales broken down by day part (Happy Hour, Close, Open, None).
    Sourced from: Sales Report 'Sales Chart' + 'Metrics' sections.
    """

    __tablename__ = "pos_daily_sales_by_daypart"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trading_day = Column(Date, nullable=False)
    day_part = Column(String(50), nullable=False)  # 'Happy Hour', 'Close', 'Open', 'None'

    gross_sales = Column(Numeric(10, 2), nullable=True)
    net_sales = Column(Numeric(10, 2), nullable=True)
    guests = Column(Integer, nullable=True)
    checks = Column(Integer, nullable=True)
    guest_avg = Column(Numeric(10, 2), nullable=True)
    check_avg = Column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("trading_day", "day_part", name="uq_daypart_day"),
    )


class PosDailySalesByCategory(Base):
    """
    Category-level daily sales breakdown.
    Sourced from: Sales Report 'Categories' section.
    """

    __tablename__ = "pos_daily_sales_by_category"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trading_day = Column(Date, nullable=False)
    category_name = Column(String(200), nullable=False)

    gross_sales = Column(Numeric(10, 2), nullable=True)
    comps = Column(Numeric(10, 2), nullable=True)
    total_tax = Column(Numeric(10, 2), nullable=True)
    net_sales = Column(Numeric(10, 2), nullable=True)
    receipt_total = Column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("trading_day", "category_name", name="uq_category_day"),
    )


class PosHourlySales(Base):
    """
    Hourly sales aggregation -- DERIVED from pos_checks timestamps.
    Not imported from a separate CSV; computed during checks import.

    Powers: rush prediction, staffing heatmaps, shift cut analysis, SPLH by hour.
    """

    __tablename__ = "pos_hourly_sales"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trading_day = Column(Date, nullable=False)
    hour_of_day = Column(Integer, nullable=False)  # 0-23 (e.g., 17 = 5pm)

    net_sales = Column(Numeric(10, 2), nullable=True)
    gross_sales = Column(Numeric(10, 2), nullable=True)
    check_count = Column(Integer, nullable=True)
    guest_count = Column(Integer, nullable=True)
    avg_check = Column(Numeric(10, 2), nullable=True)
    tips = Column(Numeric(10, 2), nullable=True)

    __table_args__ = (
        UniqueConstraint("trading_day", "hour_of_day", name="uq_hourly_day"),
        Index("ix_hourly_sales_day", "trading_day"),
    )


class PosCheck(Base):
    """
    Check-level detail (one row per check/tab).
    Sourced from: Checks Report CSV.
    """

    __tablename__ = "pos_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    check_number = Column(String(20), nullable=False)
    check_name = Column(String(200), nullable=True)
    server = Column(String(200), nullable=True)
    opened_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=True)
    guests = Column(Integer, nullable=True)
    comps = Column(Numeric(10, 2), nullable=True)
    voids = Column(Numeric(10, 2), nullable=True)
    net_sales = Column(Numeric(10, 2), nullable=True)
    auto_grat = Column(Numeric(10, 2), nullable=True)
    total_tax = Column(Numeric(10, 2), nullable=True)
    bill_total = Column(Numeric(10, 2), nullable=True)
    payment_total = Column(Numeric(10, 2), nullable=True)
    tips_total = Column(Numeric(10, 2), nullable=True)

    # Payment breakdown
    cash_payment = Column(Numeric(10, 2), nullable=True)
    cash_tips = Column(Numeric(10, 2), nullable=True)
    credit_payment = Column(Numeric(10, 2), nullable=True)
    credit_tips = Column(Numeric(10, 2), nullable=True)

    revenue_center = Column(String(100), nullable=True)
    trading_day = Column(Date, nullable=True)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("check_number", "trading_day", "opened_at", "check_name", name="uq_check_day"),
        Index("ix_checks_trading_day", "trading_day"),
        Index("ix_checks_opened_at", "opened_at"),
    )


class PosProductMix(Base):
    """
    Item-level sales data (quantity sold, revenue, cost, comps per item).
    Sourced from: Product Mix Report CSV.
    This is the KEY table for theoretical inventory depletion.
    """

    __tablename__ = "pos_product_mix"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_start_date = Column(Date, nullable=False)
    report_end_date = Column(Date, nullable=False)
    entry_type = Column(
        String(20), nullable=False
    )  # 'Category', 'Item', 'Modifier'
    pos_item_id = Column(String(36), nullable=True)  # Lightspeed UUID
    item_name = Column(String(300), nullable=False)

    qty_sold = Column(Integer, nullable=True)
    qty_void = Column(Integer, nullable=True)
    qty_comp = Column(Integer, nullable=True)
    avg_price = Column(Numeric(10, 2), nullable=True)
    cost = Column(Numeric(10, 2), nullable=True)
    gross_sales = Column(Numeric(10, 2), nullable=True)
    comp_amount = Column(Numeric(10, 2), nullable=True)
    total_tax = Column(Numeric(10, 2), nullable=True)
    net_sales = Column(Numeric(10, 2), nullable=True)
    gross_profit = Column(Numeric(10, 2), nullable=True)
    receipt_total = Column(Numeric(10, 2), nullable=True)

    category_name = Column(String(200), nullable=True)
    category_id = Column(String(36), nullable=True)
    item_identifier = Column(String(200), nullable=True)

    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "report_start_date",
            "report_end_date",
            "entry_type",
            "pos_item_id",
            "item_name",
            name="uq_pmix_item_period",
        ),
        Index("ix_pmix_dates", "report_start_date", "report_end_date"),
        Index("ix_pmix_item_id", "pos_item_id"),
    )


class PosComp(Base):
    """
    Individual comp line items with reasons.
    Sourced from: Comps Report CSV.
    """

    __tablename__ = "pos_comps"

    id = Column(Integer, primary_key=True, autoincrement=True)
    comp_date = Column(DateTime, nullable=True)
    comp_reason = Column(String(200), nullable=True)
    check_owner = Column(String(200), nullable=True)
    authorized_by = Column(String(200), nullable=True)
    check_number = Column(String(20), nullable=True)
    comp_type = Column(String(20), nullable=True)  # 'Item' or 'Check'
    item_name = Column(String(300), nullable=True)
    amount = Column(Numeric(10, 2), nullable=True)
    note = Column(Text, nullable=True)
    trading_day = Column(Date, nullable=True)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)

    __table_args__ = (Index("ix_comps_trading_day", "trading_day"),)


class PosVoid(Base):
    """
    Individual void line items with reasons.
    Sourced from: Voids Report CSV.
    """

    __tablename__ = "pos_voids"

    id = Column(Integer, primary_key=True, autoincrement=True)
    void_date = Column(DateTime, nullable=True)
    void_reason = Column(String(200), nullable=True)
    check_owner = Column(String(200), nullable=True)
    authorized_by = Column(String(200), nullable=True)
    check_number = Column(String(20), nullable=True)
    item_name = Column(String(300), nullable=True)
    amount = Column(Numeric(10, 2), nullable=True)
    note = Column(Text, nullable=True)
    trading_day = Column(Date, nullable=True)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)

    __table_args__ = (Index("ix_voids_trading_day", "trading_day"),)


class PosPayment(Base):
    """
    Payment-level detail (one row per payment transaction).
    Sourced from: Payments Report CSV 'Payments List' section.
    """

    __tablename__ = "pos_payments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), nullable=True)  # 'Captured', 'Paid', etc.
    tender_type = Column(String(50), nullable=True)  # 'Credit', 'Cash'
    tender_account = Column(
        String(50), nullable=True
    )  # 'Visa 4727', 'MasterCard 3655', etc.
    payment_date = Column(DateTime, nullable=True)
    check_number = Column(String(20), nullable=True)
    trading_day = Column(Date, nullable=True)
    payment_amount = Column(Numeric(10, 2), nullable=True)
    tip_amount = Column(Numeric(10, 2), nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True)
    server = Column(String(200), nullable=True)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)

    __table_args__ = (Index("ix_payments_trading_day", "trading_day"),)


class PosLabor(Base):
    """
    Timecard-level labor data (one row per shift).
    Sourced from: Labor Report CSV 'Timecards' section.
    """

    __tablename__ = "pos_labor"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), nullable=True)
    last_name = Column(String(100), nullable=True)
    first_name = Column(String(100), nullable=True)
    role = Column(String(100), nullable=True)
    shift_date = Column(Date, nullable=True)
    shift_start = Column(DateTime, nullable=True)
    shift_end = Column(DateTime, nullable=True)
    reg_hours = Column(Numeric(6, 2), nullable=True)
    ot_hours = Column(Numeric(6, 2), nullable=True)
    pay_per_hour = Column(Numeric(8, 2), nullable=True)
    blended_pay_per_hour = Column(Numeric(8, 2), nullable=True)
    total_pay = Column(Numeric(10, 2), nullable=True)
    net_sales = Column(Numeric(10, 2), nullable=True)
    cash_tips = Column(Numeric(10, 2), nullable=True)
    credit_tips = Column(Numeric(10, 2), nullable=True)
    total_tips = Column(Numeric(10, 2), nullable=True)
    trading_day = Column(Date, nullable=True)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)

    __table_args__ = (
        Index(
            "uq_labor_shift",
            "employee_id",
            "last_name",
            "first_name",
            "shift_date",
            "shift_start",
            sql_text("COALESCE(TRIM(role), '')"),
            unique=True,
        ),
        Index("ix_labor_trading_day", "trading_day"),
    )


# ============================================================================
# INVENTORY
# ============================================================================


class InvVendor(Base):
    """
    Vendor master -- suppliers with ordering logistics.
    Order deadlines and lead times power the reorder alert engine.
    """

    __tablename__ = "inv_vendors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True)
    contact_name = Column(String(200), nullable=True)
    email = Column(String(200), nullable=True)
    phone = Column(String(50), nullable=True)
    supply_categories = Column(
        String(500), nullable=True
    )  # 'spirits, wine' or 'food, supplies'
    delivery_days = Column(String(100), nullable=True)  # 'mon,wed,fri'
    order_deadline_day = Column(
        String(20), nullable=True
    )  # 'monday', 'wednesday', etc.
    order_deadline_time = Column(Time, nullable=True)  # e.g., 14:00
    lead_time_days = Column(Integer, nullable=True)  # days from order to delivery
    invoice_format = Column(
        String(50), nullable=True
    )  # 'email_pdf', 'paper', 'portal'
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InvItem(Base):
    """
    Inventory item catalog -- separate from POS items.
    An inv_item represents a purchasable/stockable unit (e.g., a bottle of bourbon),
    while a pos_item represents a sellable unit (e.g., a bourbon pour).
    Linked via pos_item_id.
    """

    __tablename__ = "inv_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(300), nullable=False)
    category = Column(
        String(100), nullable=True
    )  # 'spirits', 'wine', 'beer', 'food', 'supplies'
    subcategory = Column(
        String(100), nullable=True
    )  # 'bourbon', 'tequila', 'vodka', etc.
    unit_of_measure = Column(
        String(50), nullable=True
    )  # 'bottle', 'case', 'each', 'lb', 'oz', 'gallon'
    pack_size = Column(Integer, nullable=True)  # units per case
    bottle_size_ml = Column(Integer, nullable=True)  # for spirits/wine
    par_level = Column(Numeric(10, 2), nullable=True)
    reorder_point = Column(Numeric(10, 2), nullable=True)
    reorder_qty = Column(Numeric(10, 2), nullable=True)
    inventory_tier = Column(
        String(1), nullable=False, default="C"
    )  # 'A', 'B', 'C'

    primary_vendor_id = Column(
        Integer, ForeignKey("inv_vendors.id"), nullable=True
    )
    unit_cost = Column(Numeric(10, 2), nullable=True)  # cost per unit (bottle, each)
    case_cost = Column(Numeric(10, 2), nullable=True)  # cost per case

    # Pour economics (new columns)
    purchase_unit = Column(
        String(50), nullable=True
    )  # how you BUY it from vendor: 'case', 'keg', 'bag', 'bottle', etc.
    current_qty = Column(
        Numeric(10, 2), nullable=True
    )  # manual convenience / UI field only — NOT stock SoT; see inv_daily_ledger + docs/adr/0001
    standard_pour_oz = Column(
        Numeric(5, 2), nullable=True
    )  # pour size per serving in oz (1.5 spirits, 5.0 wine, 16.0 draft)
    menu_price = Column(
        Numeric(10, 2), nullable=True
    )  # what you charge per pour/serving

    pos_item_id = Column(
        String(36), nullable=True
    )  # link to pos_items (may be null for non-sellable items like garnishes)

    status = Column(String(20), default="active")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendor = relationship("InvVendor", backref="items")

    __table_args__ = (
        Index("ix_inv_items_category", "category"),
        Index("ix_inv_items_tier", "inventory_tier"),
    )


class InvInvoice(Base):
    """
    Vendor invoice header.
    Sourced from: parsed PDFs or manual entry.
    """

    __tablename__ = "inv_invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_id = Column(Integer, ForeignKey("inv_vendors.id"), nullable=True)
    invoice_number = Column(String(100), nullable=True)
    invoice_date = Column(Date, nullable=False)
    received_date = Column(Date, nullable=True)
    total_amount = Column(Numeric(10, 2), nullable=True)
    status = Column(
        String(20), default="pending"
    )  # 'pending', 'verified', 'posted'
    source_file = Column(String(500), nullable=True)  # path to original PDF
    notes = Column(Text, nullable=True)
    import_log_id = Column(Integer, ForeignKey("import_logs.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    vendor = relationship("InvVendor", backref="invoices")
    lines = relationship("InvInvoiceLine", back_populates="invoice")

    __table_args__ = (
        UniqueConstraint("vendor_id", "invoice_number", name="uq_invoice_vendor"),
    )


class InvInvoiceLine(Base):
    """
    Individual line item on a vendor invoice (one purchased product per row).
    """

    __tablename__ = "inv_invoice_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(
        Integer, ForeignKey("inv_invoices.id"), nullable=False
    )
    inv_item_id = Column(Integer, ForeignKey("inv_items.id"), nullable=True)
    description = Column(Text, nullable=True)  # raw description from invoice
    quantity = Column(Numeric(10, 2), nullable=True)
    unit_of_measure = Column(String(50), nullable=True)
    unit_price = Column(Numeric(10, 2), nullable=True)
    extended_price = Column(Numeric(10, 2), nullable=True)
    line_number = Column(Integer, nullable=True)
    matched = Column(Boolean, default=False)  # matched to inv_items?
    line_type = Column(
        String(10), nullable=False, default="item", server_default="item"
    )  # 'item', 'credit', 'fee'
    created_at = Column(DateTime, default=datetime.utcnow)

    invoice = relationship("InvInvoice", back_populates="lines")
    inv_item = relationship("InvItem", backref="invoice_lines")


class InvCount(Base):
    """
    Physical inventory count header (full, spot, or cycle count).
    """

    __tablename__ = "inv_counts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    count_date = Column(Date, nullable=False)
    count_type = Column(
        String(20), nullable=False
    )  # 'full', 'spot', 'cycle'
    counted_by = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    status = Column(
        String(20), default="in_progress"
    )  # 'in_progress', 'completed', 'verified'
    created_at = Column(DateTime, default=datetime.utcnow)

    lines = relationship("InvCountLine", back_populates="count")


class InvCountLine(Base):
    """
    Individual line on a physical count (one product per row).
    Captures actual qty and compares to theoretical.
    """

    __tablename__ = "inv_count_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    count_id = Column(Integer, ForeignKey("inv_counts.id"), nullable=False)
    inv_item_id = Column(Integer, ForeignKey("inv_items.id"), nullable=False)
    counted_qty = Column(Numeric(10, 2), nullable=True)
    unit_of_measure = Column(String(50), nullable=True)
    theoretical_qty = Column(
        Numeric(10, 2), nullable=True
    )  # calculated at time of count
    variance = Column(Numeric(10, 2), nullable=True)  # counted - theoretical
    variance_pct = Column(Numeric(6, 2), nullable=True)
    notes = Column(Text, nullable=True)

    count = relationship("InvCount", back_populates="lines")
    inv_item = relationship("InvItem", backref="count_lines")


class InvAdjustment(Base):
    """
    Inventory adjustments for events outside normal sales/purchases.
    Waste, spillage, staff drinks, breakage, vendor credits, etc.
    """

    __tablename__ = "inv_adjustments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inv_item_id = Column(Integer, ForeignKey("inv_items.id"), nullable=False)
    adjustment_date = Column(Date, nullable=False)
    adjustment_type = Column(
        String(30), nullable=False
    )  # 'waste', 'spillage', 'staff_drink', 'comp', 'breakage', 'vendor_credit', 'transfer', 'other'
    quantity = Column(Numeric(10, 2), nullable=True)  # positive = add, negative = remove
    unit_of_measure = Column(String(50), nullable=True)
    reason = Column(Text, nullable=True)
    entered_by = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    inv_item = relationship("InvItem", backref="adjustments")

    __table_args__ = (Index("ix_adjustments_date", "adjustment_date"),)


# ============================================================================
# RECIPES + THEORETICAL INVENTORY
# ============================================================================


class Recipe(Base):
    """
    Links a POS menu item to its recipe (ingredient list).
    A menu item may have multiple recipe versions over time.
    """

    __tablename__ = "recipes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pos_item_id = Column(
        String(36), nullable=False
    )  # link to pos_items (menu item)
    recipe_name = Column(String(300), nullable=False)
    version = Column(Integer, default=1)
    yield_qty = Column(
        Numeric(10, 2), default=1
    )  # how many servings this recipe makes
    status = Column(String(20), default="active")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lines = relationship("RecipeLine", back_populates="recipe")

    __table_args__ = (
        Index("ix_recipes_pos_item", "pos_item_id"),
    )


class RecipeLine(Base):
    """
    Individual ingredient in a recipe.
    e.g., 'Old Fashioned' recipe contains:
      - 2 oz Bourbon (inv_item: House Bourbon)
      - 0.25 oz Simple Syrup
      - 2 dashes Angostura Bitters
    """

    __tablename__ = "recipe_lines"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recipe_id = Column(Integer, ForeignKey("recipes.id"), nullable=False)
    inv_item_id = Column(Integer, ForeignKey("inv_items.id"), nullable=False)
    quantity = Column(Numeric(10, 4), nullable=True)  # amount needed per serving
    unit_of_measure = Column(
        String(50), nullable=True
    )  # 'oz', 'ml', 'dash', 'each', 'slice'
    waste_factor = Column(
        Numeric(4, 2), default=1.0
    )  # 1.0 = no waste, 1.1 = 10% waste
    notes = Column(Text, nullable=True)

    recipe = relationship("Recipe", back_populates="lines")
    inv_item = relationship("InvItem", backref="recipe_usages")


# ============================================================================
# OPERATIONAL EXPENSES
# ============================================================================


class OpExpenseCategory(Base):
    """
    Defines types of fixed/recurring operational costs.
    These are NOT inventory vendors -- they are building, utility, insurance,
    and service costs required to keep the doors open.

    expense_type groups:
      occupancy, energy_utility, internet_telecom, pos_technology,
      cc_processing, cleaning, insurance, licensing, trash_waste,
      repairs_maintenance, marketing, professional_services,
      supplies_non_inventory, miscellaneous
    """

    __tablename__ = "op_expense_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True)
    expense_type = Column(
        String(50), nullable=False
    )  # grouping for P&L rollup
    description = Column(Text, nullable=True)
    typical_frequency = Column(
        String(20), nullable=True
    )  # 'monthly', 'weekly', 'quarterly', 'annual', 'as_needed'
    is_fixed = Column(
        Boolean, default=True
    )  # fixed vs variable cost (rent=fixed, repairs=variable)
    budget_amount = Column(
        Numeric(10, 2), nullable=True
    )  # optional monthly budget target
    status = Column(String(20), default="active")  # 'active', 'inactive'
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    expenses = relationship("OpExpense", back_populates="category")


class RecurringExpense(Base):
    """
    Template for a recurring operating expense.
    Defines what gets auto-generated into op_expenses each period.

    When the amount changes, end this template (set end_date) and create
    a new one with the updated amount. This keeps a clean audit trail.

    frequency: 'monthly', 'quarterly', 'annual'
    """

    __tablename__ = "recurring_expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    expense_category_id = Column(
        Integer, ForeignKey("op_expense_categories.id"), nullable=False
    )
    amount = Column(Numeric(10, 2), nullable=False)
    frequency = Column(String(20), nullable=False)  # 'monthly', 'quarterly', 'annual'
    day_of_month = Column(
        Integer, default=1
    )  # which day expense_date is set to (1-28)
    start_date = Column(Date, nullable=False)  # first month this applies (1st of month)
    end_date = Column(Date, nullable=True)  # last month (null = ongoing)
    payment_method = Column(String(50), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("OpExpenseCategory", backref="recurring_expenses")
    generated_expenses = relationship("OpExpense", back_populates="recurring_expense")

    __table_args__ = (
        Index("ix_recurring_expenses_category", "expense_category_id"),
    )


class OpExpense(Base):
    """
    Individual operational expense entries.
    One row per bill/payment recorded -- either manually entered or
    auto-generated from a RecurringExpense template.

    recurring_expense_id: NULL = manual entry, non-null = auto-generated.
    """

    __tablename__ = "op_expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    expense_category_id = Column(
        Integer, ForeignKey("op_expense_categories.id"), nullable=False
    )
    recurring_expense_id = Column(
        Integer, ForeignKey("recurring_expenses.id"), nullable=True
    )  # null = manually entered, non-null = auto-generated from template
    expense_date = Column(Date, nullable=False)  # date paid or incurred
    period_start = Column(Date, nullable=True)  # what period it covers
    period_end = Column(Date, nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)
    payment_method = Column(
        String(50), nullable=True
    )  # 'check', 'ach', 'auto_pay', 'cash', 'credit_card'
    reference_number = Column(
        String(100), nullable=True
    )  # check #, confirmation #, invoice #
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    category = relationship("OpExpenseCategory", back_populates="expenses")
    recurring_expense = relationship("RecurringExpense", back_populates="generated_expenses")

    __table_args__ = (
        Index("ix_op_expenses_date", "expense_date"),
        Index("ix_op_expenses_category", "expense_category_id"),
        Index("ix_op_expenses_period", "period_start", "period_end"),
        Index("ix_op_expenses_recurring", "recurring_expense_id"),
    )


class OwnerDistribution(Base):
    """
    Owner/investor payouts -- tracked separately from operating expenses.
    These are 'below the line' and do not affect operating P&L.

    Net Operating Income - Distributions - Debt Service = Retained Cash
    """

    __tablename__ = "owner_distributions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    distribution_date = Column(Date, nullable=False)
    recipient = Column(String(200), nullable=False)  # owner/investor name
    amount = Column(Numeric(10, 2), nullable=False)
    distribution_type = Column(
        String(50), nullable=True
    )  # 'owner_draw', 'investor_payout', 'loan_payment', 'interest'
    payment_method = Column(String(50), nullable=True)
    reference_number = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_distributions_date", "distribution_date"),
    )


class InvDailyLedger(Base):
    """
    The heart of theoretical inventory.
    One row per inventory item per day.

    closing = opening + purchases - theoretical_usage + adjustments

    Also computes days_of_cover and reorder_alert.
    """

    __tablename__ = "inv_daily_ledger"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inv_item_id = Column(Integer, ForeignKey("inv_items.id"), nullable=False)
    ledger_date = Column(Date, nullable=False)

    opening_qty = Column(Numeric(10, 2), nullable=True)  # on-hand at start of day
    purchases_qty = Column(Numeric(10, 2), default=0)  # from invoices
    theoretical_usage = Column(Numeric(10, 2), default=0)  # from recipes * sales
    adjustments_qty = Column(Numeric(10, 2), default=0)  # from inv_adjustments
    closing_qty = Column(
        Numeric(10, 2), nullable=True
    )  # opening + purchases - usage + adjustments

    days_of_cover = Column(
        Numeric(6, 1), nullable=True
    )  # closing / avg daily usage
    reorder_alert = Column(Boolean, default=False)

    inv_item = relationship("InvItem", backref="ledger_entries")

    __table_args__ = (
        UniqueConstraint("inv_item_id", "ledger_date", name="uq_ledger_item_day"),
        Index("ix_ledger_date", "ledger_date"),
    )


# ============================================================================
# PAYROLL (TIP POOL + CASH TIPS)
# ============================================================================


class PayrollSettings(Base):
    """
    Single-row config for payroll: kitchen tip-out %, barback multiplier,
    and which POS category counts as 'food' for net food sales.
    """

    __tablename__ = "payroll_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    kitchen_tipout_pct = Column(Numeric(5, 4), default=Decimal("0.05"), nullable=False)
    barback_multiplier = Column(Numeric(4, 2), default=Decimal("0.5"), nullable=False)
    food_category_name = Column(String(200), default="Food", nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PayrollCashTips(Base):
    """
    Manually entered cash tips per trading day (added to FOH pool before split).
    One row per trading day.
    """

    __tablename__ = "payroll_cash_tips"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trading_day = Column(Date, nullable=False, unique=True)
    amount = Column(Numeric(10, 2), default=0, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (Index("ix_payroll_cash_tips_trading_day", "trading_day"),)


class PayrollEmployeeSettings(Base):
    """
    Per-employee tip pool eligibility and weighting.
    Keys match pos_labor identity: employee_id, first_name, last_name.
    Used to exclude placeholders (e.g. BAR 2) and set multiplier (bartender=1.0, barback=0.5).
    employee_id stored as empty string when not present in labor CSV.
    """

    __tablename__ = "payroll_employee_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(String(20), default="", nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    include_in_tip_pool = Column(Boolean, default=True, nullable=False)
    tip_pool_multiplier = Column(Numeric(4, 2), default=Decimal("1"), nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "employee_id", "first_name", "last_name",
            name="uq_payroll_employee_identity",
        ),
        Index("ix_payroll_employee_settings_identity", "employee_id", "first_name", "last_name"),
    )


# ============================================================================
# LABOR PROJECTIONS (FIXED / SALARIED)
# ============================================================================


class LaborFixedDailyCost(Base):
    """
    Fixed daily labor costs not sourced from POS clock-in data.
    Example: fixed manager labor included in profitability/labor projections.
    """

    __tablename__ = "labor_fixed_daily_costs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cost_name = Column(String(200), nullable=False)
    daily_amount = Column(Numeric(10, 2), nullable=False)
    effective_start_date = Column(Date, nullable=False)
    effective_end_date = Column(Date, nullable=True)
    include_in_projections = Column(Boolean, default=True, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_labor_fixed_dates", "effective_start_date", "effective_end_date"),
        Index("ix_labor_fixed_include", "include_in_projections"),
    )


# ============================================================================
# PAYROLL BURDEN (TAX RATE + SERVICE FEES)
# ============================================================================


class PayrollBurdenSettings(Base):
    """
    Employer payroll burden rates applied on top of gross wages.

    payroll_tax_rate    -- employer-side payroll burden as a decimal fraction
                          of total wages.
    payroll_fee_monthly -- flat monthly payroll processing fee.

    Effective date ranges allow the rate to change over time while keeping
    historical labor cost calculations accurate.
    """

    __tablename__ = "payroll_burden_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payroll_tax_rate = Column(Numeric(6, 4), nullable=False)
    payroll_fee_monthly = Column(Numeric(10, 2), nullable=False, default=0)
    effective_start_date = Column(Date, nullable=False)
    effective_end_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_payroll_burden_dates", "effective_start_date", "effective_end_date"),
    )


# ============================================================================
# SCHEDULING & DEMAND FORECASTING
# ============================================================================


class Employee(Base):
    """
    Master employee record. Centralises identity that previously existed
    only as denormalised fields across pos_labor and payroll_employee_settings.
    Auto-seeded from distinct pos_labor records; maintained by GM via dashboard.
    """

    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, autoincrement=True)
    pos_employee_id = Column(String(20), nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    primary_role = Column(String(100), nullable=True)
    hire_date = Column(Date, nullable=True)
    status = Column(String(20), default="active", nullable=False)
    max_hours_per_week = Column(Numeric(5, 2), default=40, nullable=False)
    min_hours_per_week = Column(Numeric(5, 2), default=0, nullable=False)
    phone = Column(String(50), nullable=True)
    email = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    availability = relationship("EmployeeAvailability", back_populates="employee")
    schedule_entries = relationship("ScheduleEntry", back_populates="employee")

    __table_args__ = (
        UniqueConstraint("pos_employee_id", "first_name", "last_name", name="uq_employee_identity"),
        Index("ix_employees_status", "status"),
    )


class EmployeeAvailability(Base):
    """
    Weekly availability windows per employee.
    Each row = one day-of-week slot with a preference level and optional
    time window. Replaces the iCloud notes workflow.
    """

    __tablename__ = "employee_availability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    day_of_week = Column(Integer, nullable=False)  # 0=Mon ... 6=Sun
    available_from = Column(Time, nullable=True)  # null = all day
    available_until = Column(Time, nullable=True)
    preference = Column(
        String(20), default="available", nullable=False
    )  # 'preferred', 'available', 'unavailable'
    effective_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)
    notes = Column(Text, nullable=True)

    employee = relationship("Employee", back_populates="availability")

    __table_args__ = (
        Index("ix_avail_employee_dow", "employee_id", "day_of_week"),
    )


class ScheduleTemplate(Base):
    """
    Reusable shift template (e.g. 'Weekday Normal', 'Thunder Game Day').
    Defines what roles and shifts are needed for a particular type of day.
    """

    __tablename__ = "schedule_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, unique=True)
    day_type = Column(String(30), nullable=False)  # 'weekday', 'weekend', 'event'
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    shifts = relationship("ScheduleTemplateShift", back_populates="template",
                          cascade="all, delete-orphan")


class ScheduleTemplateShift(Base):
    """Individual shift slot within a template (role + time + headcount)."""

    __tablename__ = "schedule_template_shifts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    template_id = Column(Integer, ForeignKey("schedule_templates.id"), nullable=False)
    role = Column(String(100), nullable=False)
    shift_start = Column(Time, nullable=False)
    shift_end = Column(Time, nullable=False)
    headcount = Column(Integer, default=1, nullable=False)

    template = relationship("ScheduleTemplate", back_populates="shifts")


class ScheduleEntry(Base):
    """
    Published schedule: one row per employee per day.
    The GM builds this via the Schedule Builder tab.
    """

    __tablename__ = "schedule_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False)
    schedule_date = Column(Date, nullable=False)
    role = Column(String(100), nullable=True)
    shift_start = Column(Time, nullable=False)
    shift_end = Column(Time, nullable=False)
    status = Column(
        String(20), default="scheduled", nullable=False
    )  # 'scheduled', 'confirmed', 'called_out', 'covered'
    created_by = Column(String(200), nullable=True)
    published_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    employee = relationship("Employee", back_populates="schedule_entries")

    __table_args__ = (
        UniqueConstraint("employee_id", "schedule_date", name="uq_schedule_employee_day"),
        Index("ix_schedule_date", "schedule_date"),
    )


class ExternalEvent(Base):
    """
    OKC Thunder home games, Civic Center shows, and other downtown events
    that materially affect demand at Bar Arbolada (Bricktown location).
    """

    __tablename__ = "external_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_date = Column(Date, nullable=False)
    event_time = Column(Time, nullable=True)
    venue = Column(
        String(50), nullable=False
    )  # 'paycom_center', 'civic_center', 'other'
    event_type = Column(
        String(50), nullable=False
    )  # 'thunder_home', 'concert', 'show', 'convention'
    event_name = Column(String(300), nullable=False)
    expected_impact = Column(
        String(20), default="medium", nullable=False
    )  # 'low', 'medium', 'high', 'massive'
    estimated_attendance = Column(Integer, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("event_date", "venue", "event_name", name="uq_event_date_venue_name"),
        Index("ix_events_date", "event_date"),
        Index("ix_events_venue", "venue"),
    )


class SchedulingSettings(Base):
    """
    Single-row config for the scheduling/demand engine.
    target_splh, minimum staffing rules, default event multipliers.
    """

    __tablename__ = "scheduling_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    target_splh = Column(Numeric(8, 2), default=55, nullable=False)
    min_bartenders = Column(Integer, default=1, nullable=False)
    min_barbacks = Column(Integer, default=1, nullable=False)
    default_shift_length_hours = Column(Numeric(4, 2), default=7, nullable=False)
    bartender_hour_ratio = Column(Numeric(4, 2), default=0.65, nullable=False)
    event_multiplier_thunder = Column(Numeric(4, 2), default=1.80, nullable=False)
    event_multiplier_concert = Column(Numeric(4, 2), default=1.50, nullable=False)
    event_multiplier_show = Column(Numeric(4, 2), default=1.30, nullable=False)
    event_multiplier_convention = Column(Numeric(4, 2), default=1.15, nullable=False)
    cut_threshold_per_bartender = Column(Numeric(8, 2), default=100, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
