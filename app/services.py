"""What FixTrail actually does.

The MCP tools (and, from Phase 4, the web pages) call these functions.
Each one takes a database connection and returns a short sentence that
Alexa can read aloud.
"""

import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from app import db, models, photos
from app.config import settings
from app.mailer import Mailer, get_mailer

log = logging.getLogger("fixtrail")

# Alexa+ requires tool replies in under 500 ms, and real email (SES) can be
# slower than that. So emails go to one background worker, and the tool
# replies right away. Tests set RUN_IN_BACKGROUND = False to send immediately.
RUN_IN_BACKGROUND = True
_worker = ThreadPoolExecutor(max_workers=1)

# Landlord emails queued but not yet sent, per issue, so answers can say
# "on its way" instead of "no email has gone out".
_pending_landlord_emails: dict[str, int] = {}
_pending_lock = threading.Lock()

mailer: Mailer | None = None  # created on first use; tests swap in a fake


def _mailer() -> Mailer:
    global mailer
    if mailer is None:
        mailer = get_mailer()
    return mailer


def _later(job, *args) -> None:
    if RUN_IN_BACKGROUND:
        _worker.submit(_safely, job, *args)
    else:
        job(*args)


def _safely(job, *args) -> None:
    try:
        job(*args)
    except Exception:
        log.exception("background job %s failed", job.__name__)


# ------------------------------------------------------------- wording

def _name(issue: dict) -> str:
    """'Kitchen sink leaking' -> 'kitchen sink leaking' for mid-sentence use."""
    title = issue["title"]
    return title[:1].lower() + title[1:]


def _join(items: list[str], word: str = "or") -> str:
    if len(items) <= 1:
        return "".join(items)
    if len(items) == 2:
        return f"{items[0]} {word} {items[1]}"
    return f"{', '.join(items[:-1])}, {word} {items[-1]}"


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _landlord_phrase(event: dict) -> str:
    """'acknowledged it 2 days ago' / 'scheduled a repair for Tuesday, October 20 at 10:00 AM'."""
    if event["type"] == "landlord_scheduled" and event["payload"].get("date"):
        return f"scheduled a repair for {models.nice_date(event['payload']['date'])}"
    phrase = models.LANDLORD_EVENT_PHRASES.get(event["type"], "responded")
    return f"{phrase} {models.ago(models.days_since(event['created_at']))}"


# --------------------------------------------------------------- emails

def fingerprint_footer(conn) -> str:
    """Footer for every email: the record's fingerprint at this moment.

    Copies of this sit in inboxes FixTrail can't edit, so a later rewrite of
    history would be caught by db.check_fingerprint().
    """
    latest = db.latest_fingerprint(conn)
    if latest is None:
        return ""
    event_id, full_hash = latest
    # Plain ASCII and short lines, so mail software never re-encodes or wraps
    # the fingerprint (which would make it hard to copy and paste).
    return (
        "\n\n--\n"
        f"Record fingerprint after event #{event_id}: {full_hash[:4]}...{full_hash[-3:]}\n"
        "Full fingerprint:\n"
        f"{full_hash}\n"
        "Keep this email. You can check the record against it at:\n"
        f"{settings.base_url}/verify\n"
    )


LANDLORD_MESSAGES = {
    "new_issue": ("Repair request: {title}", "{tenant} reported a repair issue through FixTrail."),
    "disputed": ("Repair not complete: {title}", "{tenant} says this repair is not complete.\nReason given: {reason}"),
    "confirmed_fixed": ("Repair confirmed: {title}", "{tenant} confirmed this repair is complete. Thank you."),
    "follow_up": ("Reminder: {title}", "This is a reminder about a repair issue {tenant} reported {reported_ago}. "
                  "It is still open."),
}


def _queue_landlord_email(conn, issue_id: str, kind: str, reason: str = "") -> None:
    with _pending_lock:
        _pending_landlord_emails[issue_id] = _pending_landlord_emails.get(issue_id, 0) + 1
    _later(_email_landlord, db.database_path(conn), issue_id, kind, reason)


def _landlord_email_pending(issue_id: str) -> bool:
    with _pending_lock:
        return _pending_landlord_emails.get(issue_id, 0) > 0


