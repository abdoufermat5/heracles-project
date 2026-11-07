"""Outgoing mail abstraction used by password recovery."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


@dataclass(frozen=True, slots=True)
class SentMail:
    to: str
    subject: str
    body: str


class MemoryMailer:
    """Collects messages in ``outbox`` (tests)."""

    def __init__(self) -> None:
        self.outbox: list[SentMail] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.outbox.append(SentMail(to, subject, body))


class SmtpMailer:
    """Plain ``smtplib`` sender with optional STARTTLS / implicit TLS and login."""

    def __init__(
        self,
        host: str,
        port: int = 25,
        *,
        sender: str = "heracles@localhost",
        username: str | None = None,
        password: str | None = None,
        starttls: bool = False,
        use_ssl: bool = False,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._sender = sender
        self._username = username
        self._password = password
        self._starttls = starttls
        self._ssl = use_ssl
        self._timeout = timeout

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        context = ssl.create_default_context()
        if self._ssl:
            with smtplib.SMTP_SSL(
                self._host, self._port, timeout=self._timeout, context=context
            ) as smtp:
                self._deliver(smtp, msg)
            return
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            if self._starttls:
                smtp.starttls(context=context)
            self._deliver(smtp, msg)

    def _deliver(self, smtp: smtplib.SMTP, msg: EmailMessage) -> None:
        if self._username is not None and self._password is not None:
            smtp.login(self._username, self._password)
        smtp.send_message(msg)
