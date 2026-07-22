"""
Shared design system for the Bar Arbolada dashboards.

One place for the brand palette, chart theming, and base CSS so the forest/coral
language is applied system-wide instead of being re-declared per page. Streamlit
chrome (widgets, buttons, sidebar) is themed via ``.streamlit/config.toml``;
this module themes in-page content (CSS) and Plotly charts, which the config
theme does not reach.

Usage in a page::

    from dashboards.theme import inject_base_css, style_fig, FOREST, CORAL
    inject_base_css()
    ...
    fig = go.Figure(...)
    style_fig(fig)
"""

from __future__ import annotations

# ── Brand palette ────────────────────────────────────────────────────────────
FOREST = "#2d6a4f"        # primary brand green
FOREST_DARK = "#1b4332"   # deeper green for accents/gradients
CORAL = "#e76f51"         # secondary/accent, trend lines
TEAL = "#264653"          # tertiary, forecast/secondary series

# ── Semantic colors (status, good/bad) ───────────────────────────────────────
SUCCESS = "#22c55e"       # good / up / in-budget
DANGER = "#ef4444"        # bad / over / alert
WARNING = "#f59e0b"       # caution / near-threshold
INFO = "#3b82f6"          # neutral highlight / comparison

# ── Neutrals / typography ─────────────────────────────────────────────────────
INK = "#1a1a2e"           # headings
INK_SOFT = "#16213e"      # sub-headings
RULE = "#e9ecef"          # dividers / gridlines
MUTED = "#94a3b8"         # de-emphasized lines/text

# Ordered categorical sequence for multi-series charts. Brand colors lead so the
# most important series read as "Bar Arbolada", with semantic/neutral fillers.
CATEGORICAL = [FOREST, CORAL, INFO, WARNING, TEAL, SUCCESS, DANGER, MUTED]

# Sequential/diverging scales reused by heatmaps and choropleth-style charts.
SCALE_BAD_TO_GOOD = [DANGER, WARNING, SUCCESS]   # low = bad, high = good
SCALE_GOOD_TO_BAD = [SUCCESS, WARNING, DANGER]   # low = good, high = bad (e.g. cost %)

_FONT_FAMILY = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif'
)


def style_fig(fig, *, legend_top: bool = True):
    """
    Apply the brand look to a Plotly figure: transparent background, brand
    colorway, consistent font, tight margins, and soft gridlines. Returns the
    same figure for chaining. Callers may still override any of these after.
    """
    fig.update_layout(
        colorway=CATEGORICAL,
        font=dict(family=_FONT_FAMILY, color=INK, size=13),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
        hoverlabel=dict(font_family=_FONT_FAMILY),
    )
    if legend_top:
        fig.update_layout(
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0)
        )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=RULE, zeroline=False)
    return fig


def inject_base_css() -> None:
    """
    Inject the shared in-page CSS (KPI cards, typography, section dividers).

    Call once near the top of each page, after ``st.set_page_config``. Idempotent
    within a run. Kept in sync with the ``[theme]`` block in
    ``.streamlit/config.toml``.
    """
    import streamlit as st

    st.markdown(
        f"""
<style>
    .block-container {{ padding-top: 1rem; }}

    /* KPI metric cards */
    .stMetric {{
        border-radius: 10px;
        padding: 14px 16px;
        border-left: 4px solid {FOREST};
    }}
    div[data-testid="stMetricValue"] {{
        font-size: 1.6rem !important;
        font-weight: 700 !important;
    }}
    div[data-testid="stMetricDelta"] {{ font-size: 0.85rem !important; }}

    /* Typography */
    h1 {{ font-weight: 800; letter-spacing: -0.02em; }}
    h2 {{ font-weight: 700; color: {INK}; margin-top: 0.5rem; }}
    h3 {{ font-weight: 600; color: {INK_SOFT}; }}

    /* Section dividers */
    .section-divider {{ border: none; border-top: 2px solid {RULE}; margin: 1.5rem 0; }}
</style>
""",
        unsafe_allow_html=True,
    )
