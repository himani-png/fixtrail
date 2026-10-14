"""Tests for photos sent by email reply (Phase 5b)."""

import hashlib
from email.message import EmailMessage

import pytest

from app import db, inbound_email, photos, services
from app.config import settings

PNG = b"\x89PNG\r\n\x1a\n" + b"real enough for the type check"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg bytes"
GOOD_VERDICTS = {"spf": "PASS", "dkim": "PASS", "spam": "PASS", "virus": "PASS", "dmarc": "PASS"}


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, reply_to=None):
        self.sent.append({"to": to, "subject": subject, "body": body})
        return "<id@test>"


@pytest.fixture
def mailer(monkeypatch, tmp_path):
    fake = FakeMailer()
    monkeypatch.setattr(services, "mailer", fake)
    monkeypatch.setattr(services, "RUN_IN_BACKGROUND", False)
    monkeypatch.setattr(photos, "store", photos.LocalPhotoStore(str(tmp_path / "uploads")))
    return fake


@pytest.fixture
def issue(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    issue = db.list_issues(conn)[0]
    issue["token"] = db.get_token_for_issue(conn, issue["id"], "photo_reply")
    mailer.sent.clear()
    return issue


def reply(token, sender=settings.tenant_email, attachments=(("sink.png", PNG, "png"),),
          message_id="<reply-1@tenant.example>", domain=settings.inbound_email_domain):
    msg = EmailMessage()
    msg["From"] = f"Alex Tenant <{sender}>"
    msg["To"] = f"photos+{token}@{domain}"
    msg["Subject"] = "Re: FixTrail logged: Kitchen sink leaking"
    msg["Message-ID"] = message_id
    msg.set_content("Here's a photo.")
    for name, data, subtype in attachments:
        msg.add_attachment(data, maintype="image", subtype=subtype, filename=name)
    return msg.as_bytes()


def photo_events(conn, issue_id):
    return [e for e in db.list_events(conn, issue_id) if e["type"] == "photo_added"]


# ------------------------------------------------------------- accepted

def test_reply_with_photo_is_added_with_email_details(conn, issue, mailer):
    result = inbound_email.process_email(conn, reply(issue["token"]))
    assert result.accepted and result.photos_added == 1

    [event] = photo_events(conn, issue["id"])
    p = event["payload"]
    assert p["source"] == "email_reply"
    assert p["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert p["sender"] == settings.tenant_email
    assert p["message_id"] == "<reply-1@tenant.example>"
    assert p["verdicts"] == inbound_email.NO_VERDICTS  # honest about local testing
    assert event["verification"] == "verified"

    confirmation = mailer.sent[-1]
    assert confirmation["subject"] == "1 photo added to: Kitchen sink leaking"
    assert "Full fingerprint:" in confirmation["body"]


def test_several_photos_and_ses_verdicts(conn, issue):
    raw = reply(issue["token"], attachments=(("a.png", PNG, "png"), ("b.jpg", JPEG, "jpeg")))
    result = inbound_email.process_email(conn, raw, verdicts=GOOD_VERDICTS)
    assert result.photos_added == 2
    assert photo_events(conn, issue["id"])[0]["payload"]["verdicts"] == GOOD_VERDICTS


def test_sender_match_ignores_case_and_display_name(conn, issue):
    result = inbound_email.process_email(conn, reply(issue["token"], sender=settings.tenant_email.upper()))
    assert result.accepted


def test_same_email_twice_is_not_added_twice(conn, issue):
    inbound_email.process_email(conn, reply(issue["token"]))
    second = inbound_email.process_email(conn, reply(issue["token"]))
    assert not second.accepted and "already processed" in second.reason
    assert len(photo_events(conn, issue["id"])) == 1


def test_same_photo_in_a_new_email_is_skipped(conn, issue):
    inbound_email.process_email(conn, reply(issue["token"]))
    again = inbound_email.process_email(conn, reply(issue["token"], message_id="<reply-2@tenant.example>"))
    assert again.photos_added == 0
    assert "already in the record" in again.skipped[0]


# ------------------------------------------------------------- rejected

def test_wrong_sender_is_rejected_without_reply(conn, issue, mailer):
    result = inbound_email.process_email(conn, reply(issue["token"], sender="stranger@example.com"))
    assert not result.accepted and "isn't the tenant" in result.reason
    assert photo_events(conn, issue["id"]) == []
    assert mailer.sent == []  # never email strangers


def test_bad_token_is_rejected(conn, issue):
    result = inbound_email.process_email(conn, reply("not-a-real-token"))
    assert not result.accepted and "isn't valid" in result.reason


def test_wrong_domain_is_rejected(conn, issue):
    result = inbound_email.process_email(conn, reply(issue["token"], domain="evil.example"))
    assert not result.accepted and "photo address" in result.reason


def test_landlord_token_cannot_be_used_for_photos(conn, issue):
    landlord_token = db.get_token_for_issue(conn, issue["id"], "landlord")
    assert not inbound_email.process_email(conn, reply(landlord_token)).accepted


@pytest.mark.parametrize("bad, expected", [
    ({"spam": "FAIL"}, "spam"),
    ({"virus": "FAIL"}, "virus"),
    ({"dmarc": "FAIL"}, "DMARC"),
    ({"spf": "FAIL", "dkim": "FAIL"}, "could not be authenticated"),
])
def test_failed_ses_verdicts_are_rejected(conn, issue, bad, expected):
    result = inbound_email.process_email(conn, reply(issue["token"]), verdicts={**GOOD_VERDICTS, **bad})
    assert not result.accepted and expected in result.reason
    assert photo_events(conn, issue["id"]) == []


def test_dkim_pass_alone_is_enough(conn, issue):
    # Forwarded mail often fails SPF but keeps a valid DKIM signature.
    result = inbound_email.process_email(conn, reply(issue["token"]), verdicts={**GOOD_VERDICTS, "spf": "FAIL"})
    assert result.accepted


def test_non_image_attachment_is_skipped_and_tenant_told(conn, issue, mailer):
    raw = reply(issue["token"], attachments=(("notes.png", b"not really an image", "png"),))
    result = inbound_email.process_email(conn, raw)
    assert not result.accepted and "no usable photos" in result.reason
    assert "isn't a JPEG or PNG" in result.skipped[0]
    assert mailer.sent[-1]["subject"].startswith("No photos were added")


def test_timeline_labels_email_photos(conn, issue, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app

    inbound_email.process_email(conn, reply(issue["token"]))
    monkeypatch.setattr(db, "DEFAULT_PATH", db.database_path(conn))
    client = TestClient(app)
    client.post("/login", data={"passcode": settings.tenant_passcode, "next": "/"})
    page = client.get(f"/issues/{issue['id']}").text
    assert "Photo added via email" in page
    assert "Emailed by" in page and inbound_email.NO_VERDICTS in page
    assert "Sent to: <code>None" not in page  # incoming email isn't shown as one FixTrail sent
