"""Photos sent by replying to a FixTrail email.

Tenant emails have Reply-To: photos+<token>@<INBOUND_EMAIL_DOMAIN>. When a
reply arrives, process_email() runs these checks before anything is added:

  1. The address contains a valid photo-reply token, which identifies the issue.
  2. The sender is the tenant's registered email address.
  3. Spam, virus, and authentication verdicts don't fail. In production, AWS
     SES provides these (SPF/DKIM prove the sender address wasn't faked).
     Locally there are none, and that is recorded honestly.
  4. Only JPEG/PNG images within the size limit are kept.

The email's body text is ignored for the record; only the photos are added.

The same function serves local testing (scripts/ingest_email.py reads .eml
files from inbox/) and production (SES receiving, wired up in Phase 7).
"""

import hashlib
import re
from dataclasses import dataclass, field
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr

from app import db, services
from app.config import settings

NO_VERDICTS = "not available (local test)"


@dataclass
class Result:
    accepted: bool
    reason: str
    issue_id: str | None = None
    photos_added: int = 0
    skipped: list[str] = field(default_factory=list)


def _find_token(msg: EmailMessage) -> str | None:
    """Look for photos+<token>@<our domain> in the recipient headers."""
    domain = re.escape(settings.inbound_email_domain.lower())
    pattern = re.compile(rf"^photos\+([A-Za-z0-9_-]+)@{domain}$")
    headers = []
    for name in ("To", "Cc", "Delivered-To", "X-Original-To"):
        headers.extend(msg.get_all(name, []))
    for _, address in getaddresses(headers):
        match = pattern.match(address.strip().lower()) if address else None
        if match:
            # Tokens are case-sensitive, so take the original spelling back out.
            start = address.lower().index(match.group(1).lower())
            return address[start:start + len(match.group(1))]
    return None


def _verdict_problem(verdicts: dict | None) -> str | None:
    """Return why the message should be rejected, or None if it's fine."""
    if verdicts is None:
        return None  # local test: nothing to check, recorded as unavailable
    v = {k: str(val).upper() for k, val in verdicts.items()}
    if v.get("virus") == "FAIL":
        return "the message failed the virus check"
    if v.get("spam") == "FAIL":
        return "the message was flagged as spam"
    if v.get("dmarc") == "FAIL":
        return "the sender's domain policy (DMARC) check failed"
    if v.get("spf") != "PASS" and v.get("dkim") != "PASS":
        return "the sender address could not be authenticated (SPF and DKIM did not pass)"
    return None


def _image_parts(msg: EmailMessage):
    """Yield (filename, bytes) for every attachment or inline part that claims to be a file."""
    for part in msg.walk():
        if part.is_multipart():
            continue
        filename = part.get_filename()
        if part.get_content_maintype() != "image" and not filename:
            continue  # the text/html body
        data = part.get_payload(decode=True) or b""
        yield filename or f"photo.{part.get_content_subtype()}", data


def process_email(conn, raw: bytes, verdicts: dict | None = None, notify: bool = True) -> Result:
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    token = _find_token(msg)
    if token is None:
        return Result(False, "it wasn't sent to a FixTrail photo address")
    issue_id = db.lookup_token(conn, token, "photo_reply")
    if issue_id is None:
        return Result(False, "the photo address isn't valid for any issue")

    prop = db.get_or_create_property(conn)
    sender = parseaddr(msg.get("From", ""))[1].strip().lower()
    if sender != prop["tenant_email"].strip().lower():
        # No reply in this case, so FixTrail never emails strangers.
        return Result(False, f"the sender ({sender or 'unknown'}) isn't the tenant's registered address", issue_id)

    problem = _verdict_problem(verdicts)
    if problem:
        return Result(False, problem, issue_id)

    message_id = (msg.get("Message-ID") or "").strip()
    events = db.list_events(conn, issue_id)
    if message_id and any(e["type"] == "photo_added" and e["payload"].get("message_id") == message_id for e in events):
        return Result(False, "this email was already processed", issue_id)
    known_hashes = {e["payload"].get("sha256") for e in events if e["type"] == "photo_added"}

    extra = {
        "sender": sender,
        "message_id": message_id,
        "verdicts": verdicts if verdicts is not None else NO_VERDICTS,
    }
    result = Result(True, "", issue_id)
    for filename, data in _image_parts(msg):
        if hashlib.sha256(data).hexdigest() in known_hashes:
            result.skipped.append(f"{filename} is already in the record")
            continue
        try:
            services.add_photo(conn, issue_id, filename, data, source="email_reply", extra=extra)
            known_hashes.add(hashlib.sha256(data).hexdigest())
            result.photos_added += 1
        except services.ActionError as error:
            result.skipped.append(str(error))

    if result.photos_added == 0:
        result.accepted = False
        result.reason = "no usable photos were attached"
    else:
        result.reason = f"{result.photos_added} photo(s) added"
    if notify:
        services.queue_photo_reply_confirmation(conn, issue_id, result.photos_added, result.skipped)
    return result