def _email_landlord(db_path: str, issue_id: str, kind: str, reason: str = "") -> None:
    """Email the landlord, then log that FixTrail sent it (a verified event)."""
    try:
        _send_landlord_email(db_path, issue_id, kind, reason)
    finally:
        with _pending_lock:
            _pending_landlord_emails[issue_id] = max(0, _pending_landlord_emails.get(issue_id, 0) - 1)


def _send_landlord_email(db_path: str, issue_id: str, kind: str, reason: str) -> None:
    conn = db.connect(db_path)
    try:
        issue = db.get_issue(conn, issue_id)
        prop = db.get_or_create_property(conn)
        token = db.get_token_for_issue(conn, issue_id, "landlord")
        subject_tpl, intro_tpl = LANDLORD_MESSAGES[kind]
        values = {
            "title": issue["title"],
            "tenant": prop["tenant_name"],
            "reason": reason,
            "reported_ago": models.ago(models.days_since(issue["created_at"])),
        }
        subject = subject_tpl.format(**values)
        body = (
            f"Hello {prop['landlord_name']},\n\n"
            f"{intro_tpl.format(**values)}\n\n"
            f"Issue: {issue['title']}\n"
            f"Location: {issue['location']}\n"
            f"Urgency: {issue['urgency']}\n"
            f"Reported: {issue['created_at'][:10]}\n"
            f"Property: {prop['address']}\n\n"
            f"Respond here (acknowledge, schedule a repair, mark fixed):\n"
            f"{settings.base_url}/respond/{token}\n"
            + fingerprint_footer(conn)
        )
        message_id = _mailer().send(prop["landlord_email"], subject, body)
        event_type = "follow_up_sent" if kind == "follow_up" else "landlord_notified"
        db.append_event(conn, issue_id, event_type, "system", "verified", {
            "kind": kind,
            "to": prop["landlord_email"],
            "subject": subject,
            "message_id": message_id,
            "body": body,
        })
    finally:
        conn.close()


def _email_tenant_confirmation(db_path: str, issue_id: str) -> None:
    """Tell the tenant the issue is logged. Replying with photos adds them
    (the inbound side is built in Phase 5b)."""
    conn = db.connect(db_path)
    try:
        issue = db.get_issue(conn, issue_id)
        prop = db.get_or_create_property(conn)
        token = db.get_token_for_issue(conn, issue_id, "photo_reply")
        body = (
            f"Hi {prop['tenant_name']},\n\n"
            f"FixTrail logged: {issue['title']} ({issue['location']}).\n"
            f"Your landlord has been emailed a copy.\n\n"
            f"Reply to this email with photos to add them to the record.\n"
            f"See the full timeline: {settings.base_url}/issues/{issue_id}\n"
            + fingerprint_footer(conn)
        )
        _mailer().send(
            prop["tenant_email"],
            f"FixTrail logged: {issue['title']}",
            body,
            reply_to=f"photos+{token}@{settings.inbound_email_domain}",
        )
    finally:
        conn.close()


def _email_tenant_photo_link(db_path: str, issue_id: str) -> None:
    """Two ways to add photos: reply to this email, or use the upload page."""
    conn = db.connect(db_path)
    try:
        issue = db.get_issue(conn, issue_id)
        prop = db.get_or_create_property(conn)
        token = db.get_token_for_issue(conn, issue_id, "photo_reply")
        body = (
            f"Hi {prop['tenant_name']},\n\n"
            f"To add photos to: {issue['title']} ({issue['location']})\n\n"
            f"Option 1: reply to this email with the photos attached.\n"
            f"Option 2: upload them here:\n"
            f"{settings.base_url}/issues/{issue_id}/photos\n"
            + fingerprint_footer(conn)
        )
        _mailer().send(
            prop["tenant_email"],
            f"Add photos: {issue['title']}",
            body,
            reply_to=f"photos+{token}@{settings.inbound_email_domain}",
        )
    finally:
        conn.close()


def _email_tenant_report(db_path: str, report_path: str, scope: str) -> None:
    conn = db.connect(db_path)
    try:
        prop = db.get_or_create_property(conn)
        body = (
            f"Hi {prop['tenant_name']},\n\n"
            f"Your FixTrail repair report ({scope}) is ready:\n"
            f"{settings.base_url}{report_path}\n\n"
            f"Open it in a browser and use Print to save it as a PDF.\n"
            + fingerprint_footer(conn)
        )
        _mailer().send(prop["tenant_email"], "Your FixTrail repair report", body)
    finally:
        conn.close()


