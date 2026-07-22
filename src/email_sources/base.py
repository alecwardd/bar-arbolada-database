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
) -> tuple[list[Path], dict[str, list[Path]]]:
    """
    Save CSV attachments to target_dir.

    Returns:
      (saved_paths, message_paths)

    where ``message_paths`` maps each source message id to the list of files that
    were saved from it. Callers use this map to mark a message processed ONLY when
    every one of its attachments imported successfully — a message is not "done"
    just because its bytes reached disk.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    message_paths: dict[str, list[Path]] = {}

    for msg in messages:
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
            message_paths.setdefault(msg.message_id, []).append(out)

    return saved, message_paths
