"""
Tests the IMAP partial-failure guard.

Before the fix, a message was marked processed (``\\Seen`` on IMAP) as soon as its
attachments hit disk — so a message with one good and one failing attachment was
marked done, and the failed attachment was permanently lost. The importer now
marks a message processed only when EVERY attachment it contributed imported
successfully.
"""

from pathlib import Path

from src.email_sources.base import EmailAttachment, EmailMessage, save_attachments
from scripts.import_from_email import select_processed_message_ids


def test_partial_failure_message_is_not_processed():
    good = Path("run/good.csv")
    bad = Path("run/bad.csv")
    solo = Path("run/solo.csv")

    message_paths = {
        "msg-partial": [good, bad],   # one attachment fails
        "msg-clean": [solo],          # all attachments succeed
    }
    results = {good: True, bad: False, solo: True}

    fully_ok, failed_report = select_processed_message_ids(message_paths, results)

    assert fully_ok == ["msg-clean"]
    assert "msg-partial" in failed_report
    assert failed_report["msg-partial"] == [bad]


def test_all_success_marks_every_message():
    a, b = Path("run/a.csv"), Path("run/b.csv")
    message_paths = {"m1": [a], "m2": [b]}
    results = {a: True, b: True}

    fully_ok, failed_report = select_processed_message_ids(message_paths, results)

    assert set(fully_ok) == {"m1", "m2"}
    assert failed_report == {}


def test_missing_result_counts_as_failure():
    # A file that never appears in results (importer never ran) must not count
    # as success — otherwise a dropped file could silently mark its message done.
    a = Path("run/a.csv")
    message_paths = {"m1": [a]}

    fully_ok, failed_report = select_processed_message_ids(message_paths, {})

    assert fully_ok == []
    assert failed_report == {"m1": [a]}


def test_save_attachments_maps_files_to_their_message(tmp_path):
    messages = [
        EmailMessage(
            message_id="msg-1",
            subject="daily",
            sender="pos@example.com",
            received_at="now",
            attachments=[
                EmailAttachment("sales.csv", "text/csv", b"a,b\n1,2\n"),
                EmailAttachment("labor.csv", "text/csv", b"a,b\n3,4\n"),
                EmailAttachment("ignore.pdf", "application/pdf", b"%PDF"),
            ],
        ),
    ]

    saved, message_paths = save_attachments(messages, tmp_path)

    assert len(saved) == 2  # PDF skipped
    assert set(message_paths.keys()) == {"msg-1"}
    assert {p.name for p in message_paths["msg-1"]} == {"sales.csv", "labor.csv"}
