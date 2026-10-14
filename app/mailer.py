"""Sending email.

Everything goes through a small `Mailer` interface, so the rest of the app
doesn't care whether mail is printed locally or sent with AWS SES.
"""

import re
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Protocol

from app.config import settings


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
        """Send an email and return its Message-ID."""
        ...


# Email lines may be up to 998 characters (RFC 5322). Python's default of 78
# makes it re-encode bodies with long links, splitting them with "=" signs.
LONG_LINES = policy.default.clone(max_line_length=998)


def sender_address() -> str:
    """With SES, the From address must be one you verified in SES."""
    return settings.ses_from_email or f"notifications@{settings.inbound_email_domain}"


def build_message(to: str, subject: str, body: str, reply_to: str | None = None) -> EmailMessage:
    msg = EmailMessage(policy=LONG_LINES)
    msg["From"] = f"FixTrail <{sender_address()}>"
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=settings.inbound_email_domain)
    if reply_to:
        msg["Reply-To"] = reply_to
    # Plain ASCII goes out as-is, so links and fingerprints stay copy-pasteable.
    msg.set_content(body, cte="7bit" if body.isascii() else "quoted-printable")
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


class SESMailer:
    """Production: send through Amazon SES (API v2).

    The whole message is sent "raw", so FixTrail's own headers (Reply-To for
    photo replies) and the plain-text fingerprint footer arrive untouched.
    In the SES sandbox, every recipient must be a verified address.
    """

    def __init__(self, client=None):
        if client is None:
            import boto3
            client = boto3.client("sesv2", region_name=settings.aws_region)
        self.client = client

    def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> str:
        if not settings.ses_from_email:
            raise RuntimeError("Set SES_FROM_EMAIL to an address verified in Amazon SES.")
        msg = build_message(to, subject, body, reply_to)
        response = self.client.send_email(
            FromEmailAddress=settings.ses_from_email,
            Destination={"ToAddresses": [to]},
            Content={"Raw": {"Data": msg.as_bytes()}},
        )
        print(f"[email via SES] to={to} subject={subject!r} id={response['MessageId']}")
        # SES assigns its own message ID; it's what SES logs and bounce reports use.
        return response["MessageId"]


def get_mailer() -> Mailer:
    if settings.mailer == "console":
        return ConsoleMailer()
    if settings.mailer == "ses":
        return SESMailer()
    raise ValueError(f"Unknown MAILER={settings.mailer!r}; use 'console' or 'ses'.")