# -------------------------------------------------------------- helpers

def _refresh_status(conn, issue_id: str) -> str:
    status = models.derive_status(db.list_events(conn, issue_id))
    db.set_issue_status(conn, issue_id, status)
    return status


def _open_issues(conn) -> list[dict]:
    return [i for i in db.list_issues(conn) if i["status"] != "closed"]


def queue_photo_reply_confirmation(conn, issue_id: str, added: int, skipped: list[str]) -> None:
    _later(_email_tenant_photo_result, db.database_path(conn), issue_id, added, list(skipped))


def _email_tenant_photo_result(db_path: str, issue_id: str, added: int, skipped: list[str]) -> None:
    """Reply to the tenant after they emailed photos: what was added, what wasn't."""
    conn = db.connect(db_path)
    try:
        issue = db.get_issue(conn, issue_id)
        prop = db.get_or_create_property(conn)
        if added:
            headline = f"{added} photo{'s' if added != 1 else ''} added to: {issue['title']}"
        else:
            headline = f"No photos were added to: {issue['title']}"
        lines = [f"Hi {prop['tenant_name']},", "", headline + "."]
        if skipped:
            lines += ["", "Not added:"] + [f"- {reason}" for reason in skipped]
            lines += ["", "FixTrail accepts JPEG and PNG photos up to "
                          f"{settings.max_photo_mb} MB each."]
        lines += ["", f"See the timeline: {settings.base_url}/issues/{issue_id}"]
        _mailer().send(prop["tenant_email"], headline, "\n".join(lines) + "\n" + fingerprint_footer(conn))
    finally:
        conn.close()


def find_issue(conn, query: str, include_closed: bool = False) -> tuple[dict | None, str | None]:
    """Return (issue, None) or (None, a short question/explanation to speak)."""
    issues = db.list_issues(conn) if include_closed else _open_issues(conn)
    if not issues:
        return None, "You don't have any open repair issues."
    match = models.match_issue(query, issues)
    if match.issue:
        return match.issue, None
    if match.candidates:
        return None, f"Do you mean {_join([_name(c) for c in match.candidates[:3]])}?"
    names = _join([_name(i) for i in issues[:5]], "and")
    return None, f"I couldn't find an issue matching \"{query}\". Your open issues are: {names}."


# ----------------------------------------------------------- the actions

def report_issue(conn, title: str, location: str, category: str | None = None,
                 urgency: str | None = None) -> str:
    title, location = title.strip(), location.strip()
    if not title:
        return "What's the problem? For example: the kitchen sink is leaking."
    if category not in models.CATEGORIES:
        category = models.guess_category(f"{title} {location}")
    if urgency not in models.URGENCIES:
        urgency = "routine"

    prop = db.get_or_create_property(conn)
    issue = db.create_issue(conn, prop["id"], title, location or "unspecified", category, urgency)
    db.create_token(conn, issue["id"], "landlord")
    db.create_token(conn, issue["id"], "photo_reply")
    db.append_event(conn, issue["id"], "issue_reported", "tenant", "verified", {
        "title": title, "location": issue["location"], "category": category, "urgency": urgency,
    })

    path = db.database_path(conn)
    _queue_landlord_email(conn, issue["id"], "new_issue")
    _later(_email_tenant_confirmation, path, issue["id"])
    return (f"Got it. I logged {_name(issue)} and I'm emailing your landlord now. "
            "I'm also emailing you, so you can reply with photos.")


def list_open_issues(conn) -> str:
    issues = _open_issues(conn)
    if not issues:
        return "You have no open repair issues."

    sentences = [f"You have {_plural(len(issues), 'open issue')}."]
    for issue in issues:
        events = db.list_events(conn, issue["id"])
        days = models.days_since(issue["created_at"])
        opened = "was reported today" if days <= 0 else f"has been open {models.describe_days(days)}"
        landlord_events = [e for e in events if e["actor"] == "landlord"]
        if landlord_events:
            last = landlord_events[-1]
            response = f"your landlord {_landlord_phrase(last)}"
        else:
            response = "no landlord response yet"
        if issue["status"] == "disputed":
            response += ", and you said the fix didn't work"
        sentences.append(f"{issue['title']} {opened}, {response}.")
    return " ".join(sentences)


