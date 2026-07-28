"""Read-only service layer with field-by-field response shaping."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

import pandas as pd

from . import read_model as queries

from .schemas import (
    AvailableRange,
    CategoryProfitability,
    CostHealth,
    CostHealthCategory,
    DailySalesResponse,
    DailySalesRow,
    DailySalesTotals,
    DatasetCoverage,
    ImportLogSummary,
    ImportOperationsResponse,
    ImportRun,
    InventoryHealthResponse,
    InventoryItemHealth,
    InventorySummary,
    MissingReportDays,
    OverviewKpis,
    OverviewResponse,
    Period,
    PnlSnapshot,
    ProfitabilityResponse,
    Provenance,
    ReorderAlert,
    StaffingDailyRow,
    StaffingHourlyRow,
    StaffingKpis,
    StaffingRushResponse,
)


MAX_PERIOD_DAYS = 366
MAX_OVERVIEW_ALERTS = 20
MAX_IMPORT_DATASETS = 50
MAX_MISSING_DATES_PER_REPORT = 60
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")


class InvalidPeriod(ValueError):
    """Raised when caller-supplied dates violate the bounded query contract."""


@dataclass(frozen=True)
class PeriodBounds:
    period: Period
    available_range: AvailableRange


PeriodPreset = Literal["30d", "60d", "90d", "ytd"]


def resolve_period(
    start: date | None,
    end: date | None,
    preset: PeriodPreset = "30d",
) -> PeriodBounds:
    """Resolve optional dates against available sales history and cap the span."""

    available_start_raw, available_end_raw = queries.get_sales_date_range()
    available_start = _as_date(available_start_raw)
    available_end = _as_date(available_end_raw)
    if available_start is None or available_end is None:
        raise RuntimeError("Sales date range is unavailable.")
    if available_start > available_end:
        raise RuntimeError("Sales date range is invalid.")

    resolved_end = end or available_end
    if start is None:
        resolved_end = min(resolved_end, available_end)
    if start is not None:
        resolved_start = start
    elif preset == "ytd":
        resolved_start = max(available_start, date(resolved_end.year, 1, 1))
    else:
        preset_days = {"30d": 30, "60d": 60, "90d": 90}[preset]
        resolved_start = max(
            available_start,
            resolved_end - timedelta(days=preset_days - 1),
        )
    if resolved_start > resolved_end:
        raise InvalidPeriod("start must be on or before end.")

    days = (resolved_end - resolved_start).days + 1
    if days > MAX_PERIOD_DAYS:
        raise InvalidPeriod(f"Date range must not exceed {MAX_PERIOD_DAYS} days.")

    return PeriodBounds(
        period=Period(start=resolved_start, end=resolved_end, days=days),
        available_range=AvailableRange(start=available_start, end=available_end),
    )


def build_overview(bounds: PeriodBounds) -> OverviewResponse:
    period = bounds.period
    sales = queries.get_daily_sales(period.start, period.end)
    pnl_raw = queries.get_full_pnl(
        period.start,
        period.end,
        include_distributions=False,
    )
    alerts = queries.get_reorder_items()

    daily = _daily_sales_rows(sales)
    pnl = _pnl_snapshot(pnl_raw)
    net_sales = sum(row.net_sales for row in daily)
    total_checks = sum(row.total_checks for row in daily)
    check_values = [row.check_avg for row in daily if row.check_avg is not None]
    avg_daily = net_sales / len(daily) if daily else 0.0
    avg_check = sum(check_values) / len(check_values) if check_values else None
    alert_rows = [
        _reorder_alert(row) for _, row in alerts.head(MAX_OVERVIEW_ALERTS).iterrows()
    ]

    (
        net_sales_delta,
        avg_daily_delta,
        avg_check_delta,
        prime_delta,
        labor_delta,
        cogs_delta,
    ) = _prior_period_deltas(bounds, net_sales, avg_daily, avg_check, pnl)

    return OverviewResponse(
        provenance=_provenance(
            bounds.available_range.end,
            [
                "analytics.get_sales_date_range",
                "analytics.get_daily_sales",
                "analytics.get_full_pnl",
                "analytics.get_reorder_items",
            ],
        ),
        period=period,
        available_range=bounds.available_range,
        kpis=OverviewKpis(
            net_sales=net_sales,
            avg_daily_sales=avg_daily,
            avg_check=avg_check,
            total_checks=total_checks,
            trading_days=len(daily),
            prime_cost_pct=pnl.prime_cost_pct,
            labor_pct=pnl.labor_pct,
            cogs_pct=pnl.cogs_pct,
            net_sales_delta=net_sales_delta,
            avg_daily_sales_delta=avg_daily_delta,
            avg_check_delta=avg_check_delta,
            prime_cost_pct_delta=prime_delta,
            labor_pct_delta=labor_delta,
            cogs_pct_delta=cogs_delta,
        ),
        daily=daily,
        pnl=pnl,
        reorder_alerts=alert_rows,
        reorder_alerts_truncated=len(alerts.index) > MAX_OVERVIEW_ALERTS,
    )


def _prior_period_deltas(
    bounds: PeriodBounds,
    net_sales: float,
    avg_daily: float,
    avg_check: float | None,
    pnl: PnlSnapshot,
) -> tuple[
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
    float | None,
]:
    """Compare the selected window to the immediately prior equal-length window."""

    period = bounds.period
    prior_end = period.start - timedelta(days=1)
    if prior_end < bounds.available_range.start:
        return (None, None, None, None, None, None)

    prior_start = prior_end - timedelta(days=period.days - 1)
    if prior_start < bounds.available_range.start:
        return (None, None, None, None, None, None)

    prior_daily = _daily_sales_rows(
        queries.get_daily_sales(prior_start, prior_end)
    )
    if not prior_daily:
        return (None, None, None, None, None, None)

    prior_pnl = _pnl_snapshot(
        queries.get_full_pnl(
            prior_start,
            prior_end,
            include_distributions=False,
        )
    )
    prior_net = sum(row.net_sales for row in prior_daily)
    prior_avg_daily = prior_net / len(prior_daily)
    prior_checks = [row.check_avg for row in prior_daily if row.check_avg is not None]
    prior_avg_check = (
        sum(prior_checks) / len(prior_checks) if prior_checks else None
    )

    return (
        net_sales - prior_net,
        avg_daily - prior_avg_daily,
        (avg_check - prior_avg_check)
        if avg_check is not None and prior_avg_check is not None
        else None,
        pnl.prime_cost_pct - prior_pnl.prime_cost_pct,
        pnl.labor_pct - prior_pnl.labor_pct,
        pnl.cogs_pct - prior_pnl.cogs_pct,
    )


def build_daily_sales(period: Period) -> DailySalesResponse:
    daily = _daily_sales_rows(queries.get_daily_sales(period.start, period.end))
    return DailySalesResponse(
        provenance=_provenance(
            max((row.trading_day for row in daily), default=None),
            ["analytics.get_sales_date_range", "analytics.get_daily_sales"],
        ),
        period=period,
        totals=DailySalesTotals(
            gross_sales=sum(row.gross_sales for row in daily),
            net_sales=sum(row.net_sales for row in daily),
            total_guests=sum(row.total_guests for row in daily),
            total_checks=sum(row.total_checks for row in daily),
            total_tips=sum(row.total_tips for row in daily),
            total_comps=sum(row.total_comps for row in daily),
            total_voids=sum(row.total_voids for row in daily),
        ),
        daily=daily,
    )


def build_staffing_rush(period: Period) -> StaffingRushResponse:
    trend = queries.get_splh_trend(period.start, period.end)
    heatmap = queries.get_hourly_heatmap_data(period.start, period.end)

    daily = [
        StaffingDailyRow(
            trading_day=_required_date(row.get("trading_day")),
            net_sales=_float(row.get("net_sales")),
            total_hours=_float(row.get("total_hours")),
            total_labor_cost=_float(row.get("total_labor_cost")),
            splh=_nullable_float(row.get("splh")),
            labor_pct=_nullable_float(row.get("labor_pct")),
        )
        for _, row in trend.iterrows()
    ]
    hourly = [
        StaffingHourlyRow(
            dow=_int(row.get("dow")),
            dow_name=_text(row.get("dow_name"), max_length=16) or "",
            hour_of_day=_int(row.get("hour_of_day")),
            avg_net_sales=_float(row.get("avg_net_sales")),
            avg_checks=_float(row.get("avg_checks")),
            avg_guests=_float(row.get("avg_guests")),
            num_days=_int(row.get("num_days")),
        )
        for _, row in heatmap.iterrows()
    ]

    net_sales = sum(row.net_sales for row in daily)
    labor_hours = sum(row.total_hours for row in daily)
    labor_cost = sum(row.total_labor_cost for row in daily)
    return StaffingRushResponse(
        provenance=_provenance(
            max((row.trading_day for row in daily), default=None),
            [
                "analytics.get_sales_date_range",
                "analytics.get_splh_trend",
                "analytics.get_hourly_heatmap_data",
            ],
        ),
        period=period,
        kpis=StaffingKpis(
            net_sales=net_sales,
            labor_hours=labor_hours,
            labor_cost=labor_cost,
            splh=(net_sales / labor_hours) if labor_hours > 0 else None,
            labor_pct=(labor_cost / net_sales * 100) if net_sales > 0 else None,
        ),
        daily=daily,
        hourly=hourly,
    )


def build_profitability(period: Period) -> ProfitabilityResponse:
    pnl = _pnl_snapshot(
        queries.get_full_pnl(
            period.start,
            period.end,
            include_distributions=False,
        )
    )
    categories_df = queries.get_category_profitability(period.start, period.end)
    health_raw = queries.get_cost_data_health(period.start, period.end)

    categories = []
    for _, row in categories_df.iterrows():
        revenue = _float(row.get("net_revenue"))
        cost = _float(row.get("total_cost"))
        categories.append(
            CategoryProfitability(
                category_name=_text(row.get("category_name"), max_length=120)
                or "Uncategorized",
                total_qty=_float(row.get("total_qty")),
                net_revenue=revenue,
                total_cost=cost,
                gross_profit=_float(row.get("gross_profit"), default=revenue - cost),
                pour_cost_pct=(cost / revenue * 100) if revenue > 0 else None,
                unique_items=_int(row.get("unique_items")),
            )
        )

    by_category_raw = health_raw.get("by_category")
    if not isinstance(by_category_raw, pd.DataFrame):
        by_category_raw = pd.DataFrame()
    by_category = []
    for _, row in by_category_raw.iterrows():
        total_revenue = _float(row.get("total_revenue"))
        covered_revenue = _float(row.get("revenue_with_cost"))
        by_category.append(
            CostHealthCategory(
                category_name=_text(row.get("category_name"), max_length=120)
                or "Uncategorized",
                total_items=_int(row.get("total_items")),
                items_with_cost=_int(row.get("items_with_cost")),
                total_revenue=total_revenue,
                revenue_with_cost=covered_revenue,
                revenue_coverage_pct=(
                    covered_revenue / total_revenue * 100 if total_revenue > 0 else None
                ),
            )
        )

    total_revenue = _float(health_raw.get("total_revenue"))
    covered_revenue = _float(health_raw.get("revenue_with_cost"))
    health = CostHealth(
        total_items=_int(health_raw.get("total_items")),
        items_with_cost=_int(health_raw.get("items_with_cost")),
        total_revenue=total_revenue,
        revenue_with_cost=covered_revenue,
        total_cogs=_float(health_raw.get("total_cogs")),
        revenue_coverage_pct=(
            covered_revenue / total_revenue * 100 if total_revenue > 0 else None
        ),
        by_category=by_category,
    )
    return ProfitabilityResponse(
        provenance=_provenance(
            period.end,
            [
                "analytics.get_sales_date_range",
                "analytics.get_full_pnl",
                "analytics.get_category_profitability",
                "analytics.get_cost_data_health",
            ],
        ),
        period=period,
        pnl=pnl,
        categories=categories,
        cost_health=health,
    )


def build_inventory_health(
    requested_as_of: date | None,
    limit: int,
) -> InventoryHealthResponse:
    ledger = queries.get_ledger_current(requested_as_of)
    all_items = [_inventory_item(row) for _, row in ledger.iterrows()]
    data_dates = [item.ledger_date for item in all_items]

    below_par = sum(
        1
        for item in all_items
        if item.closing_qty is not None
        and item.par_level is not None
        and item.closing_qty < item.par_level
    )
    return InventoryHealthResponse(
        provenance=_provenance(
            max(data_dates) if data_dates else None,
            ["analytics.get_ledger_current"],
        ),
        requested_as_of=requested_as_of,
        data_as_of=max(data_dates) if data_dates else None,
        summary=InventorySummary(
            items_tracked=len(all_items),
            items_below_par=below_par,
            reorder_alerts=sum(1 for item in all_items if item.reorder_alert),
            items_with_days_of_cover=sum(
                1 for item in all_items if item.days_of_cover is not None
            ),
        ),
        items=all_items[:limit],
        truncated=len(all_items) > limit,
    )


def load_import_rows(limit: int) -> tuple[Any | None, list[Any]]:
    """Load the latest run and safe-to-summarize log rows from local PostgreSQL."""

    return queries.get_import_operations_rows(limit)


def build_import_operations(limit: int) -> ImportOperationsResponse:
    snapshot, logs = load_import_rows(limit)
    latest_run = None
    coverage: list[DatasetCoverage] = []
    missing_reports: list[MissingReportDays] = []

    if snapshot is not None:
        latest_run = ImportRun(
            source=_safe_import_source(snapshot.source),
            messages_fetched=_int(snapshot.messages_fetched),
            csv_attachments_saved=_int(snapshot.csv_attachments_saved),
            lookback_days=_int(snapshot.lookback_days),
            generated_on=_as_date(snapshot.generated_on),
            created_at=_as_datetime(snapshot.created_at),
        )
        coverage = _sanitize_coverage(_json_object(snapshot.coverage_max_dates_json))
        missing_reports = _sanitize_missing_days(
            _json_object(snapshot.missing_report_days_json)
        )

    recent_imports = [
        ImportLogSummary(
            imported_at=_required_datetime(row.imported_at),
            import_type=_safe_label(row.import_type) or "unknown",
            report_date_start=_as_date(row.report_date_start),
            report_date_end=_as_date(row.report_date_end),
            row_count=_nullable_int(row.row_count),
            status=_safe_label(row.status) or "unknown",
        )
        for row in logs
    ]
    return ImportOperationsResponse(
        provenance=_provenance(
            _as_date(snapshot.generated_on) if snapshot is not None else None,
            ["operations.import_run_snapshots.latest", "operations.import_logs.recent"],
        ),
        latest_run=latest_run,
        coverage=coverage,
        missing_reports=missing_reports,
        recent_imports=recent_imports,
    )


def _provenance(data_as_of: date | None, source_query_ids: list[str]) -> Provenance:
    return Provenance(
        generated_at=datetime.now(timezone.utc),
        data_as_of=data_as_of,
        source_query_ids=source_query_ids,
        assumptions=[],
    )


def _daily_sales_rows(frame: pd.DataFrame) -> list[DailySalesRow]:
    return [
        DailySalesRow(
            trading_day=_required_date(row.get("trading_day")),
            gross_sales=_float(row.get("gross_sales")),
            net_sales=_float(row.get("net_sales")),
            total_guests=_int(row.get("total_guests")),
            total_checks=_int(row.get("total_checks")),
            guest_avg=_nullable_float(row.get("guest_avg")),
            check_avg=_nullable_float(row.get("check_avg")),
            total_tips=_float(row.get("total_tips")),
            total_comps=_float(row.get("total_comps")),
            total_voids=_float(row.get("total_voids")),
        )
        for _, row in frame.iterrows()
    ]


def _pnl_snapshot(raw: dict[str, Any]) -> PnlSnapshot:
    net_sales = _float(raw.get("net_sales"))
    cogs = _float(raw.get("cogs"))
    return PnlSnapshot(
        net_sales=net_sales,
        cogs=cogs,
        cogs_pct=(cogs / net_sales * 100) if net_sales > 0 else 0.0,
        gross_profit=_float(raw.get("gross_profit")),
        gross_margin_pct=_float(raw.get("gross_margin_pct")),
        labor_cost=_float(raw.get("labor_cost")),
        labor_pct=_float(raw.get("labor_pct")),
        prime_cost=_float(raw.get("prime_cost")),
        prime_cost_pct=_float(raw.get("prime_cost_pct")),
        total_opex=_float(raw.get("total_opex")),
        opex_pct=_float(raw.get("opex_pct")),
        net_operating_income=_float(raw.get("net_operating_income")),
        noi_pct=_float(raw.get("noi_pct")),
    )


def _reorder_alert(row: pd.Series) -> ReorderAlert:
    return ReorderAlert(
        ledger_date=_as_date(row.get("ledger_date")),
        item_name=_text(row.get("item_name"), max_length=200) or "Unknown item",
        category=_text(row.get("category"), max_length=100),
        unit_of_measure=_text(row.get("unit_of_measure"), max_length=50),
        closing_qty=_nullable_float(row.get("closing_qty")),
        par_level=_nullable_float(row.get("par_level")),
        reorder_point=_nullable_float(row.get("reorder_point")),
        days_of_cover=_nullable_float(row.get("days_of_cover")),
        vendor_name=_text(row.get("vendor_name"), max_length=200),
        lead_time_days=_nullable_int(row.get("lead_time_days")),
    )


def _inventory_item(row: pd.Series) -> InventoryItemHealth:
    return InventoryItemHealth(
        ledger_date=_required_date(row.get("ledger_date")),
        item_name=_text(row.get("item_name"), max_length=200) or "Unknown item",
        category=_text(row.get("category"), max_length=100),
        unit_of_measure=_text(row.get("unit_of_measure"), max_length=50),
        closing_qty=_nullable_float(row.get("closing_qty")),
        par_level=_nullable_float(row.get("par_level")),
        reorder_point=_nullable_float(row.get("reorder_point")),
        days_of_cover=_nullable_float(row.get("days_of_cover")),
        reorder_alert=_bool(row.get("reorder_alert")),
        vendor_name=_text(row.get("vendor_name"), max_length=200),
    )


def _sanitize_coverage(raw: dict[str, Any]) -> list[DatasetCoverage]:
    rows = []
    for key, value in list(raw.items())[:MAX_IMPORT_DATASETS]:
        label = _safe_label(key)
        max_date = _as_date(value)
        if label and max_date:
            rows.append(DatasetCoverage(dataset=label, max_date=max_date))
    return sorted(rows, key=lambda item: item.dataset)


def _sanitize_missing_days(raw: dict[str, Any]) -> list[MissingReportDays]:
    rows = []
    for key, value in list(raw.items())[:MAX_IMPORT_DATASETS]:
        label = _safe_label(key)
        if not label or not isinstance(value, list):
            continue
        valid_dates = [
            parsed for item in value if (parsed := _as_date(item)) is not None
        ]
        rows.append(
            MissingReportDays(
                report_type=label,
                missing_days=len(valid_dates),
                dates=valid_dates[:MAX_MISSING_DATES_PER_REPORT],
                dates_truncated=len(valid_dates) > MAX_MISSING_DATES_PER_REPORT,
            )
        )
    return sorted(rows, key=lambda item: (-item.missing_days, item.report_type))


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw or len(raw) > 1_000_000:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_label(value: Any) -> str | None:
    text = _text(value, max_length=64)
    return text if text and _SAFE_LABEL.fullmatch(text) else None


def _safe_import_source(value: Any) -> str:
    parsed = (_text(value, max_length=50) or "").lower()
    return parsed if parsed in {"imap", "local"} else "unknown"


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, bool) else False


def _float(value: Any, default: float = 0.0) -> float:
    parsed = _nullable_float(value)
    return default if parsed is None else parsed


def _nullable_float(value: Any) -> float | None:
    if _is_missing(value):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) else None


def _int(value: Any, default: int = 0) -> int:
    parsed = _nullable_int(value)
    return default if parsed is None else parsed


def _nullable_int(value: Any) -> int | None:
    if _is_missing(value):
        return None
    try:
        if isinstance(value, Decimal) and value != value.to_integral_value():
            return None
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed


def _bool(value: Any) -> bool:
    if _is_missing(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _text(value: Any, *, max_length: int) -> str | None:
    if _is_missing(value):
        return None
    parsed = str(value).strip()
    if not parsed:
        return None
    return parsed[:max_length]


def _as_date(value: Any) -> date | None:
    if _is_missing(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _required_date(value: Any) -> date:
    parsed = _as_date(value)
    if parsed is None:
        raise ValueError("Required date value is missing.")
    return parsed


def _as_datetime(value: Any) -> datetime | None:
    if _is_missing(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _required_datetime(value: Any) -> datetime:
    parsed = _as_datetime(value)
    if parsed is None:
        raise ValueError("Required datetime value is missing.")
    return parsed
