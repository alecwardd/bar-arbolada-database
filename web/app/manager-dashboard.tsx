"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { FeedbackDialog } from "./components/feedback-dialog";
import { PlotlyChart } from "./components/plotly-chart";

type JsonRecord = Record<string, unknown>;
type ManagerRole = "viewer" | "manager" | "owner";

type ApiState<T> =
  | { status: "loading"; data?: undefined; message?: undefined }
  | { status: "ready"; data: T; message?: undefined }
  | { status: "error"; data?: undefined; message: string };

const FOREST = "#2d6a4f";
const FOREST_SOFT = "rgba(45, 106, 79, 0.72)";
const CORAL = "#e76f51";
const DANGER = "#ef4444";
const INFO = "#3b82f6";
const MUTED = "#94a3b8";

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const moneyExact = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 2,
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
  format: "money" | "percent" | "number" | "moneyExact",
): string {
  if (value === null) return "—";
  if (format === "money") return money.format(value);
  if (format === "moneyExact") return moneyExact.format(value);
  if (format === "percent") return `${decimal.format(value)}%`;
  return decimal.format(value);
}

function Delta({
  value,
  inverse = false,
  format = "money",
}: {
  value: number | null;
  inverse?: boolean;
  format?: "money" | "percent" | "number" | "moneyExact";
}) {
  if (value === null) {
    return <span className="metric-delta neutral">No prior comparison</span>;
  }
  const favorable = inverse ? value <= 0 : value >= 0;
  const prefix = value > 0 ? "+" : "";
  const label =
    format === "percent"
      ? `${prefix}${decimal.format(value)} pp vs prior`
      : `${prefix}${formatMetric(value, format)} vs prior`;
  return (
    <span className={`metric-delta ${favorable ? "positive" : "negative"}`}>
      {label}
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
  format: "money" | "percent" | "number" | "moneyExact";
  inverse?: boolean;
}) {
  return (
    <article className="kpi-card">
      <span className="eyebrow">{label}</span>
      <strong className="kpi-value">{formatMetric(value, format)}</strong>
      <Delta value={delta} inverse={inverse} format={format} />
    </article>
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
  const [profitability, setProfitability] = useState<ApiState<JsonRecord>>({
    status: "loading",
  });
  const [staffing, setStaffing] = useState<ApiState<JsonRecord>>({ status: "loading" });
  const [role, setRole] = useState<ManagerRole>("viewer");
  const [refreshing, setRefreshing] = useState(false);
  const [selectedPeriod, setSelectedPeriod] = useState("Last 30 Days");
  const [feedbackOpen, setFeedbackOpen] = useState(false);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    const preset = {
      "Last 30 Days": "30d",
      "Last 60 Days": "60d",
      "Last 90 Days": "90d",
      "Year to Date": "ytd",
    }[selectedPeriod] ?? "30d";

    const [overviewResult, meResult] = await Promise.allSettled([
      loadJson(`/api/manager/overview?preset=${preset}`),
      loadJson("/api/me"),
    ]);

    if (meResult.status === "fulfilled") {
      const nextRole = asText(meResult.value.role, "viewer");
      if (nextRole === "owner" || nextRole === "manager" || nextRole === "viewer") {
        setRole(nextRole);
      }
    }

    if (overviewResult.status !== "fulfilled") {
      setOverview({
        status: "error",
        message: overviewResult.reason?.message ?? "Live data is unavailable.",
      });
      setProfitability({ status: "error", message: "Waiting on overview." });
      setStaffing({ status: "error", message: "Waiting on overview." });
      setRefreshing(false);
      return;
    }

    const overviewData = overviewResult.value;
    setOverview({ status: "ready", data: overviewData });
    const period = asRecord(overviewData.period);
    const start = asText(period.start, "");
    const end = asText(period.end, "");
    const rangeQuery =
      start && end
        ? `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`
        : "";

    const [profitResult, staffResult] = await Promise.allSettled([
      loadJson(`/api/manager/profitability?${rangeQuery}`),
      loadJson(`/api/manager/staffing-rush?${rangeQuery}`),
    ]);

    setProfitability(
      profitResult.status === "fulfilled"
        ? { status: "ready", data: profitResult.value }
        : {
            status: "error",
            message: profitResult.reason?.message ?? "Profitability is unavailable.",
          },
    );
    setStaffing(
      staffResult.status === "fulfilled"
        ? { status: "ready", data: staffResult.value }
        : {
            status: "error",
            message: staffResult.reason?.message ?? "Staffing is unavailable.",
          },
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
  const pnl = asRecord(
    profitability.status === "ready" ? profitability.data.pnl : data.pnl,
  );
  const period = asRecord(data.period);
  const availableRange = asRecord(data.available_range);
  const daily = asRows(data.daily ?? data.sales_trend);
  const alerts = asRows(data.reorder_alerts ?? data.inventory_alerts);
  const categories = asRows(
    profitability.status === "ready" ? profitability.data.categories : [],
  ).slice(0, 6);
  const costHealth = asRecord(
    profitability.status === "ready" ? profitability.data.cost_health : {},
  );
  const staffKpis = asRecord(staffing.status === "ready" ? staffing.data.kpis : {});
  const showOps = role === "owner" || role === "manager";

  const values = useMemo(
    () => ({
      netSales: asNumber(metrics.net_sales),
      avgDaily: asNumber(metrics.avg_daily_sales),
      avgCheck: asNumber(metrics.avg_check),
      primeCost: asNumber(metrics.prime_cost_pct) ?? asNumber(pnl.prime_cost_pct),
      labor: asNumber(metrics.labor_pct) ?? asNumber(pnl.labor_pct),
      cogs: asNumber(metrics.cogs_pct) ?? asNumber(pnl.cogs_pct),
      netSalesDelta: asNumber(metrics.net_sales_delta),
      avgDailyDelta: asNumber(metrics.avg_daily_sales_delta),
      avgCheckDelta: asNumber(metrics.avg_check_delta),
      primeDelta: asNumber(metrics.prime_cost_pct_delta),
      laborDelta: asNumber(metrics.labor_pct_delta),
      cogsDelta: asNumber(metrics.cogs_pct_delta),
    }),
    [metrics, pnl],
  );

  const salesChartData = useMemo(() => {
    const days = daily.map((row) => asText(row.trading_day));
    const sales = daily.map((row) => asNumber(row.net_sales) ?? 0);
    const rolling = sales.map((_, index) => {
      const window = sales.slice(Math.max(0, index - 6), index + 1);
      return window.reduce((sum, value) => sum + value, 0) / window.length;
    });
    return [
      {
        type: "bar",
        name: "Daily Sales",
        x: days,
        y: sales,
        marker: { color: FOREST_SOFT },
        hovertemplate: "<b>%{x}</b><br>Net sales: %{y:$,.0f}<extra></extra>",
      },
      {
        type: "scatter",
        mode: "lines",
        name: "7-day average",
        x: days,
        y: rolling,
        line: { color: CORAL, width: 3, shape: "spline" },
        hovertemplate: "<b>%{x}</b><br>7-day avg: %{y:$,.0f}<extra></extra>",
      },
    ];
  }, [daily]);

  const salesLayout = useMemo(
    () => ({
      height: 360,
      legend: {
        orientation: "h",
        yanchor: "bottom",
        y: 1.08,
        x: 0,
      },
      xaxis: { showgrid: false, tickformat: "%b %d" },
      yaxis: {
        title: "Net sales",
        tickprefix: "$",
        gridcolor: "#e9ecef",
        zeroline: false,
      },
      bargap: 0.18,
      hovermode: "x unified",
    }),
    [],
  );

  const pnlChartData = useMemo(() => {
    const rows = [
      { label: "Sales", value: asNumber(pnl.net_sales) ?? 0, color: FOREST },
      { label: "COGS", value: -(asNumber(pnl.cogs) ?? 0), color: DANGER },
      { label: "Labor", value: -(asNumber(pnl.labor_cost) ?? 0), color: DANGER },
      { label: "OpEx", value: -(asNumber(pnl.total_opex) ?? 0), color: DANGER },
      {
        label: "NOI",
        value: asNumber(pnl.net_operating_income) ?? 0,
        color: INFO,
      },
    ];
    return [
      {
        type: "bar",
        x: rows.map((row) => row.label),
        y: rows.map((row) => row.value),
        marker: { color: rows.map((row) => row.color) },
        hovertemplate: "<b>%{x}</b><br>%{y:$,.0f}<extra></extra>",
      },
    ];
  }, [pnl]);

  const pnlLayout = useMemo(
    () => ({
      height: 300,
      showlegend: false,
      yaxis: {
        tickprefix: "$",
        gridcolor: "#e9ecef",
        zeroline: true,
        zerolinecolor: MUTED,
      },
      xaxis: { showgrid: false },
    }),
    [],
  );

  const categoryChartData = useMemo(() => {
    return [
      {
        type: "bar",
        orientation: "h",
        y: categories.map((row) => asText(row.category_name)).reverse(),
        x: categories.map((row) => asNumber(row.net_revenue) ?? 0).reverse(),
        marker: { color: FOREST },
        hovertemplate: "<b>%{y}</b><br>Revenue: %{x:$,.0f}<extra></extra>",
      },
    ];
  }, [categories]);

  const categoryLayout = useMemo(
    () => ({
      height: 300,
      showlegend: false,
      margin: { l: 110, r: 16, t: 10, b: 40 },
      xaxis: {
        tickprefix: "$",
        gridcolor: "#e9ecef",
        zeroline: false,
      },
      yaxis: { showgrid: false },
    }),
    [],
  );

  const rangeStart = availableRange.start ?? availableRange.min_date;
  const rangeEnd = availableRange.end ?? availableRange.max_date;

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Dashboard navigation">
        <a className="brand" href="#pulse" aria-label="Bar Arbolada operating pulse">
          <span className="brand-mark" aria-hidden="true">
            BA
          </span>
          <span>
            <strong>Bar Arbolada</strong>
            <small>Partner Analytics</small>
          </span>
        </a>

        <div className="period-control" aria-label="Reporting period">
          <strong>Period</strong>
          {["Last 30 Days", "Last 60 Days", "Last 90 Days", "Year to Date"].map(
            (label) => (
              <button
                type="button"
                className={selectedPeriod === label ? "active" : ""}
                aria-pressed={selectedPeriod === label}
                key={label}
                onClick={() => setSelectedPeriod(label)}
              >
                {label}
              </button>
            ),
          )}
        </div>

        <nav className="sidebar-nav" aria-label="Sections">
          <a href="#pulse">Operating pulse</a>
          <a href="#sales">Sales trend</a>
          <a href="#cost">P&amp;L</a>
          <a href="#categories">Categories</a>
          <a href="#staffing">Staffing</a>
          <a href="#inventory">Inventory</a>
        </nav>

        <div className="sidebar-range">
          <span>Available history</span>
          <strong>
            {formatDate(rangeStart)} to {formatDate(rangeEnd)}
          </strong>
        </div>

        <div className="sidebar-status">
          <span
            className={`status-dot ${overview.status === "ready" ? "success" : "warning"}`}
          />
          <div>
            <strong>
              {overview.status === "ready" ? "Live operating data" : "Connecting…"}
            </strong>
            <small>
              {overview.status === "ready"
                ? `Through ${formatDate(rangeEnd)}`
                : "Private read-only connection"}
            </small>
          </div>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <h1>Bar Arbolada</h1>
            <p className="page-subtitle">
              A private, read-only operating pulse for partners. Live numbers from
              the venue — nothing here can change payroll, inventory, or books.
            </p>
            <div className="header-meta">
              <span className="release-badge">Private · Read-only</span>
              <span className="data-caption">
                Viewing {formatDate(period.start)} — {formatDate(period.end)}
              </span>
            </div>
          </div>
          <div className="topbar-actions">
            <button type="button" className="secondary-button" onClick={() => setFeedbackOpen(true)}>
              Send feedback
            </button>
            <button type="button" onClick={() => void refresh()} disabled={refreshing}>
              {refreshing ? "Refreshing…" : "Refresh"}
            </button>
          </div>
        </header>

        {overview.status === "error" ? (
          <section className="connection-banner" role="status">
            <span className="status-dot warning" />
            <div>
              <strong>The page is ready, but live data is not connected yet.</strong>
              <p>{overview.message} No production figures are stored in this site.</p>
            </div>
          </section>
        ) : null}

        <section id="pulse" className="section">
          <div className="section-heading">
            <div>
              <h2>Operating pulse</h2>
              <p className="section-copy">
                Sales and cost ratios for this period, compared with the previous window.
              </p>
            </div>
            <span className="data-through">
              {overview.status === "loading"
                ? "Loading live figures…"
                : `${daily.length} trading days`}
            </span>
          </div>

          <div className="kpi-groups">
            <div className="kpi-group">
              <p className="kpi-group-label">Sales</p>
              <div className="kpi-grid sales">
                <KpiCard
                  label="Net sales"
                  value={values.netSales}
                  delta={values.netSalesDelta}
                  format="money"
                />
                <KpiCard
                  label="Average / day"
                  value={values.avgDaily}
                  delta={values.avgDailyDelta}
                  format="money"
                />
                <KpiCard
                  label="Average check"
                  value={values.avgCheck}
                  delta={values.avgCheckDelta}
                  format="moneyExact"
                />
              </div>
            </div>
            <div className="kpi-group">
              <p className="kpi-group-label">Costs</p>
              <div className="kpi-grid costs">
                <KpiCard
                  label="Prime cost"
                  value={values.primeCost}
                  delta={values.primeDelta}
                  format="percent"
                  inverse
                />
                <KpiCard
                  label="Labor"
                  value={values.labor}
                  delta={values.laborDelta}
                  format="percent"
                  inverse
                />
                <KpiCard
                  label="COGS"
                  value={values.cogs}
                  delta={values.cogsDelta}
                  format="percent"
                  inverse
                />
              </div>
            </div>
          </div>
        </section>

        <section id="sales" className="section">
          <article className="panel chart-panel">
            <div className="panel-heading">
              <div>
                <h2>Sales trend</h2>
                <span className="panel-subtitle">
                  Daily sales with a seven-day average
                </span>
              </div>
            </div>
            {daily.length ? (
              <PlotlyChart
                data={salesChartData}
                layout={salesLayout}
                ariaLabel="Daily net sales with a coral seven-day moving average"
              />
            ) : (
              <div className="empty-state">
                Daily figures appear when the private API is connected.
              </div>
            )}
          </article>
        </section>

        <section id="cost" className="section split-grid">
          <article className="panel">
            <div className="panel-heading">
              <div>
                <h2>P&amp;L snapshot</h2>
                <span className="panel-subtitle">
                  Operating result — owner draws not included
                </span>
              </div>
            </div>
            {asNumber(pnl.net_sales) !== null ? (
              <>
                <PlotlyChart
                  data={pnlChartData}
                  layout={pnlLayout}
                  ariaLabel="P and L bars for sales, costs, and net operating income"
                />
                <dl className="stat-strip">
                  <div>
                    <dt>Gross margin</dt>
                    <dd>{formatMetric(asNumber(pnl.gross_margin_pct), "percent")}</dd>
                  </div>
                  <div>
                    <dt>Prime cost</dt>
                    <dd>{formatMetric(asNumber(pnl.prime_cost_pct), "percent")}</dd>
                  </div>
                  <div>
                    <dt>NOI margin</dt>
                    <dd>{formatMetric(asNumber(pnl.noi_pct), "percent")}</dd>
                  </div>
                </dl>
              </>
            ) : (
              <div className="empty-state">P&amp;L figures load with live data.</div>
            )}
          </article>

          <article id="categories" className="panel">
            <div className="panel-heading">
              <div>
                <h2>Category mix</h2>
                <span className="panel-subtitle">
                  Top revenue categories in this window
                </span>
              </div>
              <span className="count-badge success">
                {formatMetric(asNumber(costHealth.revenue_coverage_pct), "percent")}{" "}
                cost coverage
              </span>
            </div>
            {categories.length ? (
              <PlotlyChart
                data={categoryChartData}
                layout={categoryLayout}
                ariaLabel="Top revenue categories"
              />
            ) : (
              <div className="empty-state">
                {profitability.status === "error"
                  ? profitability.message
                  : "Category profitability appears after connection."}
              </div>
            )}
          </article>
        </section>

        <section className="section lower-grid">
          <article id="staffing" className="panel">
            <div className="panel-heading">
              <div>
                <h2>Staffing efficiency</h2>
                <span className="panel-subtitle">
                  No employee names or individual pay
                </span>
              </div>
            </div>
            {staffing.status === "ready" ? (
              <div className="staff-grid">
                <div>
                  <span className="eyebrow">Sales per labor hour</span>
                  <strong className="kpi-value">
                    {formatMetric(asNumber(staffKpis.splh), "moneyExact")}
                  </strong>
                </div>
                <div>
                  <span className="eyebrow">Labor cost</span>
                  <strong className="kpi-value">
                    {formatMetric(asNumber(staffKpis.labor_cost), "money")}
                  </strong>
                </div>
                <div>
                  <span className="eyebrow">Labor hours</span>
                  <strong className="kpi-value">
                    {formatMetric(asNumber(staffKpis.labor_hours), "number")}
                  </strong>
                </div>
                <div>
                  <span className="eyebrow">Labor %</span>
                  <strong className="kpi-value">
                    {formatMetric(asNumber(staffKpis.labor_pct), "percent")}
                  </strong>
                </div>
              </div>
            ) : (
              <div className="empty-state">
                {staffing.status === "error"
                  ? staffing.message
                  : "Staffing aggregates load with live data."}
              </div>
            )}
          </article>

          <article id="inventory" className="panel">
            <div className="panel-heading">
              <div>
                <h2>Inventory alerts</h2>
                <span className="panel-subtitle">Current on-hand from the inventory ledger</span>
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
                        <td className="num">
                          {decimal.format(asNumber(row.closing_qty) ?? 0)}
                        </td>
                        <td className="num">
                          {formatMetric(asNumber(row.days_of_cover), "number")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state">
                {overview.status === "ready"
                  ? "No reorder alerts in the current ledger."
                  : "Ledger alerts appear after connection."}
              </div>
            )}
          </article>
        </section>

        {showOps ? (
          <section className="section">
            <article className="panel ops-panel">
              <div className="panel-heading">
                <div>
                  <h2>Operator note</h2>
                  <span className="panel-subtitle">
                    Visible to managers and owners only
                  </span>
                </div>
              </div>
              <p className="panel-note">
                Import coverage and missing-day checks remain on the local Streamlit
                console. This partner site stays read-only by design.
              </p>
            </article>
          </section>
        ) : null}

        <footer>
          <span>Bar Arbolada · Private partner analytics</span>
          <button type="button" className="text-button" onClick={() => setFeedbackOpen(true)}>
            Send a suggestion
          </button>
        </footer>
      </main>

      <FeedbackDialog open={feedbackOpen} onClose={() => setFeedbackOpen(false)} />
    </div>
  );
}
