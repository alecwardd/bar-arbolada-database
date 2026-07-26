from __future__ import annotations

import inspect
import json
from datetime import date

import pandas as pd
import pytest

from src.api import read_model, services


EXPECTED_PRIVILEGES = {
    "import_logs": {
        "id",
        "import_type",
        "imported_at",
        "report_date_start",
        "report_date_end",
        "row_count",
        "status",
    },
    "import_run_snapshots": {
        "id",
        "source",
        "messages_fetched",
        "csv_attachments_saved",
        "lookback_days",
        "coverage_max_dates_json",
        "missing_report_days_json",
        "generated_on",
        "created_at",
    },
    "inv_daily_ledger": {
        "inv_item_id",
        "ledger_date",
        "closing_qty",
        "days_of_cover",
        "reorder_alert",
    },
    "inv_items": {
        "id",
        "name",
        "category",
        "unit_of_measure",
        "par_level",
        "reorder_point",
        "primary_vendor_id",
        "status",
    },
    "inv_vendors": {"id", "name", "lead_time_days"},
    "labor_fixed_daily_costs": {
        "daily_amount",
        "effective_start_date",
        "effective_end_date",
        "include_in_projections",
    },
    "op_expenses": {"expense_date", "amount"},
    "payroll_burden_settings": {
        "payroll_tax_rate",
        "payroll_fee_monthly",
        "effective_start_date",
        "effective_end_date",
    },
    "pos_daily_sales": {
        "trading_day",
        "gross_sales",
        "net_sales",
        "total_guests",
        "total_checks",
        "guest_avg",
        "check_avg",
        "total_tips",
        "total_comps",
        "total_voids",
    },
    "pos_hourly_sales": {
        "trading_day",
        "hour_of_day",
        "net_sales",
        "check_count",
        "guest_count",
    },
    "pos_labor": {
        "import_log_id",
        "trading_day",
        "reg_hours",
        "ot_hours",
        "total_pay",
    },
    "pos_product_mix": {
        "report_start_date",
        "report_end_date",
        "entry_type",
        "item_name",
        "qty_sold",
        "cost",
        "net_sales",
        "gross_profit",
        "category_name",
    },
}


FORBIDDEN_TABLES = {
    "employees",
    "owner_distributions",
    "payroll_employee_settings",
    "payroll_cash_tips",
    "inv_invoices",
    "inv_invoice_lines",
    "pos_checks",
    "pos_payments",
}


FORBIDDEN_COLUMNS = {
    "employee_id",
    "first_name",
    "last_name",
    "role",
    "pay_per_hour",
    "blended_pay_per_hour",
    "filename",
    "file_hash",
    "error_message",
    "staging_root",
    "run_staging_dir",
    "source_file",
    "recipient",
    "current_qty",
}


def test_services_use_manager_read_model_not_broad_analytics_queries():
    assert services.queries is read_model
    source = inspect.getsource(services)
    assert "src.analytics" not in source


def test_privilege_allowlist_is_exact_deterministic_and_json_serializable():
    actual = {
        table_name: set(columns)
        for table_name, columns in read_model.MANAGER_READ_PRIVILEGES.items()
    }
    assert actual == EXPECTED_PRIVILEGES

    exported = read_model.export_privilege_allowlist()
    serialized = json.dumps(exported, sort_keys=True)
    assert json.loads(serialized) == exported
    assert exported["version"] == 1
    assert exported["schema"] == "public"
    assert [row["table"] for row in exported["tables"]] == sorted(EXPECTED_PRIVILEGES)


def test_read_model_has_no_sensitive_table_or_column_privileges():
    privileges = read_model.MANAGER_READ_PRIVILEGES
    assert FORBIDDEN_TABLES.isdisjoint(privileges)
    granted_columns = {column for columns in privileges.values() for column in columns}
    assert FORBIDDEN_COLUMNS.isdisjoint(granted_columns)


def test_every_read_statement_avoids_broad_or_sensitive_selects():
    sql = "\n".join(read_model.READ_MODEL_SQL.values()).lower()
    assert "select *" not in sql
    assert "pl.*" not in sql
    assert "owner_distributions" not in sql
    assert "retained_cash" not in sql
    for identifier in (
        "employee_id",
        "first_name",
        "last_name",
        "pay_per_hour",
        "blended_pay_per_hour",
        "filename",
        "file_hash",
        "error_message",
        "staging_root",
        "run_staging_dir",
        "source_file",
        "current_qty",
    ):
        assert identifier not in sql


def test_trusted_labor_queries_are_aggregate_only_and_success_scoped():
    for sql in (read_model.STAFFING_RUSH_SQL, read_model.PNL_SQL):
        normalized = " ".join(sql.lower().split())
        assert "sum(coalesce(pl.total_pay, 0))" in normalized
        assert "il.import_type = 'labor'" in normalized
        assert "il.status = 'success'" in normalized
        assert "group by pl.trading_day" in normalized
        assert "employee_id" not in normalized
        assert "first_name" not in normalized
        assert "last_name" not in normalized
        assert "role" not in normalized


def test_column_grants_cover_only_manifest_and_validate_role():
    grants = read_model.render_column_grants("bar_arbolada_manager_read")
    assert grants.startswith(
        "GRANT USAGE ON SCHEMA public TO bar_arbolada_manager_read;"
    )
    assert grants.count("GRANT SELECT") == len(EXPECTED_PRIVILEGES)
    assert "GRANT SELECT ON TABLE" not in grants
    assert "owner_distributions" not in grants
    with pytest.raises(ValueError):
        read_model.render_column_grants("manager; DROP TABLE pos_daily_sales")


def test_manager_pnl_never_supports_distribution_access(monkeypatch):
    monkeypatch.setattr(
        read_model,
        "_query_frame",
        lambda sql, params=None: pd.DataFrame(
            [
                {
                    "net_sales": 1000,
                    "total_cogs": 200,
                    "total_labor_cost": 300,
                    "total_opex": 100,
                }
            ]
        ),
    )
    result = read_model.get_full_pnl(
        date(2026, 3, 1),
        date(2026, 3, 31),
        include_distributions=False,
    )
    assert result == {
        "net_sales": 1000.0,
        "cogs": 200.0,
        "gross_profit": 800.0,
        "gross_margin_pct": 80.0,
        "labor_cost": 300.0,
        "labor_pct": 30.0,
        "prime_cost": 500.0,
        "prime_cost_pct": 50.0,
        "total_opex": 100.0,
        "opex_pct": 10.0,
        "net_operating_income": 400.0,
        "noi_pct": 40.0,
    }
    with pytest.raises(ValueError):
        read_model.get_full_pnl(
            date(2026, 3, 1),
            date(2026, 3, 31),
            include_distributions=True,
        )
