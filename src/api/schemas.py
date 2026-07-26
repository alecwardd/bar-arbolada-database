"""Explicit public response contracts for the manager API.

These models are intentionally narrower than the underlying analytics query
results.  Adding a database/query column cannot make it appear in an API
response without a corresponding, reviewed schema change here.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictResponse(BaseModel):
    """Reject accidental additions to a public response DTO."""

    model_config = ConfigDict(extra="forbid")


class Period(StrictResponse):
    start: date
    end: date
    days: int = Field(ge=1, le=366)


class AvailableRange(StrictResponse):
    start: date
    end: date


class Provenance(StrictResponse):
    generated_at: datetime
    data_as_of: date | None
    source_query_ids: list[str]
    assumptions: list[str]


class PnlSnapshot(StrictResponse):
    net_sales: float
    cogs: float
    cogs_pct: float
    gross_profit: float
    gross_margin_pct: float
    labor_cost: float
    labor_pct: float
    prime_cost: float
    prime_cost_pct: float
    total_opex: float
    opex_pct: float
    net_operating_income: float
    noi_pct: float


class OverviewKpis(StrictResponse):
    net_sales: float
    avg_daily_sales: float
    avg_check: float | None
    total_checks: int
    trading_days: int
    prime_cost_pct: float
    labor_pct: float
    cogs_pct: float


class DailySalesRow(StrictResponse):
    trading_day: date
    gross_sales: float
    net_sales: float
    total_guests: int
    total_checks: int
    guest_avg: float | None
    check_avg: float | None
    total_tips: float
    total_comps: float
    total_voids: float


class ReorderAlert(StrictResponse):
    ledger_date: date | None
    item_name: str
    category: str | None
    unit_of_measure: str | None
    closing_qty: float | None
    par_level: float | None
    reorder_point: float | None
    days_of_cover: float | None
    vendor_name: str | None
    lead_time_days: int | None


class OverviewResponse(StrictResponse):
    provenance: Provenance
    period: Period
    available_range: AvailableRange
    kpis: OverviewKpis
    daily: list[DailySalesRow]
    pnl: PnlSnapshot
    reorder_alerts: list[ReorderAlert]
    reorder_alerts_truncated: bool


class DailySalesTotals(StrictResponse):
    gross_sales: float
    net_sales: float
    total_guests: int
    total_checks: int
    total_tips: float
    total_comps: float
    total_voids: float


class DailySalesResponse(StrictResponse):
    provenance: Provenance
    period: Period
    totals: DailySalesTotals
    daily: list[DailySalesRow]


class StaffingKpis(StrictResponse):
    net_sales: float
    labor_hours: float
    labor_cost: float
    splh: float | None
    labor_pct: float | None


class StaffingDailyRow(StrictResponse):
    trading_day: date
    net_sales: float
    total_hours: float
    total_labor_cost: float
    splh: float | None
    labor_pct: float | None


class StaffingHourlyRow(StrictResponse):
    dow: int
    dow_name: str
    hour_of_day: int
    avg_net_sales: float
    avg_checks: float
    avg_guests: float
    num_days: int


class StaffingRushResponse(StrictResponse):
    provenance: Provenance
    period: Period
    kpis: StaffingKpis
    daily: list[StaffingDailyRow]
    hourly: list[StaffingHourlyRow]


class CategoryProfitability(StrictResponse):
    category_name: str
    total_qty: float
    net_revenue: float
    total_cost: float
    gross_profit: float
    pour_cost_pct: float | None
    unique_items: int


class CostHealthCategory(StrictResponse):
    category_name: str
    total_items: int
    items_with_cost: int
    total_revenue: float
    revenue_with_cost: float
    revenue_coverage_pct: float | None


class CostHealth(StrictResponse):
    total_items: int
    items_with_cost: int
    total_revenue: float
    revenue_with_cost: float
    total_cogs: float
    revenue_coverage_pct: float | None
    by_category: list[CostHealthCategory]


class ProfitabilityResponse(StrictResponse):
    provenance: Provenance
    period: Period
    pnl: PnlSnapshot
    categories: list[CategoryProfitability]
    cost_health: CostHealth


class InventorySummary(StrictResponse):
    items_tracked: int
    items_below_par: int
    reorder_alerts: int
    items_with_days_of_cover: int


class InventoryItemHealth(StrictResponse):
    ledger_date: date
    item_name: str
    category: str | None
    unit_of_measure: str | None
    closing_qty: float | None
    par_level: float | None
    reorder_point: float | None
    days_of_cover: float | None
    reorder_alert: bool
    vendor_name: str | None


class InventoryHealthResponse(StrictResponse):
    provenance: Provenance
    requested_as_of: date | None
    data_as_of: date | None
    summary: InventorySummary
    items: list[InventoryItemHealth]
    truncated: bool


class ImportRun(StrictResponse):
    source: str
    messages_fetched: int
    csv_attachments_saved: int
    lookback_days: int
    generated_on: date | None
    created_at: datetime | None


class DatasetCoverage(StrictResponse):
    dataset: str
    max_date: date


class MissingReportDays(StrictResponse):
    report_type: str
    missing_days: int
    dates: list[date]
    dates_truncated: bool


class ImportLogSummary(StrictResponse):
    imported_at: datetime
    import_type: str
    report_date_start: date | None
    report_date_end: date | None
    row_count: int | None
    status: str


class ImportOperationsResponse(StrictResponse):
    provenance: Provenance
    latest_run: ImportRun | None
    coverage: list[DatasetCoverage]
    missing_reports: list[MissingReportDays]
    recent_imports: list[ImportLogSummary]


class HealthResponse(StrictResponse):
    status: Literal["ok"]


class ReadinessResponse(StrictResponse):
    """Non-disclosing database-readiness result."""

    status: Literal["ready", "unavailable"]
