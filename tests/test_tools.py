"""Tests for the core actions and MCP tools (Phase 3)."""

import pytest
from mcp import Client

from app import db, mcp_tools, models, services


class FakeMailer:
    """Collects emails in a list instead of sending them."""

    def __init__(self):
        self.sent = []

    def send(self, to, subject, body, reply_to=None):
        self.sent.append({"to": to, "subject": subject, "body": body, "reply_to": reply_to})
        return f"<msg-{len(self.sent)}@test>"


@pytest.fixture
def mailer(monkeypatch):
    fake = FakeMailer()
    monkeypatch.setattr(services, "mailer", fake)
    monkeypatch.setattr(services, "RUN_IN_BACKGROUND", False)
    return fake


def types(conn, issue_id):
    return [e["type"] for e in db.list_events(conn, issue_id)]


# ----------------------------------------------------------- reporting

def test_report_issue_logs_and_emails_both_parties(conn, mailer):
    speech = services.report_issue(conn, "Kitchen sink leaking", "kitchen")

    assert "logged kitchen sink leaking" in speech
    issue = db.list_issues(conn)[0]
    assert issue["category"] == "water"  # auto-detected
    assert types(conn, issue["id"]) == ["issue_reported", "landlord_notified"]

    landlord_email, tenant_email = mailer.sent
    token = db.get_token_for_issue(conn, issue["id"], "landlord")
    assert landlord_email["to"] == "landlord@example.com"
    assert f"/respond/{token}" in landlord_email["body"]

    photo_token = db.get_token_for_issue(conn, issue["id"], "photo_reply")
    assert tenant_email["reply_to"].startswith(f"photos+{photo_token}@")


def test_landlord_notified_event_stores_message_id_and_copy(conn, mailer):
    services.report_issue(conn, "Heater not working", "living room")
    notified = db.list_events(conn)[-1]
    assert notified["verification"] == "verified"
    assert notified["payload"]["message_id"] == "<msg-1@test>"
    assert notified["payload"]["body"] == mailer.sent[0]["body"]


def test_every_email_has_a_fingerprint_that_checks_out(conn, mailer):
    services.report_issue(conn, "Heater not working", "living room")
    for email in mailer.sent:
        assert email["body"].isascii()  # keeps mail software from re-encoding it
        lines = email["body"].splitlines()
        fingerprint = lines[lines.index("Full fingerprint:") + 1]
        event_no = int(email["body"].split("after event #")[1].split(":")[0])
        assert db.check_fingerprint(conn, event_no, fingerprint)["match"] is True


# ------------------------------------------------------------- listing

def test_list_open_issues(conn, mailer):
    assert services.list_open_issues(conn) == "You have no open repair issues."
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    services.report_issue(conn, "Heater not working", "living room")

    speech = services.list_open_issues(conn)
    assert speech.startswith("You have 2 open issues.")
    assert "no landlord response yet" in speech


def test_list_shows_latest_landlord_response(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    issue = db.list_issues(conn)[0]
    db.append_event(conn, issue["id"], "landlord_acknowledged", "landlord", "verified")

    assert "your landlord acknowledged it today" in services.list_open_issues(conn)


# ------------------------------------------------------------- matching

def test_issue_matching_by_everyday_words(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    services.report_issue(conn, "Heater not working", "living room")
    services.report_issue(conn, "Kitchen light broken", "kitchen")

    assert services.find_issue(conn, "the heat")[0]["title"] == "Heater not working"
    assert services.find_issue(conn, "the sink")[0]["title"] == "Kitchen sink leaking"
    issue, question = services.find_issue(conn, "the kitchen")
    assert issue is None and question.startswith("Do you mean")
    issue, message = services.find_issue(conn, "the garage door")
    assert issue is None and "couldn't find" in message


def test_matching_tolerates_typos():
    issues = [{"id": "1", "title": "Heater not working", "location": "bedroom", "category": "heat"}]
    assert models.match_issue("the haeter", issues).issue["id"] == "1"


def test_matching_avoids_false_positives():
    issues = [
        {"id": "1", "title": "Heater not working", "location": "bedroom", "category": "heat"},
        {"id": "2", "title": "Hallway light flickering", "location": "hallway", "category": "electrical"},
    ]
    assert models.match_issue("nothing here", issues).issue is None
    assert models.match_issue("the night stand", issues).issue is None


# --------------------------------------------------- the other actions

def test_contact_attempt_is_labeled_tenant_reported(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    speech = services.log_contact_attempt(conn, "sink", "call", "left a voicemail")

    event = db.list_events(conn)[-1]
    assert event["type"] == "tenant_contact_claimed"
    assert event["verification"] == "tenant_reported"
    assert event["payload"] == {"method": "phone call", "note": "left a voicemail"}
    assert "can't verify" in speech


def test_confirm_fixed_closes_issue_and_tells_landlord(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    services.confirm_fixed(conn, "the sink")

    assert db.list_issues(conn)[0]["status"] == "closed"
    assert mailer.sent[-1]["subject"] == "Repair confirmed: Kitchen sink leaking"
    assert services.list_open_issues(conn) == "You have no open repair issues."


def test_dispute_fix_records_reason_and_tells_landlord(conn, mailer):
    services.report_issue(conn, "Heater not working", "living room")
    services.dispute_fix(conn, "heater", "it's cold again")

    assert db.list_issues(conn)[0]["status"] == "disputed"
    assert "Reason given: it's cold again" in mailer.sent[-1]["body"]


def test_history_summary(conn, mailer):
    services.report_issue(conn, "Heater not working", "living room")
    services.log_contact_attempt(conn, "heater", "text")

    speech = services.get_issue_history(conn, "heater")
    assert "was reported today" in speech
    assert "emailed once" in speech
    assert "hasn't responded" in speech
    assert "1 contact attempt" in speech


def test_history_finds_closed_issues_too(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    services.confirm_fixed(conn, "sink")
    assert "closed" in services.get_issue_history(conn, "sink")


def test_status_is_derived_from_events():
    events = [{"type": t} for t in ["issue_reported", "landlord_scheduled", "landlord_comment"]]
    assert models.derive_status(events) == "scheduled"


# ------------------------------------------------- through real MCP calls

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_tools_work_over_mcp(tmp_path, monkeypatch, mailer):
    monkeypatch.setattr(mcp_tools, "DATABASE_PATH", str(tmp_path / "mcp.db"))

    async with Client(mcp_tools.mcp) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {"report_issue", "list_open_issues", "get_issue_history", "log_contact_attempt",
                "confirm_fixed", "dispute_fix"} <= names

        result = await client.call_tool("report_issue", {"title": "Heater not working", "location": "bedroom"})
        assert "logged heater not working" in result.content[0].text

        result = await client.call_tool("list_open_issues", {})
        assert result.content[0].text.startswith("You have 1 open issue.")
