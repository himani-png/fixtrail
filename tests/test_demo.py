"""Tests for the demo data and the tamper demo."""

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, demo, photos, services
from app.config import settings
from app.main import app

NOW = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)


class FakeMailer:
    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, reply_to=None):
        self.sent.append({"to": to, "subject": subject, "body": body})
        return f"<{len(self.sent)}@test>"


@pytest.fixture
def seeded(conn, monkeypatch, tmp_path):
    fake = FakeMailer()
    monkeypatch.setattr(services, "mailer", fake)
    monkeypatch.setattr(photos, "store", photos.LocalPhotoStore(str(tmp_path / "uploads")))
    demo.seed_demo(conn, now=NOW)
    return fake


def test_demo_history_is_realistic_and_marked(conn, seeded):
    assert db.is_demo(conn)
    assert {i["title"]: i["status"] for i in db.list_issues(conn)} == {
        "Mold on bathroom ceiling": "closed",
        "Heater not working": "open",
        "Kitchen sink leaking": "scheduled",
        "Front door lock sticking": "open",
    }
    labels = {e["verification"] for e in db.list_events(conn)}
    assert labels == {"verified", "tenant_reported", "landlord_reported"}
    assert any(e["payload"].get("source") == "email_reply" for e in db.list_events(conn))


def test_demo_events_are_in_time_order_and_chain_verifies(conn, seeded):
    times = [e["created_at"] for e in db.list_events(conn)]
    assert times == sorted(times)
    assert times[0].startswith("2026-09-14")  # 30 days before NOW
    assert db.verify_chain(conn)["ok"]


def test_demo_emails_carry_checkable_fingerprints(conn, seeded):
    email = seeded.sent[-1]
    lines = email["body"].splitlines()
    fingerprint = lines[lines.index("Full fingerprint:") + 1]
    number = int(email["body"].split("after event #")[1].split(":")[0])
    assert db.check_fingerprint(conn, number, fingerprint)["match"]


def test_demo_needs_an_empty_database(conn, seeded):
    with pytest.raises(RuntimeError):
        demo.seed_demo(conn, now=NOW)


def test_clock_is_restored_after_seeding(conn, seeded):
    assert db.utc_now().startswith(str(datetime.now(timezone.utc).year))
    assert services.RUN_IN_BACKGROUND is True


def test_demo_banner_on_pages(conn, seeded, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_PATH", db.database_path(conn))
    client = TestClient(app)
    client.post("/login", data={"passcode": settings.tenant_passcode, "next": "/"})
    assert "Demo data." in client.get("/").text
    assert "not a real repair record" in client.get("/reports/all").text


def test_no_banner_for_real_records(conn, monkeypatch):
    monkeypatch.setattr(db, "DEFAULT_PATH", db.database_path(conn))
    assert "Demo data." not in TestClient(app).get("/verify").text


def test_tamper_demo_fools_the_chain_but_not_the_email(conn, seeded):
    path = Path(__file__).resolve().parent.parent / "scripts" / "tamper_demo.py"
    spec = importlib.util.spec_from_file_location("tamper_demo", path)
    tamper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tamper)

    email = seeded.sent[-1]["body"].splitlines()
    fingerprint = email[email.index("Full fingerprint:") + 1]
    number = int(seeded.sent[-1]["body"].split("after event #")[1].split(":")[0])

    change = tamper.rewrite_history(conn)
    assert change["after"] > change["before"]
    assert db.verify_chain(conn)["ok"]  # the operator's own check is fooled
    assert not db.check_fingerprint(conn, number, fingerprint)["match"]  # the email is not
    with pytest.raises(Exception, match="append-only"):  # protections were put back
        conn.execute("DELETE FROM events WHERE id = 1")
