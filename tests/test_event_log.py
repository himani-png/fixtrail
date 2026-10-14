"""Tests for the tamper-evident event log (Phase 2)."""

import json
import sqlite3

import pytest

from app import db


def add_events(conn, issue_id, n=3):
    return [
        db.append_event(conn, issue_id, "landlord_comment", "landlord", "verified", {"n": i})
        for i in range(n)
    ]


def drop_protection(conn):
    """Simulate an attacker with direct database access: remove the triggers."""
    conn.execute("DROP TRIGGER events_no_update")
    conn.execute("DROP TRIGGER events_no_delete")


def rewrite_and_rehash(conn):
    """Simulate a dishonest operator: recompute every hash so the chain
    looks perfectly valid again after editing history."""
    prev = db.GENESIS_HASH
    for row in conn.execute("SELECT * FROM events ORDER BY id").fetchall():
        fields = {**db._hashed_fields(row), "prev_hash": prev}
        new_hash = db.compute_hash(prev, fields)
        conn.execute("UPDATE events SET prev_hash = ?, hash = ? WHERE id = ?",
                     (prev, new_hash, row["id"]))
        prev = new_hash


# ------------------------------------------------------- appending events

def test_events_append_in_order_with_linked_hashes(conn, issue):
    events = add_events(conn, issue["id"], 3)

    assert [e["id"] for e in events] == [1, 2, 3]
    assert events[0]["prev_hash"] == db.GENESIS_HASH
    assert events[1]["prev_hash"] == events[0]["hash"]
    assert events[2]["prev_hash"] == events[1]["hash"]
    assert db.latest_fingerprint(conn) == (3, events[2]["hash"])


def test_timestamp_is_set_by_server(conn, issue):
    event = db.append_event(conn, issue["id"], "issue_reported", "tenant", "verified")
    assert event["created_at"].endswith("+00:00")  # UTC, generated here


def test_invalid_event_values_are_rejected(conn, issue):
    with pytest.raises(ValueError):
        db.append_event(conn, issue["id"], "made_up_type", "tenant", "verified")
    with pytest.raises(ValueError):
        db.append_event(conn, issue["id"], "issue_reported", "hacker", "verified")
    with pytest.raises(ValueError):
        db.append_event(conn, issue["id"], "issue_reported", "tenant", "trust_me")


# ------------------------------------------------------ verifying the chain

def test_untouched_chain_verifies(conn, issue):
    add_events(conn, issue["id"], 5)
    assert db.verify_chain(conn) == {"ok": True, "count": 5}


def test_empty_chain_verifies(conn):
    assert db.verify_chain(conn) == {"ok": True, "count": 0}


# ------------------------------------------------- triggers block changes

def test_update_is_blocked(conn, issue):
    add_events(conn, issue["id"], 1)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE events SET payload = '{}' WHERE id = 1")


def test_delete_is_blocked(conn, issue):
    add_events(conn, issue["id"], 1)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM events WHERE id = 1")


# ---------------------------------------- tampering is detected anyway

def test_edited_event_is_detected(conn, issue):
    add_events(conn, issue["id"], 3)
    drop_protection(conn)
    conn.execute("UPDATE events SET payload = ? WHERE id = 2", (json.dumps({"n": 999}),))

    result = db.verify_chain(conn)
    assert result["ok"] is False
    assert result["broken_at"] == 2


def test_backdated_event_is_detected(conn, issue):
    add_events(conn, issue["id"], 3)
    drop_protection(conn)
    conn.execute("UPDATE events SET created_at = '2020-01-01T00:00:00+00:00' WHERE id = 1")

    assert db.verify_chain(conn)["broken_at"] == 1


def test_deleted_event_is_detected(conn, issue):
    add_events(conn, issue["id"], 3)
    drop_protection(conn)
    conn.execute("DELETE FROM events WHERE id = 2")

    result = db.verify_chain(conn)
    assert result["ok"] is False
    assert result["broken_at"] == 2
    assert "missing" in result["reason"]


# ----------------------------------- fingerprints catch a full rewrite

def test_fingerprint_matches_untouched_record(conn, issue):
    events = add_events(conn, issue["id"], 3)
    result = db.check_fingerprint(conn, 2, events[1]["hash"])
    assert result["match"] is True


def test_fingerprint_check_ignores_case_and_spaces(conn, issue):
    events = add_events(conn, issue["id"], 1)
    assert db.check_fingerprint(conn, 1, f"  {events[0]['hash'].upper()} ")["match"] is True


def test_rewritten_and_rehashed_log_fails_old_fingerprint(conn, issue):
    events = add_events(conn, issue["id"], 3)
    old_fingerprint = events[2]["hash"]  # what an email captured at event #3

    drop_protection(conn)
    conn.execute("UPDATE events SET payload = ? WHERE id = 1", (json.dumps({"n": "rewritten"}),))
    rewrite_and_rehash(conn)

    # The operator's own check is fooled...
    assert db.verify_chain(conn)["ok"] is True
    # ...but the fingerprint sitting in someone's inbox is not.
    result = db.check_fingerprint(conn, 3, old_fingerprint)
    assert result["match"] is False


def test_fingerprint_for_missing_event(conn, issue):
    assert db.check_fingerprint(conn, 42, "abc")["match"] is False


# --------------------------------------------------------------- tokens

def test_tokens_are_long_random_and_purpose_specific(conn, issue):
    token = db.create_token(conn, issue["id"], "landlord")
    assert len(token) >= 40
    assert db.lookup_token(conn, token, "landlord") == issue["id"]
    assert db.lookup_token(conn, token, "photo_reply") is None
    assert db.lookup_token(conn, "guess", "landlord") is None
