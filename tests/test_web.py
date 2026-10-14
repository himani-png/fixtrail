"""Tests for the web pages (Phase 4)."""

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from app import db, photos, services
from app.config import settings
from app.main import app

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image data"


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, reply_to=None):
        self.sent.append({"to": to, "subject": subject, "body": body})
        return f"<msg-{len(self.sent)}@test>"


@pytest.fixture
def mailer():
    return FakeMailer()


@pytest.fixture
def client(tmp_path, monkeypatch, mailer):
    monkeypatch.setattr(db, "DEFAULT_PATH", str(tmp_path / "web.db"))
    monkeypatch.setattr(photos, "store", photos.LocalPhotoStore(str(tmp_path / "uploads")))
    monkeypatch.setattr(services, "mailer", mailer)
    monkeypatch.setattr(services, "RUN_IN_BACKGROUND", False)
    # Not used as a context manager, so the MCP lifespan doesn't start.
    return TestClient(app)


@pytest.fixture
def tenant(client):
    client.post("/login", data={"passcode": settings.tenant_passcode, "next": "/"})
    return client


@pytest.fixture
def issue_id(client):
    conn = db.connect()
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    issue = db.list_issues(conn)[0]
    conn.close()
    return issue["id"]


def landlord_token(issue_id):
    conn = db.connect()
    token = db.get_token_for_issue(conn, issue_id, "landlord")
    conn.close()
    return token


def events(issue_id):
    conn = db.connect()
    result = db.list_events(conn, issue_id)
    conn.close()
    return result


# ------------------------------------------------------------- login

def test_tenant_pages_need_the_passcode(client, issue_id):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
    assert client.get(f"/issues/{issue_id}", follow_redirects=False).status_code == 303


def test_wrong_passcode_is_rejected(client):
    response = client.post("/login", data={"passcode": "nope", "next": "/"})
    assert response.status_code == 401
    assert "That passcode isn&#39;t right" in response.text


def test_login_does_not_redirect_off_site(client):
    response = client.post("/login", data={"passcode": settings.tenant_passcode, "next": "//evil.com"},
                           follow_redirects=False)
    assert response.headers["location"] == "/"


# ----------------------------------------------------------- tenant pages

def test_dashboard_lists_issues_and_record_status(tenant, issue_id):
    page = tenant.get("/").text
    assert "Kitchen sink leaking" in page
    assert "Record intact" in page


def test_timeline_shows_events_with_labels(tenant, issue_id):
    page = tenant.get(f"/issues/{issue_id}").text
    assert "Tenant reported: Kitchen sink leaking" in page
    assert "FixTrail emailed the landlord" in page
    assert "Verified" in page


# ---------------------------------------------------------- landlord page

def test_bad_landlord_link_is_not_found(client):
    assert client.get("/respond/not-a-real-token").status_code == 404


def test_landlord_page_shows_issue_without_login(client, issue_id):
    page = client.get(f"/respond/{landlord_token(issue_id)}").text
    assert "Kitchen sink leaking" in page
    assert "Schedule repair" in page


def test_landlord_schedules_repair(client, issue_id, mailer):
    token = landlord_token(issue_id)
    response = client.post(f"/respond/{token}", data={"action": "schedule", "when": "2026-10-20", "time": "10:00"})
    assert "response is recorded" in response.text

    last = events(issue_id)[-1]
    assert last["type"] == "landlord_scheduled"
    assert last["payload"]["date"] == "2026-10-20 10:00"
    assert last["verification"] == "verified"

    conn = db.connect()
    assert db.get_issue(conn, issue_id)["status"] == "scheduled"
    assert "scheduled a repair for Tuesday, October 20 at 10:00 AM" in services.list_open_issues(conn)
    conn.close()

    tenant_email = mailer.sent[-1]
    assert tenant_email["to"] == settings.tenant_email
    assert "Landlord scheduled a repair for Tuesday, October 20, 2026 at 10:00 AM" in tenant_email["body"]
    assert "Full fingerprint:" in tenant_email["body"]


def test_schedule_needs_a_date(client, issue_id):
    before = len(events(issue_id))
    response = client.post(f"/respond/{landlord_token(issue_id)}", data={"action": "schedule", "when": ""})
    assert response.status_code == 400
    assert "pick a date" in response.text
    assert len(events(issue_id)) == before


def test_access_issue_is_labeled_landlord_reported(client, issue_id):
    client.post(f"/respond/{landlord_token(issue_id)}", data={"action": "access_issue", "note": "No answer at 10am"})
    last = events(issue_id)[-1]
    assert last["type"] == "access_issue"
    assert last["verification"] == "landlord_reported"
    assert last["payload"]["note"] == "No answer at 10am"


def test_landlord_shows_up_on_tenant_timeline(client, tenant, issue_id):
    client.post(f"/respond/{landlord_token(issue_id)}", data={"action": "acknowledge"})
    assert "Landlord acknowledged the issue" in tenant.get(f"/issues/{issue_id}").text


# ----------------------------------------------------------------- photos

def test_photo_upload_records_fingerprint(tenant, issue_id):
    response = tenant.post(f"/issues/{issue_id}/photos", files={"files": ("sink.png", PNG, "image/png")})
    assert "1 photo added" in response.text

    photo_event = events(issue_id)[-1]
    assert photo_event["type"] == "photo_added"
    assert photo_event["payload"]["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert photo_event["payload"]["source"] == "web_upload"

    served = tenant.get(f"/photos/{photo_event['id']}")
    assert served.content == PNG
    assert served.headers["content-type"] == "image/png"


def test_non_image_upload_is_rejected(tenant, issue_id):
    response = tenant.post(f"/issues/{issue_id}/photos", files={"files": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400
    assert "notes.txt isn&#39;t a JPEG or PNG photo" in response.text
    assert events(issue_id)[-1]["type"] != "photo_added"


def test_photo_access_needs_tenant_or_landlord_link(client, tenant, issue_id):
    tenant.post(f"/issues/{issue_id}/photos", files={"files": ("sink.png", PNG, "image/png")})
    event_id = events(issue_id)[-1]["id"]
    tenant.get("/logout")

    assert client.get(f"/photos/{event_id}").status_code == 403
    assert client.get(f"/photos/{event_id}?t=wrong").status_code == 403
    assert client.get(f"/photos/{event_id}?t={landlord_token(issue_id)}").content == PNG


# ----------------------------------------------------------------- verify

def test_verify_page_and_fingerprint_check(client, issue_id):
    assert "Record intact" in client.get("/verify").text

    first = events(issue_id)[0]
    good = client.post("/verify", data={"event_id": "#1", "fingerprint": first["hash"]}).text
    assert "✓ Match" in good
    bad = client.post("/verify", data={"event_id": "1", "fingerprint": "0" * 64}).text
    assert "✗ No match" in bad


def test_verify_page_shows_tampering(client, issue_id):
    conn = db.connect()
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("UPDATE events SET payload = ? WHERE id = 1", (json.dumps({"title": "forged"}),))
    conn.close()

    page = client.get("/verify").text
    assert "Record broken at event #1" in page
