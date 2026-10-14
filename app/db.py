"""Database schema and the tamper-evident event log.

Key ideas:
  * `events` is append-only. The app never UPDATEs or DELETEs it, and
    SQLite triggers refuse those statements even if someone tries.
  * Each event stores `prev_hash` (the previous event's hash) and its own
    `hash`. Changing any old event breaks every hash after it: a "hash chain".
  * The newest hash is the record's "fingerprint". It goes into every email,
    so copies live in inboxes FixTrail can't change (see check_fingerprint).
"""

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone

from app.config import settings

GENESIS_HASH = "0" * 64  # the "previous hash" of the very first event

EVENT_TYPES = {
    "issue_reported",
    "landlord_notified",
    "follow_up_sent",
    "tenant_contact_claimed",
    "photo_added",
    "landlord_acknowledged",
    "landlord_scheduled",
    "landlord_marked_fixed",
    "landlord_comment",
    "access_issue",
    "tenant_confirmed_fixed",
    "tenant_disputed_fix",
    "repair_visit_detected",
}
ACTORS = {"tenant", "landlord", "system"}
# "landlord_reported" is the landlord-side twin of "tenant_reported": a claim
# the system records but cannot check (e.g. "I couldn't get access").
VERIFICATIONS = {"verified", "tenant_reported", "landlord_reported"}
TOKEN_PURPOSES = {"landlord", "photo_reply"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    id             TEXT PRIMARY KEY,
    address        TEXT NOT NULL,
    tenant_name    TEXT NOT NULL,
    tenant_email   TEXT NOT NULL,
    landlord_name  TEXT NOT NULL,
    landlord_email TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS issues (
    id          TEXT PRIMARY KEY,
    property_id TEXT NOT NULL REFERENCES properties(id),
    title       TEXT NOT NULL,
    location    TEXT NOT NULL,
    category    TEXT NOT NULL,
    urgency     TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',  -- cached; events are the truth
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    issue_id     TEXT NOT NULL REFERENCES issues(id),
    type         TEXT NOT NULL,
    actor        TEXT NOT NULL,
    verification TEXT NOT NULL,
    payload      TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    prev_hash    TEXT NOT NULL,
    hash         TEXT NOT NULL
);

-- Secret links. purpose = 'landlord' (response page) or 'photo_reply'
-- (the Reply-To address for emailed photos).
CREATE TABLE IF NOT EXISTS tokens (
    token      TEXT PRIMARY KEY,
    issue_id   TEXT NOT NULL REFERENCES issues(id),
    purpose    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS events_no_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: UPDATE is not allowed');
END;

CREATE TRIGGER IF NOT EXISTS events_no_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'events are append-only: DELETE is not allowed');
END;
"""


def utc_now() -> str:
    """Current server time in UTC, e.g. '2026-10-14T18:03:12.123456+00:00'."""
    return datetime.now(timezone.utc).isoformat()


DEFAULT_PATH: str | None = None  # tests point this at a temporary file


def connect(path: str | None = None) -> sqlite3.Connection:
    """Open the database and make sure all tables exist."""
    conn = sqlite3.connect(path or DEFAULT_PATH or settings.database_path, isolation_level=None)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["title"]
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


# ---------------------------------------------------------------- hashing

def canonical_json(data) -> str:
    """JSON with sorted keys and no extra spaces, so hashing is reproducible."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, fields: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(fields)).encode("utf-8")).hexdigest()


def _hashed_fields(row) -> dict:
    """The event fields covered by the hash (everything except `hash` itself)."""
    return {
        "id": row["id"],
        "issue_id": row["issue_id"],
        "type": row["type"],
        "actor": row["actor"],
        "verification": row["verification"],
        "payload": json.loads(row["payload"]),
        "created_at": row["created_at"],
        "prev_hash": row["prev_hash"],
    }


# ------------------------------------------------------------- event log

def append_event(
    conn: sqlite3.Connection,
    issue_id: str,
    type: str,
    actor: str,
    verification: str,
    payload: dict | None = None,
) -> dict:
    """Add one event to the end of the log and return it (with id and hash).

    The timestamp is always set here, by the server. Callers can't supply it.
    """
    if type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {type}")
    if actor not in ACTORS:
        raise ValueError(f"unknown actor: {actor}")
    if verification not in VERIFICATIONS:
        raise ValueError(f"unknown verification: {verification}")

    # BEGIN IMMEDIATE locks the database for writing, so two requests can't
    # both read the same "last event" and fork the chain.
    conn.execute("BEGIN IMMEDIATE")
    try:
        last = conn.execute("SELECT id, hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
        fields = {
            "id": (last["id"] + 1) if last else 1,
            "issue_id": issue_id,
            "type": type,
            "actor": actor,
            "verification": verification,
            # Round-trip through canonical JSON so what we hash is exactly
            # what we store and later re-read.
            "payload": json.loads(canonical_json(payload or {})),
            "created_at": utc_now(),
            "prev_hash": last["hash"] if last else GENESIS_HASH,
        }
        fields["hash"] = compute_hash(fields["prev_hash"], fields)
        conn.execute(
            "INSERT INTO events (id, issue_id, type, actor, verification, payload,"
            " created_at, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fields["id"], issue_id, type, actor, verification,
                canonical_json(fields["payload"]), fields["created_at"],
                fields["prev_hash"], fields["hash"],
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return fields


def list_events(conn: sqlite3.Connection, issue_id: str | None = None) -> list[dict]:
    if issue_id:
        rows = conn.execute("SELECT * FROM events WHERE issue_id = ? ORDER BY id", (issue_id,))
    else:
        rows = conn.execute("SELECT * FROM events ORDER BY id")
    return [{**dict(r), "payload": json.loads(r["payload"])} for r in rows]


def latest_fingerprint(conn: sqlite3.Connection) -> tuple[int, str] | None:
    """(event number, hash) of the newest event, for email footers."""
    row = conn.execute("SELECT id, hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
    return (row["id"], row["hash"]) if row else None


def verify_chain(conn: sqlite3.Connection, up_to: int | None = None) -> dict:
    """Recompute every hash and check the links between events.

    Returns {"ok": True, "count": N} if the record is intact, otherwise
    {"ok": False, "count": N, "broken_at": event_id, "reason": "..."} for
    the first broken entry.
    """
    query = "SELECT * FROM events ORDER BY id"
    params: tuple = ()
    if up_to is not None:
        query = "SELECT * FROM events WHERE id <= ? ORDER BY id"
        params = (up_to,)

    expected_prev = GENESIS_HASH
    expected_id = 1
    count = 0
    for row in conn.execute(query, params):
        count += 1
        if row["id"] != expected_id:
            return _broken(count, expected_id, f"event #{expected_id} is missing")
        if row["prev_hash"] != expected_prev:
            return _broken(count, row["id"], "link to the previous event is broken")
        if compute_hash(row["prev_hash"], _hashed_fields(row)) != row["hash"]:
            return _broken(count, row["id"], "contents were changed after it was recorded")
        expected_prev = row["hash"]
        expected_id += 1
    return {"ok": True, "count": count}


def _broken(count: int, event_id: int, reason: str) -> dict:
    return {"ok": False, "count": count, "broken_at": event_id, "reason": reason}


def check_fingerprint(conn: sqlite3.Connection, event_id: int, fingerprint: str) -> dict:
    """Compare a fingerprint copied from an old email with the record today.

    If the log was rewritten and every hash recomputed, verify_chain() can
    still pass, but the stored hash for this event will no longer equal the
    fingerprint the email captured at the time.
    """
    fingerprint = fingerprint.strip().lower()
    row = conn.execute("SELECT hash FROM events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return {"match": False, "reason": f"event #{event_id} does not exist in the record"}
    if row["hash"] != fingerprint:
        return {"match": False, "reason": "the record no longer matches this fingerprint"}
    chain = verify_chain(conn, up_to=event_id)
    if not chain["ok"]:
        return {"match": False, "reason": f"fingerprint matches, but {chain['reason']} (event #{chain['broken_at']})"}
    return {"match": True, "reason": f"the record up to event #{event_id} matches this fingerprint"}


# ------------------------------------------------- properties and issues

def get_or_create_property(conn: sqlite3.Connection) -> dict:
    """The hackathon version has one property, configured in .env."""
    row = conn.execute("SELECT * FROM properties LIMIT 1").fetchone()
    if row:
        return dict(row)
    prop = {
        "id": str(uuid.uuid4()),
        "address": settings.property_address,
        "tenant_name": settings.tenant_name,
        "tenant_email": settings.tenant_email,
        "landlord_name": settings.landlord_name,
        "landlord_email": settings.landlord_email,
    }
    conn.execute(
        "INSERT INTO properties (id, address, tenant_name, tenant_email, landlord_name,"
        " landlord_email) VALUES (:id, :address, :tenant_name, :tenant_email,"
        " :landlord_name, :landlord_email)",
        prop,
    )
    return prop


def create_issue(conn, property_id, title, location, category="other", urgency="routine") -> dict:
    issue = {
        "id": str(uuid.uuid4()),
        "property_id": property_id,
        "title": title,
        "location": location,
        "category": category,
        "urgency": urgency,
        "status": "open",
        "created_at": utc_now(),
    }
    conn.execute(
        "INSERT INTO issues (id, property_id, title, location, category, urgency, status,"
        " created_at) VALUES (:id, :property_id, :title, :location, :category, :urgency,"
        " :status, :created_at)",
        issue,
    )
    return issue


def get_issue(conn: sqlite3.Connection, issue_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
    return dict(row) if row else None


def list_issues(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM issues ORDER BY created_at")]


def set_issue_status(conn: sqlite3.Connection, issue_id: str, status: str) -> None:
    """Update the cached status. (Allowed: only `events` is append-only.)"""
    conn.execute("UPDATE issues SET status = ? WHERE id = ?", (status, issue_id))


# ------------------------------------------------------------------ tokens

def create_token(conn: sqlite3.Connection, issue_id: str, purpose: str) -> str:
    if purpose not in TOKEN_PURPOSES:
        raise ValueError(f"unknown token purpose: {purpose}")
    token = secrets.token_urlsafe(32)  # ~256 bits of randomness: unguessable
    conn.execute(
        "INSERT INTO tokens (token, issue_id, purpose, created_at) VALUES (?, ?, ?, ?)",
        (token, issue_id, purpose, utc_now()),
    )
    return token


def get_token_for_issue(conn: sqlite3.Connection, issue_id: str, purpose: str) -> str | None:
    row = conn.execute(
        "SELECT token FROM tokens WHERE issue_id = ? AND purpose = ? ORDER BY created_at LIMIT 1",
        (issue_id, purpose),
    ).fetchone()
    return row["token"] if row else None


def database_path(conn: sqlite3.Connection) -> str:
    """The file behind a connection, so background jobs can open their own."""
    return conn.execute("PRAGMA database_list").fetchone()["file"]


def lookup_token(conn: sqlite3.Connection, token: str, purpose: str) -> str | None:
    """Return the issue id for a valid token, or None."""
    row = conn.execute(
        "SELECT issue_id FROM tokens WHERE token = ? AND purpose = ?", (token, purpose)
    ).fetchone()
    return row["issue_id"] if row else None
