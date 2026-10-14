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


def test_history_says_email_on_its_way_while_queued(conn, mailer, monkeypatch):
    queued = []
    monkeypatch.setattr(services, "_later", lambda job, *args: queued.append((job, args)))
    services.report_issue(conn, "Heater not working", "living room")
    assert "on its way" in services.get_issue_history(conn, "heater")

    for job, args in queued:  # now the worker sends them
        job(*args)
    assert "emailed once" in services.get_issue_history(conn, "heater")


def test_history_finds_closed_issues_too(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    services.confirm_fixed(conn, "sink")
    assert "closed" in services.get_issue_history(conn, "sink")


def test_follow_up_emails_landlord_and_logs_verified_event(conn, mailer):
    services.report_issue(conn, "Heater not working", "living room")
    speech = services.send_follow_up(conn, "heater")
    assert "reminder about heater not working" in speech

    last = db.list_events(conn)[-1]
    assert last["type"] == "follow_up_sent"
    assert last["verification"] == "verified"
    reminder = mailer.sent[-1]
    assert reminder["subject"] == "Reminder: Heater not working"
    assert "still open" in reminder["body"]
    assert "/respond/" in reminder["body"]

    assert "reminder number 2" in services.send_follow_up(conn, "heater")
    assert "emailed 3 times" in services.get_issue_history(conn, "heater")


def test_follow_up_for_closed_issue_is_refused(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    services.confirm_fixed(conn, "sink")
    assert "don't have any open" in services.send_follow_up(conn, "sink")


def test_photo_upload_link_email(conn, mailer):
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    speech = services.get_photo_upload_link(conn, "sink")
    assert "Reply to that email with photos" in speech

    issue = db.list_issues(conn)[0]
    email = mailer.sent[-1]
    assert email["to"] == "tenant@example.com"
    assert f"/issues/{issue['id']}/photos" in email["body"]
    assert email["reply_to"].startswith("photos+")


def test_generate_report_for_one_issue_and_all(conn, mailer):
    assert "nothing to report" in services.generate_report(conn)
    services.report_issue(conn, "Kitchen sink leaking", "kitchen")
    issue = db.list_issues(conn)[0]

    assert "for kitchen sink leaking is ready" in services.generate_report(conn, "sink")
    assert f"/reports/{issue['id']}" in mailer.sent[-1]["body"]

    assert "covering all your issues" in services.generate_report(conn)
    assert "/reports/all" in mailer.sent[-1]["body"]


def test_report_durations_and_stats():
    from app import reports
    assert reports.duration("2026-10-01T10:00:00+00:00", "2026-10-01T10:00:20+00:00") == "under a minute"
    assert reports.duration("2026-10-01T10:00:00+00:00", "2026-10-01T10:12:00+00:00") == "12 minutes"
    assert reports.duration("2026-10-01T10:00:00+00:00", "2026-10-01T15:30:00+00:00") == "5 hours"
    assert reports.duration("2026-10-01T10:00:00+00:00", "2026-10-07T11:00:00+00:00") == "6 days"

    issue = {"created_at": "2026-10-01T10:00:00+00:00", "status": "closed"}
    events = [
        {"type": "issue_reported", "actor": "tenant", "created_at": "2026-10-01T10:00:00+00:00", "payload": {}},
        {"type": "landlord_notified", "actor": "system", "created_at": "2026-10-01T10:00:01+00:00", "payload": {}},
        {"type": "landlord_scheduled", "actor": "landlord", "created_at": "2026-10-07T10:00:00+00:00",
         "payload": {"date": "2026-10-09 09:00"}},
        {"type": "tenant_confirmed_fixed", "actor": "tenant", "created_at": "2026-10-09T12:00:00+00:00", "payload": {}},
    ]
    stats = reports.issue_stats(issue, events)
    assert stats["first_response"] == "Landlord first responded after 6 days"
    assert stats["open_for"] == "Closed after 8 days"
    assert stats["scheduled_for"] == "Friday, October 9, 2026 at 9:00 AM"


def test_dates_are_easy_to_say():
    assert models.nice_date("2026-10-20 14:30") == "Tuesday, October 20 at 2:30 PM"
    assert models.nice_date("2026-10-20") == "Tuesday, October 20"
    assert models.nice_date("2026-10-20", with_year=True) == "Tuesday, October 20, 2026"


def test_status_is_derived_from_events():
    events = [{"type": t} for t in ["issue_reported", "landlord_scheduled", "landlord_comment"]]
    assert models.derive_status(events) == "scheduled"


# ------------------------------------------------- through real MCP calls

@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_tools_work_over_mcp(tmp_path, monkeypatch, mailer):
    monkeypatch.setattr(db, "DEFAULT_PATH", str(tmp_path / "mcp.db"))

    async with Client(mcp_tools.mcp) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert {"report_issue", "list_open_issues", "get_issue_history", "log_contact_attempt",
                "confirm_fixed", "dispute_fix", "send_follow_up", "get_photo_upload_link",
                "generate_report"} <= names

        result = await client.call_tool("report_issue", {"title": "Heater not working", "location": "bedroom"})
        assert "logged heater not working" in result.content[0].text

        result = await client.call_tool("list_open_issues", {})
        assert result.content[0].text.startswith("You have 1 open issue.")
