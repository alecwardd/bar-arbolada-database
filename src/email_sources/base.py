"""
Email source interface for daily report ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class EmailAttachment:
    """Represents one attachment from an inbound email message."""

    filename: str
    content_type: str | None
    content_bytes: bytes


@dataclass(frozen=True)
class EmailMessage:
    """Normalized email metadata and attachments for processing."""

    message_id: str
    subject: str
    sender: str
    received_at: str
    attachments: list[EmailAttachment]


class EmailSource(Protocol):
    """Provider-agnostic mailbox interface."""

    def list_new_messages(self) -> list[EmailMessage]:
        """Return unprocessed messages that may contain report attachments."""

    def mark_processed(self, message_ids: list[str]) -> None:
        """Mark processed messages so they are not imported again."""


def save_attachments(
    messages: list[EmailMessage],
    target_dir: Path,
) -> tuple[list[Path], list[str]]:
    """
    Save CSV attachments to target_dir.

    Returns:
      (saved_paths, source_message_ids_with_saved_attachments)
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    message_ids: list[str] = []

    for msg in messages:
        saved_for_message = 0
        for att in msg.attachments:
            # Keep only CSV reports for this pipeline.
            if not att.filename.lower().endswith(".csv"):
                continue

            out = target_dir / att.filename
            # Avoid filename collisions from duplicate message forwards.
            if out.exists():
                stem = out.stem
                suffix = out.suffix
                i = 1
                while True:
                    candidate = target_dir / f"{stem}__{i}{suffix}"
                    if not candidate.exists():
                        out = candidate
                        break
                    i += 1

            out.write_bytes(att.content_bytes)
            saved.append(out)
            saved_for_message += 1

        if saved_for_message > 0:
            message_ids.append(msg.message_id)

    return saved, message_ids
