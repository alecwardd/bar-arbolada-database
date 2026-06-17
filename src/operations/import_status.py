"""
Helpers for storing and reading importer run snapshots.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from src.models import ImportRunSnapshot


def snapshot_from_payload(payload: dict[str, Any]) -> ImportRunSnapshot:
    """Build an ImportRunSnapshot model from a script status payload."""
    return ImportRunSnapshot(
        source=str(payload.get("source") or "unknown"),
        staging_root=_clean_str(payload.get("staging_root")),
        run_staging_dir=_clean_str(payload.get("run_staging_dir")),
        messages_fetched=int(payload.get("messages_fetched") or 0),
        csv_attachments_saved=int(payload.get("csv_attachments_saved") or 0),
        lookback_days=int(payload.get("lookback_days") or 7),
        coverage_max_dates_json=_dump_json(payload.get("coverage_max_dates")),
        missing_report_days_json=_dump_json(payload.get("missing_report_days")),
        generated_on=_coerce_date(payload.get("generated_on")),
    )


def snapshot_to_payload(snapshot: ImportRunSnapshot | None) -> dict[str, Any]:
    """Convert a stored ImportRunSnapshot row back into dashboard-friendly payload."""
    if snapshot is None:
        return {}

    payload: dict[str, Any] = {
        "source": snapshot.source,
        "staging_root": snapshot.staging_root or "",
        "run_staging_dir": snapshot.run_staging_dir or "",
        "messages_fetched": snapshot.messages_fetched or 0,
        "csv_attachments_saved": snapshot.csv_attachments_saved or 0,
        "lookback_days": snapshot.lookback_days or 0,
        "coverage_max_dates": _load_json(snapshot.coverage_max_dates_json),
        "missing_report_days": _load_json(snapshot.missing_report_days_json),
        "generated_on": snapshot.generated_on.isoformat() if snapshot.generated_on else None,
    }

    if snapshot.created_at is not None:
        payload["created_at"] = snapshot.created_at.isoformat()

    return payload


def write_snapshot(session: Session, payload: dict[str, Any]) -> ImportRunSnapshot:
    """Persist a snapshot row for the latest import run."""
    snapshot = snapshot_from_payload(payload)
    session.add(snapshot)
    session.commit()
    return snapshot


def _dump_json(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True)


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        return date.fromisoformat(value)
    return None


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
