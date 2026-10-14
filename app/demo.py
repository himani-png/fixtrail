"""Demo data: a believable two-week repair history for screenshots and the video.

Real FixTrail records always use the server's current time. To show what a
record looks like after days or weeks, this module runs the normal FixTrail
actions with a simulated clock, in date order, and marks the database as demo
data. Every page and printed report then shows a "Demo data" banner, so a
demo record can never be mistaken for a real one.
"""

import struct
import zlib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import make_msgid

from app import db, inbound_email, services
from app.config import settings


def sample_png(width: int = 240, height: int = 160) -> bytes:
    """A small, real PNG image (a colour gradient), so no photo file is needed."""
    rows = b""
    for y in range(height):
        rows += b"\x00" + b"".join(bytes([(60 + x) % 256, (110 + y) % 256, 180]) for x in range(width))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def _photo_reply(conn, issue_id: str, sent_at: datetime) -> bytes:
    token = db.get_token_for_issue(conn, issue_id, "photo_reply")
    msg = EmailMessage()
    msg["From"] = f"{settings.tenant_name} <{settings.tenant_email}>"
    msg["To"] = f"photos+{token}@{settings.inbound_email_domain}"
    msg["Subject"] = "Re: FixTrail logged: Kitchen sink leaking"
    msg["Message-ID"] = make_msgid(domain="tenant-mail.example")
    msg.set_content("Photo of the leak under the sink.")
    msg.add_attachment(sample_png(), maintype="image", subtype="png", filename="sink-leak.png")
    return msg.as_bytes()


def seed_demo(conn, now: datetime | None = None) -> None:
    """Create four issues with a realistic mix of responses. The database must be empty."""
    if db.list_issues(conn):
        raise RuntimeError("The database already has issues. Demo data needs an empty database.")
    now = now or datetime.now(timezone.utc)

    def at(days_ago: float, hour: int, minute: int = 0) -> datetime:
        day = now - timedelta(days=days_ago)
        return day.replace(hour=hour, minute=minute, second=0, microsecond=0)

    def issue_id(title: str) -> str:
        return next(i["id"] for i in db.list_issues(conn) if i["title"] == title)

    def respond(title, action, **kwargs):
        return lambda: services.landlord_respond(conn, issue_id(title), action, **kwargs)

    in_two_days = (now + timedelta(days=2)).date().isoformat()
    mold_visit = (now - timedelta(days=25)).date().isoformat()

    # (when, what) in any order; they are run sorted by time so the chain stays chronological.
    script = [
        # Bathroom mold: a landlord who responded well. Closed.
        (at(30, 9, 12), lambda: services.report_issue(conn, "Mold on bathroom ceiling", "bathroom", "mold")),
        (at(29, 15, 40), respond("Mold on bathroom ceiling", "acknowledge")),
        (at(27, 11, 5), respond("Mold on bathroom ceiling", "schedule", when=mold_visit, time="10:00")),
        (at(25, 16, 30), respond("Mold on bathroom ceiling", "mark_fixed", note="Treated and repainted the ceiling")),
        (at(24, 19, 2), lambda: services.confirm_fixed(conn, "bathroom mold")),
        # Heater: no landlord response at all, despite reminders.
        (at(12, 21, 14), lambda: services.report_issue(conn, "Heater not working", "bedroom", "heat", "urgent")),
        (at(10, 9, 20), lambda: services.log_contact_attempt(conn, "heater", "call", "Left a voicemail")),
        (at(8, 18, 0), lambda: services.send_follow_up(conn, "heater")),
        (at(3, 19, 30), lambda: services.send_follow_up(conn, "heater")),
        # Kitchen sink: photo by email reply, landlord acknowledged and scheduled.
        (at(9, 8, 5), lambda: services.report_issue(conn, "Kitchen sink leaking", "kitchen", "water")),
        (at(9, 8, 22), lambda: inbound_email.process_email(
            conn, _photo_reply(conn, issue_id("Kitchen sink leaking"), at(9, 8, 22)))),
        (at(7, 12, 10), respond("Kitchen sink leaking", "acknowledge", note="Plumber booked")),
        (at(5, 9, 45), respond("Kitchen sink leaking", "schedule", when=in_two_days, time="09:30")),
        # Front door lock: both sides make claims FixTrail can't verify.
        (at(6, 22, 10), lambda: services.report_issue(conn, "Front door lock sticking", "front door", "lock", "urgent")),
        (at(4, 10, 20), respond("Front door lock sticking", "access_issue", note="Came at 10am, nobody answered")),
        (at(4, 18, 45), lambda: services.log_contact_attempt(
            conn, "front door lock", "text", "I was home all morning and the doorbell never rang")),
    ]

    original_clock, original_background = db.utc_now, services.RUN_IN_BACKGROUND
    clock = {"now": now}
    db.utc_now = lambda: clock["now"].isoformat()
    services.RUN_IN_BACKGROUND = False  # send each email at its simulated time
    try:
        db.get_or_create_property(conn)
        db.set_meta(conn, "demo_data", "true")
        for when, action in sorted(script, key=lambda step: step[0]):
            clock["now"] = when
            action()
    finally:
        db.utc_now, services.RUN_IN_BACKGROUND = original_clock, original_background