def get_issue_history(conn, issue_query: str) -> str:
    issue, problem = find_issue(conn, issue_query)
    if issue is None:  # maybe they mean a closed issue
        issue, closed_problem = find_issue(conn, issue_query, include_closed=True)
        if issue is None:
            return problem or closed_problem

    events = db.list_events(conn, issue["id"])
    count = lambda *types: sum(1 for e in events if e["type"] in types)  # noqa: E731

    sentences = [f"{issue['title']} was reported {models.ago(models.days_since(issue['created_at']))}."]
    notices = count("landlord_notified", "follow_up_sent")
    if notices:
        sentences.append(f"Your landlord was emailed {_times(notices)}.")
    elif _landlord_email_pending(issue["id"]):
        sentences.append("An email to your landlord is on its way.")
    else:
        sentences.append("No email to your landlord has gone out yet.")

    landlord_events = [e for e in events if e["actor"] == "landlord"]
    if landlord_events:
        last = landlord_events[-1]
        sentences.append(f"Most recently, your landlord {_landlord_phrase(last)}.")
    else:
        sentences.append("Your landlord hasn't responded yet.")

    claims = count("tenant_contact_claimed")
    if claims:
        sentences.append(f"You also noted {_plural(claims, 'contact attempt')} yourself, "
                         "marked as unverified.")
    photos = count("photo_added")
    if photos:
        sentences.append(f"There {'is' if photos == 1 else 'are'} {_plural(photos, 'photo')} on record.")
    if issue["status"] == "closed":
        sentences.append("You confirmed it's fixed, so it's closed.")
    elif issue["status"] == "disputed":
        sentences.append("You said the fix didn't work.")
    return " ".join(sentences)


CONTACT_METHODS = {
    "call": "phone call", "phone": "phone call", "phone call": "phone call",
    "text": "text message", "text message": "text message", "sms": "text message",
    "in person": "in-person conversation", "in-person": "in-person conversation",
    "email": "email", "letter": "letter",
}


def log_contact_attempt(conn, issue_query: str, method: str, note: str | None = None) -> str:
    issue, problem = find_issue(conn, issue_query)
    if issue is None:
        return problem
    method_name = CONTACT_METHODS.get(method.strip().lower(), "contact attempt")
    payload = {"method": method_name}
    if note:
        payload["note"] = note.strip()
    db.append_event(conn, issue["id"], "tenant_contact_claimed", "tenant", "tenant_reported", payload)
    return (f"Noted. I've added your {method_name} about {_name(issue)} to the record. "
            "It's marked as something you reported, since I can't verify it.")


def confirm_fixed(conn, issue_query: str) -> str:
    issue, problem = find_issue(conn, issue_query)
    if issue is None:
        return problem
    db.append_event(conn, issue["id"], "tenant_confirmed_fixed", "tenant", "verified")
    _refresh_status(conn, issue["id"])
    _queue_landlord_email(conn, issue["id"], "confirmed_fixed")
    return f"Great, I've closed {_name(issue)} and I'm letting your landlord know."


def dispute_fix(conn, issue_query: str, reason: str) -> str:
    issue, problem = find_issue(conn, issue_query)
    if issue is None:
        return problem
    reason = reason.strip() or "No reason given."
    db.append_event(conn, issue["id"], "tenant_disputed_fix", "tenant", "verified", {"reason": reason})
    _refresh_status(conn, issue["id"])
    _queue_landlord_email(conn, issue["id"], "disputed", reason)
    return f"I've recorded that {_name(issue)} still isn't fixed, and I'm telling your landlord."


def send_follow_up(conn, issue_query: str) -> str:
    issue, problem = find_issue(conn, issue_query)
    if issue is None:
        return problem
    earlier = sum(1 for e in db.list_events(conn, issue["id"]) if e["type"] == "follow_up_sent")
    _queue_landlord_email(conn, issue["id"], "follow_up")
    extra = f" That's reminder number {earlier + 1}." if earlier else ""
    return f"I'm sending your landlord a reminder about {_name(issue)}.{extra}"


def get_photo_upload_link(conn, issue_query: str) -> str:
    issue, problem = find_issue(conn, issue_query)
    if issue is None:
        return problem
    _later(_email_tenant_photo_link, db.database_path(conn), issue["id"])
    return (f"I'm emailing you now. Reply to that email with photos of {_name(issue)}, "
            "or use the upload link inside.")


