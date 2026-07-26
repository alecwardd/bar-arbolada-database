"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

type JsonRecord = Record<string, unknown>;

type ApiState<T> =
  | { status: "loading"; data?: undefined; message?: undefined }
  | { status: "ready"; data: T; message?: undefined }
  | { status: "error"; data?: undefined; message: string };

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const decimal = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
});

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function asRows(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(asRecord) : [];
}

function asNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function asText(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function metricValue(
  metrics: JsonRecord,
  key: string,
  fallback: unknown = null,
): number | null {
  const raw = metrics[key];
  const record = asRecord(raw);
  return asNumber(record.value ?? raw ?? fallback);
}

function metricDelta(metrics: JsonRecord, key: string): number | null {
  return asNumber(asRecord(metrics[key]).delta);
}

function formatDate(value: unknown): string {
  if (typeof value !== "string") return "Not available";
  const parsed = new Date(`${value.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(parsed);
}

function formatMetric(
  value: number | null,
  format: "money" | "percent" | "number",
): string {
  if (value === null) return "—";
  if (format === "money") return money.format(value);
  if (format === "percent") return `${decimal.format(value)}%`;
  return decimal.format(value);
}

function Delta({ value, inverse = false }: { value: number | null; inverse?: boolean }) {
  if (value === null) return <span className="metric-delta neutral">No comparison</span>;
  const favorable = inverse ? value <= 0 : value >= 0;
  return (
    <span className={`metric-delta ${favorable ? "positive" : "negative"}`}>
      {value > 0 ? "+" : ""}
      {decimal.format(value)} vs prior
    </span>
  );
}

function KpiCard({
  label,
  value,
  delta,
  format,
  inverse,
}: {
  label: string;
  value: number | null;
  delta: number | null;
  format: "money" | "percent" | "number";
  inverse?: boolean;
}) {
  return (
    <article className="kpi-card">
      <span className="eyebrow">{label}</span>
      <strong className="kpi-value">{formatMetric(value, format)}</strong>
      <Delta value={delta} inverse={inverse} />
    </article>
  );
}

function RatioBar({
  label,
  value,
  target,
  tone = "blue",
}: {
  label: string;
  value: number | null;
  target: number;
  tone?: "blue" | "teal" | "yellow";
}) {
  const width = Math.max(0, Math.min(100, value ?? 0));
  return (
    <div className="ratio">
      <div className="ratio-label">
        <span>{label}</span>
        <span className="num">{value === null ? "—" : `${decimal.format(value)}%`}</span>
      </div>
      <div className="ratio-track" aria-hidden="true">
        <span className={`ratio-fill ${tone}`} style={{ width: `${width}%` }} />
        <span className="ratio-target" style={{ left: `${Math.min(target, 100)}%` }} />
      </div>
      <span className="ratio-caption">Reference marker {target}%</span>
    </div>
  );
}

async function loadJson(path: string): Promise<JsonRecord> {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { accept: "application/json" },
    cache: "no-store",
  });
  const body = (await response.json().catch(() => ({}))) as JsonRecord;
  if (!response.ok) {
    throw new Error(asText(body.message ?? body.detail, "Live data is unavailable."));
  }
  return body;
}

export function ManagerDashboard() {
  const [overview, setOverview] = useState<ApiState<JsonRecord>>({ status: "loading" });
  const [imports, setImports] = useState<ApiState<JsonRecord>>({ status: "loading" });
  const [refreshing, setRefreshing] = useState(false);
  const [selectedPeriod, setSelectedPeriod] = useState("Last 30 Days");

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const preset = {
      "Last 30 Days": "30d",
      "Last 60 Days": "60d",
      "Last 90 Days": "90d",
      "Year to Date": "ytd",
    }[selectedPeriod] ?? "30d";
    const [overviewResult, importResult] = await Promise.allSettled([
      loadJson(`/api/manager/overview?preset=${preset}`),
      loadJson("/api/manager/import-operations"),
    ]);

    setOverview(
      overviewResult.status === "fulfilled"
        ? { status: "ready", data: overviewResult.value }
        : { status: "error", message: overviewResult.reason?.message ?? "Live data is unavailable." },
    );
    setImports(
      importResult.status === "fulfilled"
        ? { status: "ready", data: importResult.value }
        : { status: "error", message: importResult.reason?.message ?? "Import health is unavailable." },
    );
    setRefreshing(false);
  }, [selectedPeriod]);

  useEffect(() => {
    const refreshTimer = window.setTimeout(() => {
      void refresh();
    }, 0);
    return () => window.clearTimeout(refreshTimer);
  }, [refresh]);

  const data = overview.status === "ready" ? overview.data : {};
  const metrics = asRecord(data.kpis ?? data.metrics);
  const pnl = asRecord(data.pnl);
  const period = asRecord(data.period);
  const availableRange = asRecord(data.available_range);
  const daily = asRows(data.daily ?? data.sales_trend);
  const alerts = asRows(data.reorder_alerts ?? data.inventory_alerts);
  const importData = imports.status === "ready" ? imports.data : {};
  const snapshot = asRecord(importData.latest_run ?? importData.snapshot ?? importData);
  const importLogs = asRows(importData.recent_imports ?? importData.logs);

  const values = useMemo(() => {
    const netSales = metricValue(metrics, "net_sales");
    return {
      netSales,
      avgDaily:
        metricValue(metrics, "avg_daily_sales") ?? metricValue(metrics, "avg_daily"),
      avgCheck: metricValue(metrics, "avg_check"),
      primeCost:
        metricValue(metrics, "prime_cost_pct") ?? asNumber(pnl.prime_cost_pct),
      labor: metricValue(metrics, "labor_pct") ?? asNumber(pnl.labor_pct),
      cogs:
        metricValue(metrics, "cogs_pct") ??
        (() => {
          const cogs = asNumber(pnl.cogs);
          const sales = asNumber(pnl.net_sales) ?? netSales;
          return cogs !== null && sales ? (cogs / sales) * 100 : null;
        })(),
    };
  }, [metrics, pnl]);

  const chartRows = daily.slice(-30);
  const maxDaily = Math.max(
    1,
    ...chartRows.map((row) => asNumber(row.net_sales) ?? 0),
  );
  const movingAveragePoints = chartRows
    .map((_, index) => {
      const windowRows = chartRows.slice(Math.max(0, index - 6), index + 1);
      const average =
        windowRows.reduce((sum, row) => sum + (asNumber(row.net_sales) ?? 0), 0) /
        windowRows.length;
      const x = chartRows.length === 1 ? 500 : (index / (chartRows.length - 1)) * 1000;
      const y = 210 - (average / maxDaily) * 210;
      return `${x.toFixed(1)},${Math.max(0, y).toFixed(1)}`;
    })
    .join(" ");

  const latestImport = asText(
    snapshot.created_at ?? snapshot.generated_on,
    "No snapshot",
  );
  const coverageRows = asRows(importData.coverage);
  const coverage = asRecord(snapshot.coverage_max_dates);
  const missingRows = asRows(importData.missing_reports);
  const missing = asRecord(snapshot.missing_report_days);
  const missingCount = missingRows.length
    ? missingRows.reduce((sum, row) => sum + (asNumber(row.missing_days) ?? 0), 0)
    : Object.values(missing).reduce((sum, value) => {
        return sum + (Array.isArray(value) ? value.length : 0);
      }, 0);
  const rangeStart = availableRange.start ?? availableRange.min_date;
  const rangeEnd = availableRange.end ?? availableRange.max_date;

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Dashboard navigation">
        <a className="brand" href="#pulse" aria-label="Bar Arbolada operations pulse">
          <span>
            <strong>Bar Arbolada</strong>
            <small>Analytics</small>
          </span>
        </a>

        <div className="period-control" aria-label="Reporting period">
          <strong>Period</strong>
          {["Last 30 Days", "Last 60 Days", "Last 90 Days", "Year to Date"].map((label) => (
            <button
              type="button"
              className={selectedPeriod === label ? "active" : ""}
              aria-pressed={selectedPeriod === label}
              key={label}
              onClick={() => setSelectedPeriod(label)}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="sidebar-range">
          <span>Data range</span>
          <strong>
            {formatDate(rangeStart)} to {formatDate(rangeEnd)}
          </strong>
        </div>

        <div className="sidebar-status">
          <span className={`status-dot ${overview.status === "ready" ? "success" : "warning"}`} />
          <div>
            <strong>{overview.status === "ready" ? "Live data" : "Connection pending"}</strong>
            <small>
              {overview.status === "ready"
                ? `Through ${formatDate(rangeEnd)}`
                : "Private API boundary"}
            </small>
          </div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <h1>Bar Arbolada</h1>
            <p className="page-subtitle">Executive Dashboard</p>
            <span className="data-caption">Data through {formatDate(rangeEnd)}</span>
          </div>
          <div className="topbar-actions">
            <span className="release-badge">PRIVATE MANAGER VIEW · READ ONLY</span>
            <button type="button" onClick={() => void refresh()} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh data"}
            </button>
          </div>
        </header>

        {overview.status === "error" ? (
          <section className="connection-banner" role="status">
            <span className="status-dot warning" />
            <div>
              <strong>The manager site is ready; the live data connection is not configured yet.</strong>
              <p>{overview.message} No production data is cached in this site.</p>
            </div>
          </section>
        ) : null}

        <section id="pulse" className="section">
          <div className="section-heading">
            <div>
              <h2>Operating pulse</h2>
              <span className="period-label">
                {formatDate(period.start)} — {formatDate(period.end)}
              </span>
            </div>
            <span className="data-through">
              {overview.status === "loading" ? "Loading live figures…" : `${daily.length} trading days`}
            </span>
          </div>

          <div className="kpi-grid">
            <KpiCard label="Net sales" value={values.netSales} delta={metricDelta(metrics, "net_sales")} format="money" />
            <KpiCard label="Average / day" value={values.avgDaily} delta={metricDelta(metrics, "avg_daily")} format="money" />
            <KpiCard label="Average check" value={values.avgCheck} delta={metricDelta(metrics, "avg_check")} format="money" />
            <KpiCard label="Prime cost" value={values.primeCost} delta={metricDelta(metrics, "prime_cost_pct")} format="percent" inverse />
            <KpiCard label="Labor" value={values.labor} delta={metricDelta(metrics, "labor_pct")} format="percent" inverse />
            <KpiCard label="COGS" value={values.cogs} delta={metricDelta(metrics, "cogs_pct")} format="percent" inverse />
          </div>
        </section>

        <section id="sales" className="section split-grid">
          <article className="panel chart-panel">
            <div className="panel-heading">
              <div>
                <h2>Sales Trend</h2>
              </div>
              <div className="chart-legends" aria-label="Chart legend">
                <span className="legend"><i /> Daily Sales</span>
                <span className="legend average"><i /> 7-day Average</span>
              </div>
            </div>
            {daily.length ? (
              <div
                className="bar-chart"
                role="img"
                aria-label="Daily net sales with a coral seven-day moving average"
              >
                <svg
                  className="sales-average-overlay"
                  viewBox="0 0 1000 210"
                  preserveAspectRatio="none"
                  aria-hidden="true"
                >
                  <polyline points={movingAveragePoints} />
                </svg>
                {chartRows.map((row, index) => {
                  const value = asNumber(row.net_sales) ?? 0;
                  const day = asText(row.trading_day, `Day ${index + 1}`);
                  return (
                    <div className="bar-column" key={`${day}-${index}`}>
                      <span className="bar-value">{money.format(value)}</span>
                      <span
                        className="bar"
                        style={{ height: `${Math.max(3, (value / maxDaily) * 100)}%` }}
                      />
                      <span className="bar-day">{day.slice(5)}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="empty-state">Daily figures will appear when the private API is connected.</div>
            )}
          </article>

          <article id="cost" className="panel">
            <div className="panel-heading">
              <div>
                <h2>P&amp;L Snapshot</h2>
              </div>
            </div>
            <div className="ratio-stack">
              <RatioBar label="Prime cost" value={values.primeCost} target={60} tone="blue" />
              <RatioBar label="Labor" value={values.labor} target={30} tone="teal" />
              <RatioBar label="COGS" value={values.cogs} target={30} tone="yellow" />
            </div>
            <p className="panel-note">
              Ratios are aggregate operational signals. Employee-level pay and owner distributions are intentionally excluded.
            </p>
          </article>
        </section>

        <section className="section lower-grid">
          <article id="inventory" className="panel">
            <div className="panel-heading">
              <div>
                <h2>Inventory Alerts</h2>
                <span className="panel-subtitle">Ledger-backed quantities</span>
              </div>
              <span className={`count-badge ${alerts.length ? "warning" : "success"}`}>
                {alerts.length} flagged
              </span>
            </div>
            {alerts.length ? (
              <div className="table-wrap">
                <table className="data">
                  <thead>
                    <tr>
                      <th>Item</th>
                      <th>Category</th>
                      <th className="num">On hand</th>
                      <th className="num">Days cover</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alerts.slice(0, 8).map((row, index) => (
                      <tr key={`${asText(row.item_name)}-${index}`}>
                        <td>{asText(row.item_name)}</td>
                        <td>{asText(row.category)}</td>
                        <td className="num">{decimal.format(asNumber(row.closing_qty) ?? 0)}</td>
                        <td className="num">{formatMetric(asNumber(row.days_of_cover), "number")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state">
                {overview.status === "ready" ? "No reorder alerts in the current ledger." : "Ledger alerts will appear after connection."}
              </div>
            )}
          </article>

          <article id="imports" className="panel">
            <div className="panel-heading">
              <div>
                <h2>Import Operations</h2>
                <span className="panel-subtitle">Coverage and missing-day checks</span>
              </div>
              <span className={`status-label ${missingCount ? "warning" : "success"}`}>
                <i />
                {missingCount ? `${missingCount} gaps` : "Healthy"}
              </span>
            </div>
            <dl className="health-list">
              <div>
                <dt>Latest snapshot</dt>
                <dd>{formatDate(latestImport)}</dd>
              </div>
              <div>
                <dt>Messages fetched</dt>
                <dd className="num">{formatMetric(asNumber(snapshot.messages_fetched), "number")}</dd>
              </div>
              <div>
                <dt>CSV attachments</dt>
                <dd className="num">{formatMetric(asNumber(snapshot.csv_attachments_saved), "number")}</dd>
              </div>
              <div>
                <dt>Coverage datasets</dt>
                <dd className="num">{coverageRows.length || Object.keys(coverage).length || "—"}</dd>
              </div>
              <div>
                <dt>Recent import events</dt>
                <dd className="num">{importLogs.length || "—"}</dd>
              </div>
            </dl>
            {imports.status === "error" ? <p className="panel-note">{imports.message}</p> : null}
          </article>
        </section>

        <footer>
          <span>Bar Arbolada Analytics</span>
          <span>Private manager surface · read-only release</span>
        </footer>
      </main>
    </div>
  );
}
