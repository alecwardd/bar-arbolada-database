"""
Import Operations dashboard.

Operational view for owner/GM to monitor daily email-driven imports.
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.config import get_session
from src.models import ImportRunSnapshot
from src.operations.import_status import snapshot_to_payload


st.set_page_config(page_title="Import Operations", page_icon="📥", layout="wide")
st.title("📥 Import Operations")
st.caption("Daily report ingestion health, recent imports, and missing-day checks.")

STATUS_PATH = Path(__file__).parent.parent.parent / "reports" / "email_import_status.json"


def _load_status() -> dict:
    status = _load_status_from_db()
    if status:
        return status
    return _load_status_from_file()


def _load_status_from_db() -> dict:
    session = get_session()
    try:
        snapshot = (
            session.query(ImportRunSnapshot)
            .order_by(ImportRunSnapshot.created_at.desc(), ImportRunSnapshot.id.desc())
            .first()
        )
        return snapshot_to_payload(snapshot)
    except Exception:
        return {}
    finally:
        session.close()


def _load_status_from_file() -> dict:
    if not STATUS_PATH.exists():
        return {}
    try:
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    session = get_session()
    try:
        result = session.execute(text(sql), params or {})
        rows = result.fetchall()
        return pd.DataFrame(rows, columns=result.keys())
    finally:
        session.close()


status = _load_status()

col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Configured Source", status.get("source", "not_run"))
with col2:
    st.metric("Messages Fetched (last run)", status.get("messages_fetched", 0))
with col3:
    st.metric("CSV Attachments Saved (last run)", status.get("csv_attachments_saved", 0))

if status.get("created_at") or status.get("generated_on"):
    st.caption(
        "Latest snapshot: "
        f"{status.get('created_at') or status.get('generated_on')}"
    )

st.markdown("---")

left, right = st.columns([1, 1])

with left:
    st.subheader("Coverage Max Dates")
    coverage = status.get("coverage_max_dates", {})
    if coverage:
        cov_df = pd.DataFrame(
            [{"dataset": k, "max_date": v} for k, v in coverage.items()]
        )
        st.dataframe(cov_df, hide_index=True, width="stretch")
    else:
        st.info("No status snapshot yet. Run `python scripts/import_from_email.py` first.")

with right:
    st.subheader("Missing Report Days")
    gaps = status.get("missing_report_days", {})
    if gaps:
        gap_rows = []
        for rtype, days in gaps.items():
            gap_rows.append(
                {
                    "report_type": rtype,
                    "missing_days": len(days),
                    "dates": ", ".join(days[:8]) + (" ..." if len(days) > 8 else ""),
                }
            )
        gap_df = pd.DataFrame(gap_rows).sort_values("missing_days", ascending=False)
        st.dataframe(gap_df, hide_index=True, width="stretch")
    else:
        st.info("No missing-day analysis yet.")

st.markdown("---")

st.subheader("Recent Import Logs")
recent_logs = _query_df(
    """
    SELECT imported_at, import_type, filename, report_date_start, report_date_end, row_count, status
    FROM import_logs
    ORDER BY imported_at DESC
    LIMIT 100
    """
)
if recent_logs.empty:
    st.warning("No import logs found.")
else:
    st.dataframe(recent_logs, hide_index=True, width="stretch")

st.markdown("---")
st.subheader("Retry Command")
st.code(
    "python scripts/import_from_email.py --source imap\n"
    "# fallback/manual\n"
    "python scripts/import_from_email.py --source local --local-source-dir raw-csvs-before-pos-changes",
    language="bash",
)

