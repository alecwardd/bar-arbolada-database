"""
Local directory email source.

Useful for manual fallback and local testing:
drop CSVs into a directory and process as one synthetic message.
"""

from __future__ import annotations

from pathlib import Path

from src.email_sources.base import EmailAttachment, EmailMessage


class LocalDirectoryEmailSource:
    """Treat files in a directory as one inbound message batch."""

    def __init__(self, source_dir: Path) -> None:
        self.source_dir = source_dir

    def list_new_messages(self) -> list[EmailMessage]:
        if not self.source_dir.exists():
            return []

        attachments: list[EmailAttachment] = []
        for csv_path in sorted(self.source_dir.glob("*.csv")):
            attachments.append(
                EmailAttachment(
                    filename=csv_path.name,
                    content_type="text/csv",
                    content_bytes=csv_path.read_bytes(),
                )
            )

        if not attachments:
            return []

        return [
            EmailMessage(
                message_id=f"local::{self.source_dir.resolve()}",
                subject="Local directory batch",
                sender="local@filesystem",
                received_at="local",
                attachments=attachments,
            )
        ]

    def mark_processed(self, message_ids: list[str]) -> None:
        # Local mode is read-only to source_dir; importer archiving handles files.
        _ = message_ids
