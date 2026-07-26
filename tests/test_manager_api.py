from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.api import services
from src.api.app import create_app


TOKEN = "manager-test-token-that-is-at-least-32-characters"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PERIOD_PARAMS = {"start": "2026-03-01", "end": "2026-03-02"}


@pytest.fixture(autouse=True)
def configured_token(monkeypatch):
    monkeypatch.setenv("MANAGER_API_TOKEN", TOKEN)
    monkeypatch.delenv("MANAGER_API_ALLOWED_ORIGINS", raising=False)


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def sales_range(monkeypatch):
    monkeypatch.setattr(
        services.queries,
        "get_sales_date_range",
        lambda: (date(2025, 12, 1), date(2026, 3, 31)),
    )


def _sales_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trading_day": pd.Timestamp("2026-03-01"),
                "gross_sales": Decimal("120.25"),
                "net_sales": Decimal("100.25"),
                "total_guests": 10,
                "total_checks": 8,
                "guest_avg": Decimal("10.025"),
                "check_avg": Decimal("12.53125"),
                "total_tips": Decimal("20.00"),
                "total_comps": Decimal("5.00"),
                "total_voids": Decimal("1.00"),
                "employee_name": "must not leak",
                "raw_filename": "sales-private.csv",
            },
            {
                "trading_day": date(2026, 3, 2),
                "gross_sales": Decimal("240.50"),
                "net_sales": Decimal("200.50"),
                "total_guests": 20,
                "total_checks": 16,
                "guest_avg": Decimal("10.025"),
                "check_avg": float("nan"),
                "total_tips": Decimal("40.00"),
                "total_comps": Decimal("10.00"),
                "total_voids": Decimal("2.00"),
            },
        ]
    )


def _pnl() -> dict:
    return {
        "net_sales": 300.75,
        "cogs": 75.0,
        "gross_profit": 225.75,
        "gross_margin_pct": 75.062,
        "labor_cost": 90.0,
        "labor_pct": 29.925,
        "prime_cost": 165.0,
        "prime_cost_pct": 54.862,
        "total_opex": 30.0,
        "opex_pct": 9.975,
        "net_operating_income": 105.75,
        "noi_pct": 35.162,
        "distributions": 99999,
        "retained_cash": -99999,
        "opex_by_type": [{"expense_type": "private-detail"}],
        "payroll_tax": 123,
    }


def _assert_no_forbidden_fields(payload):
    serialized = str(payload)
    for forbidden in (
        "employee_name",
        "raw_filename",
        "filename",
        "file_hash",
        "error_message",
        "staging_root",
        "run_staging_dir",
        "distributions",
        "retained_cash",
        "private-detail",
        "must not leak",
        "sales-private.csv",
    ):
        assert forbidden not in serialized


