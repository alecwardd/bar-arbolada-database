from datetime import datetime

from src.models import ImportRunSnapshot
from src.operations.import_status import snapshot_from_payload, snapshot_to_payload


def test_snapshot_from_payload_populates_model_fields():
    payload = {
        "source": "imap",
        "staging_root": "data/raw/email-inbox",
        "run_staging_dir": "data/raw/email-inbox/run-2026-03-30-abc123",
        "messages_fetched": 4,
        "csv_attachments_saved": 7,
        "lookback_days": 10,
        "coverage_max_dates": {"sales": "2026-03-29"},
        "missing_report_days": {"sales": ["2026-03-28"]},
        "generated_on": "2026-03-30",
    }

    snapshot = snapshot_from_payload(payload)

    assert snapshot.source == "imap"
    assert snapshot.messages_fetched == 4
    assert snapshot.csv_attachments_saved == 7
    assert snapshot.lookback_days == 10
    assert snapshot.generated_on.isoformat() == "2026-03-30"
    assert '"sales": "2026-03-29"' in snapshot.coverage_max_dates_json


def test_snapshot_to_payload_round_trips_json_fields():
    snapshot = ImportRunSnapshot(
        source="imap",
        staging_root="data/raw/email-inbox",
        run_staging_dir="data/raw/email-inbox/run-2026-03-30-abc123",
        messages_fetched=2,
        csv_attachments_saved=3,
        lookback_days=7,
        coverage_max_dates_json='{"sales": "2026-03-29"}',
        missing_report_days_json='{"sales": ["2026-03-28"]}',
    )
    snapshot.created_at = datetime(2026, 3, 30, 12, 0, 0)

    payload = snapshot_to_payload(snapshot)

    assert payload["source"] == "imap"
    assert payload["coverage_max_dates"] == {"sales": "2026-03-29"}
    assert payload["missing_report_days"] == {"sales": ["2026-03-28"]}
    assert payload["created_at"] == "2026-03-30T12:00:00"
