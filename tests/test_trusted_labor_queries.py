from datetime import date

import pandas as pd

from src.analytics import queries as q


def _capture_sql(monkeypatch, frames=None):
    captured = []
    iterator = iter(frames or [])

    def fake_q(sql: str, params=None):
        captured.append(sql)
        try:
            return next(iterator)
        except StopIteration:
            return pd.DataFrame()

    monkeypatch.setattr(q, "_q", fake_q)
    return captured


def test_get_daily_labor_uses_trusted_labor_scope(monkeypatch):
    captured = _capture_sql(monkeypatch)
    q.get_daily_labor(date(2026, 1, 1), date(2026, 1, 31))
    sql = captured[0]
    assert "JOIN import_logs" in sql
    assert "import_type = 'labor'" in sql
    assert "status = 'success'" in sql
    assert "labor_fixed_daily_costs" in sql


def test_get_prime_cost_data_uses_trusted_labor_scope(monkeypatch):
    captured = _capture_sql(monkeypatch)
    q.get_prime_cost_data(date(2026, 1, 1), date(2026, 1, 31))
    sql = captured[0]
    assert "JOIN import_logs" in sql
    assert "import_type = 'labor'" in sql
    assert "status = 'success'" in sql
    assert "labor_fixed_daily_costs" in sql


def test_get_splh_trend_uses_trusted_labor_scope(monkeypatch):
    captured = _capture_sql(monkeypatch)
    q.get_splh_trend(date(2026, 1, 1), date(2026, 1, 31))
    sql = captured[0]
    assert "JOIN import_logs" in sql
    assert "import_type = 'labor'" in sql
    assert "status = 'success'" in sql
    assert "labor_fixed_daily_costs" in sql


def test_get_payroll_employee_wages_uses_trusted_labor_scope(monkeypatch):
    captured = _capture_sql(monkeypatch)
    q.get_payroll_employee_wages(date(2026, 1, 1), date(2026, 1, 31))
    sql = captured[0]
    assert "JOIN import_logs" in sql
    assert "import_type = 'labor'" in sql
    assert "status = 'success'" in sql


def test_get_full_pnl_uses_trusted_labor_scope(monkeypatch):
    revenue = pd.DataFrame([{"net_sales": 1000, "gross_sales": 1200}])
    cogs = pd.DataFrame([{"total_cogs": 300}])
    labor = pd.DataFrame([{"labor_cost": 200, "labor_hours": 40}])
    fixed = pd.DataFrame([{"fixed_labor_cost": 100.0}])
    captured = _capture_sql(monkeypatch, [revenue, cogs, labor, fixed])

    monkeypatch.setattr(q, "get_expenses_by_type", lambda start, end: pd.DataFrame())
    monkeypatch.setattr(q, "get_distributions_total", lambda start, end: 0.0)

    q.get_full_pnl(date(2026, 1, 1), date(2026, 1, 31))
    labor_sql = captured[2]
    fixed_sql = captured[3]
    assert "JOIN import_logs" in labor_sql
    assert "import_type = 'labor'" in labor_sql
    assert "status = 'success'" in labor_sql
    assert "labor_fixed_daily_costs" in fixed_sql


def test_get_untrusted_labor_rows_detects_non_lightspeed_rows(monkeypatch):
    captured = _capture_sql(monkeypatch)
    q.get_untrusted_labor_rows(date(2026, 1, 1), date(2026, 1, 31))
    sql = captured[0]
    assert "LEFT JOIN import_logs il ON il.id = l.import_log_id" in sql
    assert "il.id IS NULL" in sql
    assert "il.import_type <> 'labor'" in sql
    assert "il.status <> 'success'" in sql


def test_get_untrusted_labor_details_detects_non_lightspeed_rows(monkeypatch):
    captured = _capture_sql(monkeypatch)
    q.get_untrusted_labor_details(date(2026, 1, 1), date(2026, 1, 31))
    sql = captured[0]
    assert "LEFT JOIN import_logs il ON il.id = l.import_log_id" in sql
    assert "il.id IS NULL" in sql
    assert "il.import_type <> 'labor'" in sql
    assert "il.status <> 'success'" in sql