def _assert_provenance(payload, expected_query_ids):
    provenance = payload["provenance"]
    assert set(provenance) == {
        "generated_at",
        "data_as_of",
        "source_query_ids",
        "assumptions",
    }
    assert provenance["generated_at"]
    assert provenance["source_query_ids"] == expected_query_ids
    assert provenance["assumptions"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/overview",
        "/api/v1/daily-sales",
        "/api/v1/staffing-rush",
        "/api/v1/profitability",
        "/api/v1/inventory/health",
        "/api/v1/import-operations",
    ],
)
def test_every_v1_endpoint_requires_bearer_token(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_health_is_unauthenticated_and_discloses_no_data(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_overview_contract_is_explicit_and_redacted(client, monkeypatch, sales_range):
    monkeypatch.setattr(services.queries, "get_daily_sales", lambda start, end: _sales_frame())
    monkeypatch.setattr(
        services.queries,
        "get_full_pnl",
        lambda start, end, **kwargs: _pnl(),
    )
    monkeypatch.setattr(
        services.queries,
        "get_reorder_items",
        lambda: pd.DataFrame(
            [
                {
                    "ledger_date": date(2026, 3, 2),
                    "item_name": "Gin",
                    "category": "Spirits",
                    "unit_of_measure": "bottle",
                    "closing_qty": Decimal("2.5"),
                    "current_qty": Decimal("999"),
                    "par_level": Decimal("6"),
                    "reorder_point": Decimal("3"),
                    "days_of_cover": Decimal("1.5"),
                    "vendor_name": "Vendor",
                    "lead_time_days": 2,
                    "unit_cost": Decimal("25"),
                    "filename": "invoice.pdf",
                    "error_message": "private parser error",
                }
            ]
        ),
    )

    response = client.get("/api/v1/overview", params=PERIOD_PARAMS, headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "provenance",
        "period",
        "available_range",
        "kpis",
        "daily",
        "pnl",
        "reorder_alerts",
        "reorder_alerts_truncated",
    }
    assert set(payload["kpis"]) == {
        "net_sales",
        "avg_daily_sales",
        "avg_check",
        "total_checks",
        "trading_days",
        "prime_cost_pct",
        "labor_pct",
        "cogs_pct",
    }
    assert set(payload["pnl"]) == {
        "net_sales",
        "cogs",
        "cogs_pct",
        "gross_profit",
        "gross_margin_pct",
        "labor_cost",
        "labor_pct",
        "prime_cost",
        "prime_cost_pct",
        "total_opex",
        "opex_pct",
        "net_operating_income",
        "noi_pct",
    }
    assert payload["daily"][1]["check_avg"] is None
    assert payload["reorder_alerts"][0]["closing_qty"] == 2.5
    _assert_provenance(
        payload,
        [
            "analytics.get_sales_date_range",
            "analytics.get_daily_sales",
            "analytics.get_full_pnl",
            "analytics.get_reorder_items",
        ],
    )
    _assert_no_forbidden_fields(payload)


@pytest.mark.parametrize(
    ("preset", "expected_start"),
    [
        ("30d", "2026-03-02"),
        ("60d", "2026-01-31"),
        ("90d", "2026-01-01"),
        ("ytd", "2026-01-01"),
    ],
)
def test_overview_presets_are_bounded_and_pass_effective_period(
    client,
    monkeypatch,
    sales_range,
    preset,
    expected_start,
):
    calls = []

    def sales(start, end):
        calls.append((start, end))
        return pd.DataFrame()

    monkeypatch.setattr(services.queries, "get_daily_sales", sales)
    monkeypatch.setattr(
        services.queries,
        "get_full_pnl",
        lambda start, end, **kwargs: _pnl(),
    )
    monkeypatch.setattr(services.queries, "get_reorder_items", lambda: pd.DataFrame())

    response = client.get("/api/v1/overview", params={"preset": preset}, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["period"]["start"] == expected_start
    assert response.json()["period"]["end"] == "2026-03-31"
    assert calls == [(date.fromisoformat(expected_start), date(2026, 3, 31))]


def test_explicit_overview_start_takes_precedence_over_preset(
    client,
    monkeypatch,
    sales_range,
):
    monkeypatch.setattr(services.queries, "get_daily_sales", lambda start, end: pd.DataFrame())
    monkeypatch.setattr(
        services.queries,
        "get_full_pnl",
        lambda start, end, **kwargs: _pnl(),
    )
    monkeypatch.setattr(services.queries, "get_reorder_items", lambda: pd.DataFrame())

    response = client.get(
        "/api/v1/overview",
        params={"start": "2026-03-15", "preset": "ytd"},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json()["period"]["start"] == "2026-03-15"


def test_daily_sales_contract_serializes_decimal_date_and_nan(
    client,
    monkeypatch,
    sales_range,
):
    monkeypatch.setattr(services.queries, "get_daily_sales", lambda start, end: _sales_frame())

    response = client.get("/api/v1/daily-sales", params=PERIOD_PARAMS, headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"provenance", "period", "totals", "daily"}
    assert payload["totals"] == {
        "gross_sales": 360.75,
        "net_sales": 300.75,
        "total_guests": 30,
        "total_checks": 24,
        "total_tips": 60.0,
        "total_comps": 15.0,
        "total_voids": 3.0,
    }
    assert payload["daily"][0]["trading_day"] == "2026-03-01"
    assert payload["daily"][1]["check_avg"] is None
    _assert_provenance(
        payload,
        ["analytics.get_sales_date_range", "analytics.get_daily_sales"],
    )
    _assert_no_forbidden_fields(payload)


def test_staffing_rush_is_aggregate_only(client, monkeypatch, sales_range):
    monkeypatch.setattr(
        services.queries,
        "get_splh_trend",
        lambda start, end: pd.DataFrame(
            [
                {
                    "trading_day": date(2026, 3, 1),
                    "net_sales": Decimal("1000"),
                    "total_hours": Decimal("20"),
                    "total_labor_cost": Decimal("300"),
                    "splh": Decimal("50"),
                    "labor_pct": Decimal("30"),
                    "employee_name": "Private Employee",
                    "employee_id": "secret-id",
                    "role": "Bartender",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        services.queries,
        "get_hourly_heatmap_data",
        lambda start, end: pd.DataFrame(
            [
                {
                    "dow": 0,
                    "dow_name": "Sun",
                    "hour_of_day": 20,
                    "avg_net_sales": Decimal("500"),
                    "avg_checks": Decimal("30"),
                    "avg_guests": Decimal("35"),
                    "num_days": 4,
                }
            ]
        ),
    )

    response = client.get("/api/v1/staffing-rush", params=PERIOD_PARAMS, headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"provenance", "period", "kpis", "daily", "hourly"}
    assert payload["kpis"]["splh"] == 50.0
    assert payload["daily"][0]["total_labor_cost"] == 300.0
    _assert_provenance(
        payload,
        [
            "analytics.get_sales_date_range",
            "analytics.get_splh_trend",
            "analytics.get_hourly_heatmap_data",
        ],
    )
    assert "Private Employee" not in str(payload)
    assert "secret-id" not in str(payload)
    assert "role" not in str(payload)


def test_profitability_omits_distributions_and_employee_payroll(
    client,
    monkeypatch,
    sales_range,
):
    monkeypatch.setattr(
        services.queries,
        "get_full_pnl",
        lambda start, end, **kwargs: _pnl(),
    )
    monkeypatch.setattr(
        services.queries,
        "get_category_profitability",
        lambda start, end: pd.DataFrame(
            [
                {
                    "category_name": "Cocktails",
                    "total_qty": Decimal("25"),
                    "net_revenue": Decimal("500"),
                    "total_cost": Decimal("100"),
                    "gross_profit": Decimal("400"),
                    "unique_items": 5,
                    "owner_distribution": 999,
                }
            ]
        ),
    )
    monkeypatch.setattr(
        services.queries,
        "get_cost_data_health",
        lambda start, end: {
            "total_items": 10,
            "items_with_cost": 8,
            "total_revenue": 1000,
            "revenue_with_cost": 900,
            "total_cogs": 200,
            "by_category": pd.DataFrame(
                [
                    {
                        "category_name": "Cocktails",
                        "total_items": 5,
                        "items_with_cost": 4,
                        "total_revenue": 500,
                        "revenue_with_cost": 450,
                        "employee_wage": 100,
                    }
                ]
            ),
        },
    )

    response = client.get("/api/v1/profitability", params=PERIOD_PARAMS, headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"provenance", "period", "pnl", "categories", "cost_health"}
    assert payload["categories"][0]["pour_cost_pct"] == 20.0
    assert payload["cost_health"]["revenue_coverage_pct"] == 90.0
    _assert_provenance(
        payload,
        [
            "analytics.get_sales_date_range",
            "analytics.get_full_pnl",
            "analytics.get_category_profitability",
            "analytics.get_cost_data_health",
        ],
    )
    _assert_no_forbidden_fields(payload)
    assert "employee_wage" not in str(payload)
    assert "owner_distribution" not in str(payload)


def test_inventory_health_uses_ledger_closing_qty_not_catalog_current_qty(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        services.queries,
        "get_ledger_current",
        lambda as_of: pd.DataFrame(
            [
                {
                    "ledger_date": date(2026, 3, 2),
                    "item_name": "Gin",
                    "category": "Spirits",
                    "unit_of_measure": "bottle",
                    "closing_qty": Decimal("2.5"),
                    "current_qty": Decimal("999"),
                    "par_level": Decimal("6"),
                    "reorder_point": Decimal("3"),
                    "days_of_cover": Decimal("1.5"),
                    "reorder_alert": True,
                    "vendor_name": "Vendor",
                }
            ]
        ),
    )

    response = client.get("/api/v1/inventory/health", headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "provenance",
        "requested_as_of",
        "data_as_of",
        "summary",
        "items",
        "truncated",
    }
    assert payload["items"][0]["closing_qty"] == 2.5
    assert "current_qty" not in str(payload)
    assert "999" not in str(payload)
    assert payload["summary"] == {
        "items_tracked": 1,
        "items_below_par": 1,
        "reorder_alerts": 1,
        "items_with_days_of_cover": 1,
    }
    _assert_provenance(payload, ["analytics.get_ledger_current"])


def test_import_operations_redacts_file_and_error_metadata(client, monkeypatch):
    snapshot = SimpleNamespace(
        source="imap",
        messages_fetched=4,
        csv_attachments_saved=7,
        lookback_days=7,
        generated_on=date(2026, 3, 2),
        created_at=datetime(2026, 3, 2, 12, 30),
        staging_root=r"C:\private\inbox",
        run_staging_dir=r"C:\private\inbox\run",
        coverage_max_dates_json='{"sales": "2026-03-01"}',
        missing_report_days_json='{"labor": ["2026-02-28", "bad-date"]}',
    )
    log = SimpleNamespace(
        imported_at=datetime(2026, 3, 2, 12, 0),
        import_type="sales",
        report_date_start=date(2026, 3, 1),
        report_date_end=date(2026, 3, 1),
        row_count=42,
        status="success",
        filename="private-sales.csv",
        file_hash="abc123",
        error_message="connection details",
    )
    monkeypatch.setattr(services, "load_import_rows", lambda limit: (snapshot, [log]))

    response = client.get("/api/v1/import-operations", headers=AUTH)
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "provenance",
        "latest_run",
        "coverage",
        "missing_reports",
        "recent_imports",
    }
    assert payload["coverage"] == [{"dataset": "sales", "max_date": "2026-03-01"}]
    assert payload["missing_reports"] == [
        {
            "report_type": "labor",
            "missing_days": 1,
            "dates": ["2026-02-28"],
            "dates_truncated": False,
        }
    ]
    assert set(payload["recent_imports"][0]) == {
        "imported_at",
        "import_type",
        "report_date_start",
        "report_date_end",
        "row_count",
        "status",
    }
    _assert_provenance(
        payload,
        ["operations.import_run_snapshots.latest", "operations.import_logs.recent"],
    )
    _assert_no_forbidden_fields(payload)
    assert "private-sales.csv" not in str(payload)
    assert "connection details" not in str(payload)


def test_input_ranges_and_limits_are_bounded(client, monkeypatch, sales_range):
    response = client.get(
        "/api/v1/daily-sales",
        params={"start": "2026-03-02", "end": "2026-03-01"},
        headers=AUTH,
    )
    assert response.status_code == 422

    response = client.get(
        "/api/v1/daily-sales",
        params={"start": "2025-01-01", "end": "2026-03-02"},
        headers=AUTH,
    )
    assert response.status_code == 422

    assert client.get("/api/v1/inventory/health?limit=501", headers=AUTH).status_code == 422
    assert client.get("/api/v1/import-operations?limit=101", headers=AUTH).status_code == 422
    assert client.get("/api/v1/overview?preset=all", headers=AUTH).status_code == 422


def test_missing_server_token_fails_closed(client, monkeypatch):
    monkeypatch.delenv("MANAGER_API_TOKEN")
    response = client.get("/api/v1/overview", headers=AUTH)
    assert response.status_code == 503


def test_database_errors_are_not_returned_to_callers(client, monkeypatch):
    monkeypatch.setattr(
        services.queries,
        "get_sales_date_range",
        lambda: (_ for _ in ()).throw(RuntimeError("postgresql://user:secret@host/db")),
    )
    response = client.get("/api/v1/overview", headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {"detail": "Manager data is temporarily unavailable."}
    assert "secret" not in response.text


def test_manager_routes_are_get_only(client):
    response = client.post("/api/v1/overview", headers=AUTH)
    assert response.status_code == 405
