"""Building the printable repair report.

Everything here is calculated from the event log, so the report can never
say something the record doesn't support.
"""

from datetime import datetime, timezone

from app import db, models


def duration(start_iso: str, end_iso: str | None = None) -> str:
    """Human-friendly time between two timestamps: '12 minutes', '5 hours', '6 days'."""
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso) if end_iso else datetime.now(timezone.utc)
    minutes = max(0, int((end - start).total_seconds() // 60))
    if minutes == 0:
        return "under a minute"
    if minutes < 60:
        return "1 minute" if minutes == 1 else f"{minutes} minutes"
    hours = minutes // 60
    if hours < 48:
        return "1 hour" if hours == 1 else f"{hours} hours"
    return f"{hours // 24} days"


def issue_stats(issue: dict, events: list[dict]) -> dict:
    """The numbers a mediator or inspector would look for."""
    reported = issue["created_at"]
    landlord_events = [e for e in events if e["actor"] == "landlord"]
    closed = next((e for e in reversed(events) if e["type"] == "tenant_confirmed_fixed"), None)
    scheduled = [e for e in events if e["type"] == "landlord_scheduled"]

    first_response = (
        f"Landlord first responded after {duration(reported, landlord_events[0]['created_at'])}"
        if landlord_events else
        f"No landlord response in {duration(reported)}"
    )
    if issue["status"] == "closed" and closed:
        open_for = f"Closed after {duration(reported, closed['created_at'])}"
    else:
        open_for = f"Open for {duration(reported)}"

    return {
        "first_response": first_response,
        "open_for": open_for,
        "landlord_emails": sum(1 for e in events if e["type"] == "landlord_notified"),
        "reminders": sum(1 for e in events if e["type"] == "follow_up_sent"),
        "landlord_responses": len(landlord_events),
        "tenant_contact_claims": sum(1 for e in events if e["type"] == "tenant_contact_claimed"),
        "photos": sum(1 for e in events if e["type"] == "photo_added"),
        "scheduled_for": models.nice_date(scheduled[-1]["payload"].get("date"), with_year=True) if scheduled else None,
    }


def build_report(conn, issue_ids: list[str] | None = None) -> dict:
    """Data for one issue (issue_ids=[id]) or all issues (issue_ids=None)."""
    all_issues = db.list_issues(conn)
    issues = [i for i in all_issues if issue_ids is None or i["id"] in issue_ids]
    sections = []
    for issue in issues:
        events = db.list_events(conn, issue["id"])
        sections.append({
            "issue": {**issue, "status_label": models.STATUS_LABELS.get(issue["status"], issue["status"])},
            "stats": issue_stats(issue, events),
            "events": events,
        })
    return {
        "generated_at": db.utc_now(),
        "property": db.get_or_create_property(conn),
        "sections": sections,
        "chain": db.verify_chain(conn),
        "latest": db.latest_fingerprint(conn),
    }
