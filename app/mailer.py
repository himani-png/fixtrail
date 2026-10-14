"""Sending email.

Everything goes through a small `Mailer` interface, so the rest of the app
doesn't care whether mail is printed locally or sent with AWS SES.
"""

import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Protocol

from app.config import settings


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
        """Send an email and return its Message-ID."""
        ...


def build_message(to: str, subject: str, body: str, reply_to: str | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"FixTrail <notifications@{settings.inbound_email_domain}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=settings.inbound_email_domain)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    return msg


class ConsoleMailer:
    """Local development: print a summary and save each email as a .eml file
    in outbox/ (double-click it to open in your mail app)."""

    def __init__(self, outbox: str = "outbox"):
        self.outbox = Path(outbox)

    def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
        msg = build_message(to, subject, body, reply_to)
        self.outbox.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        slug = re.sub(r"[^a-z0-9]+", "-", subject.lower()).strip("-")[:40]
        path = self.outbox / f"{stamp}-{slug}.eml"
        path.write_bytes(msg.as_bytes())
        print(f"[email] to={to} subject={subject!r} saved={path}")
        return msg["Message-ID"]


def get_mailer() -> Mailer:
    if settings.mailer == "console":
        return ConsoleMailer()
    raise NotImplementedError(f"MAILER={settings.mailer!r} is not available yet (SES comes in Phase 7)")
