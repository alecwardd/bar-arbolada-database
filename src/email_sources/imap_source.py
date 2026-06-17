"""
IMAP-backed email source.

Designed for business-owned inboxes (Gmail, Microsoft, etc.) that expose IMAP.
"""

from __future__ import annotations

import email
import imaplib
from email.message import Message
from typing import Iterable

from src.email_sources.base import EmailAttachment, EmailMessage


class ImapEmailSource:
    """Fetches unread messages and attachments from an IMAP inbox."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 993,
        mailbox: str = "INBOX",
        subject_contains: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mailbox = mailbox
        self.subject_contains = subject_contains.lower() if subject_contains else None
        self._uid_map: dict[str, bytes] = {}

    def _connect(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.host, self.port)
        client.login(self.username, self.password)
        client.select(self.mailbox)
        return client

    def list_new_messages(self) -> list[EmailMessage]:
        client = self._connect()
        try:
            status, data = client.uid("search", None, "UNSEEN")
            if status != "OK" or not data or not data[0]:
                return []

            message_uids = data[0].split()
            results: list[EmailMessage] = []

            for uid in message_uids:
                # Use BODY.PEEK so dry runs do not implicitly mark messages as seen.
                status, payload = client.uid("fetch", uid, "(BODY.PEEK[])")
                if status != "OK" or not payload:
                    continue

                raw = payload[0][1]
                parsed = email.message_from_bytes(raw)
                if not isinstance(parsed, Message):
                    continue

                subject = (parsed.get("Subject") or "").strip()
                if self.subject_contains and self.subject_contains not in subject.lower():
                    continue

                sender = (parsed.get("From") or "").strip()
                received_at = (parsed.get("Date") or "").strip()
                message_id = (parsed.get("Message-ID") or uid.decode("utf-8")).strip()
                attachments = list(self._extract_attachments(parsed))
                if not attachments:
                    continue

                results.append(
                    EmailMessage(
                        message_id=message_id,
                        subject=subject,
                        sender=sender,
                        received_at=received_at,
                        attachments=attachments,
                    )
                )
                self._uid_map[message_id] = uid

            return results
        finally:
            try:
                client.close()
            except Exception:
                pass
            client.logout()

    def mark_processed(self, message_ids: list[str]) -> None:
        if not message_ids:
            return

        client = self._connect()
        try:
            for message_id in message_ids:
                uid = self._uid_map.get(message_id)
                if not uid:
                    continue
                # Mark as seen so we do not repeatedly process.
                client.uid("store", uid, "+FLAGS", "\\Seen")
        finally:
            try:
                client.close()
            except Exception:
                pass
            client.logout()

    @staticmethod
    def _extract_attachments(parsed_msg: Message) -> Iterable[EmailAttachment]:
        for part in parsed_msg.walk():
            disp = part.get_content_disposition()
            filename = part.get_filename()
            if disp != "attachment" or not filename:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            yield EmailAttachment(
                filename=filename,
                content_type=part.get_content_type(),
                content_bytes=payload,
            )