def generate_report(conn, issue_query: str | None = None) -> str:
    if issue_query and issue_query.strip():
        issue, problem = find_issue(conn, issue_query)
        if issue is None:  # reports can cover closed issues, too
            issue, closed_problem = find_issue(conn, issue_query, include_closed=True)
            if issue is None:
                return problem or closed_problem
        path, scope, spoken = f"/reports/{issue['id']}", issue["title"], f"for {_name(issue)}"
    else:
        if not db.list_issues(conn):
            return "There's nothing to report yet. You haven't reported any repair issues."
        path, scope, spoken = "/reports/all", "all issues", "covering all your issues"
    _later(_email_tenant_report, db.database_path(conn), path, scope)
    return f"Your repair report {spoken} is ready. I'm emailing you the link."


# -------------------------------------------- landlord responses (web)

class ActionError(ValueError):
    """A problem the person can fix, e.g. 'pick a date'. Shown on the page."""


LANDLORD_ACTIONS = {
    # action: (event type, verification)
    "acknowledge": ("landlord_acknowledged", "verified"),
    "schedule": ("landlord_scheduled", "verified"),
    "mark_fixed": ("landlord_marked_fixed", "verified"),
    "comment": ("landlord_comment", "verified"),
    # FixTrail didn't see the visit, so this is the landlord's own claim.
    "access_issue": ("access_issue", "landlord_reported"),
}


def landlord_respond(conn, issue_id: str, action: str, when: str | None = None,
                     time: str | None = None, note: str | None = None) -> str:
    """Record a landlord's button click and tell the tenant. Returns a
    confirmation message for the page."""
    if action not in LANDLORD_ACTIONS:
        raise ActionError("Unknown action.")
    event_type, verification = LANDLORD_ACTIONS[action]
    note = (note or "").strip()

    payload = {}
    if action == "schedule":
        try:
            day = date.fromisoformat(when or "")
        except ValueError:
            raise ActionError("Please pick a date for the repair.")
        payload["date"] = day.isoformat() + (f" {time}" if time else "")
    if action == "comment" and not note:
        raise ActionError("Please write a comment first.")
    if note:
        payload["note"] = note[:2000]

    event = db.append_event(conn, issue_id, event_type, "landlord", verification, payload)
    _refresh_status(conn, issue_id)
    _later(_email_tenant_update, db.database_path(conn), issue_id, event["id"])
    return "Thanks. Your response is recorded and the tenant has been notified."


def _email_tenant_update(db_path: str, issue_id: str, event_id: int) -> None:
    """Every landlord response goes straight to the tenant, too."""
    conn = db.connect(db_path)
    try:
        issue = db.get_issue(conn, issue_id)
        prop = db.get_or_create_property(conn)
        event = next(e for e in db.list_events(conn, issue_id) if e["id"] == event_id)
        body = (
            f"Hi {prop['tenant_name']},\n\n"
            f"Update on: {issue['title']}\n"
            f"{models.describe_event(event)}.\n\n"
            f"See the full timeline: {settings.base_url}/issues/{issue_id}\n"
            + fingerprint_footer(conn)
        )
        _mailer().send(prop["tenant_email"], f"Update on: {issue['title']}", body)
    finally:
        conn.close()


# ------------------------------------------------------------- photos

def add_photo(conn, issue_id: str, filename: str, data: bytes,
              source: str = "web_upload", extra: dict | None = None) -> dict:
    """Store a photo and log it with its fingerprint (sha256).

    The verified time is when FixTrail received the file, not any date
    stored inside the photo, which a phone can get wrong.
    """
    if not data:
        raise ActionError(f"{filename or 'The file'} is empty.")
    max_bytes = settings.max_photo_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ActionError(f"{filename} is larger than {settings.max_photo_mb} MB.")
    detected = photos.detect_image_type(data)
    if detected is None:
        raise ActionError(f"{filename} isn't a JPEG or PNG photo.")
    content_type, ext = detected

    sha256 = hashlib.sha256(data).hexdigest()
    key = photos.make_key(issue_id, sha256, ext)
    photos.get_store().save(key, data)
    payload = {
        "key": key,
        "sha256": sha256,
        "size": len(data),
        "content_type": content_type,
        "source": source,
        "original_filename": (filename or "")[:200],
        **(extra or {}),
    }
    return db.append_event(conn, issue_id, "photo_added", "tenant", "verified", payload)
