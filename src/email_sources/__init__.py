"""Email source implementations for report ingestion."""

from src.email_sources.base import EmailAttachment, EmailMessage, EmailSource, save_attachments
from src.email_sources.imap_source import ImapEmailSource
from src.email_sources.local_source import LocalDirectoryEmailSource

__all__ = [
    "EmailAttachment",
    "EmailMessage",
    "EmailSource",
    "ImapEmailSource",
    "LocalDirectoryEmailSource",
    "save_attachments",
]
