"""Demo: a dishonest operator rewrites history, and an old email catches it.

This plays the attacker with full database access. It quietly moves the first
issue's report date a week later (as if the tenant had reported it late), then
recomputes every hash so FixTrail's own chain check still passes. A fingerprint
from an old email in outbox/ no longer matches, which exposes the rewrite.

    .venv\\Scripts\\python scripts\\tamper_demo.py           # explain what it will do
    .venv\\Scripts\\python scripts\\tamper_demo.py --yes     # do it (backs up the database first)
    .venv\\Scripts\\python scripts\\tamper_demo.py --restore # put the original record back

For the video: run with --yes, open /verify (it still says "Record intact"),
then paste the event number and fingerprint this script prints. It fails.
"""

import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402

BACKUP = Path(settings.database_path + ".before-tamper")


def latest_email_fingerprint() -> tuple[int, str, str] | None:
    """(event number, fingerprint, file name) from the newest email in outbox/."""
    found = []
    for path in Path("outbox").glob("*.eml"):
        text = path.read_text(encoding="utf-8", errors="replace")
        number = re.search(r"Record fingerprint after event #(\d+)", text)
        full = re.search(r"Full fingerprint:\s*\n([0-9a-f]{64})", text)
        if number and full:
            found.append((int(number.group(1)), full.group(1), path.name))
    return max(found) if found else None


def copy_database(source: str, target: str) -> None:
    """SQLite's backup API copies safely even while the server has the file open."""
    with closing(sqlite3.connect(source)) as src, closing(sqlite3.connect(target)) as dst:
        src.backup(dst)


def rewrite_history(conn) -> dict:
    first = conn.execute("SELECT * FROM events WHERE type = 'issue_reported' ORDER BY id LIMIT 1").fetchone()
    if first is None:
        raise SystemExit("No issues in the record yet. Run scripts/seed.py --demo first.")
    moved = (datetime.fromisoformat(first["created_at"]) + timedelta(days=7)).isoformat()

    # The attacker removes the append-only protection...
    conn.execute("DROP TRIGGER IF EXISTS events_no_update")
    conn.execute("DROP TRIGGER IF EXISTS events_no_delete")
    conn.execute("UPDATE events SET created_at = ? WHERE id = ?", (moved, first["id"]))
    conn.execute("UPDATE issues SET created_at = ? WHERE id = ?", (moved, first["issue_id"]))
    # ...recomputes every hash so the chain looks perfect...
    prev = db.GENESIS_HASH
    for row in conn.execute("SELECT * FROM events ORDER BY id").fetchall():
        fields = {**db._hashed_fields(row), "prev_hash": prev}
        new_hash = db.compute_hash(prev, fields)
        conn.execute("UPDATE events SET prev_hash = ?, hash = ? WHERE id = ?", (prev, new_hash, row["id"]))
        prev = new_hash
    # ...and puts the protection back to cover their tracks.
    conn.executescript(db.SCHEMA)
    return {"event": first["id"], "title": first["payload"], "before": first["created_at"], "after": moved}


def main() -> None:
    path = settings.database_path
    if "--restore" in sys.argv:
        if not BACKUP.exists():
            raise SystemExit(f"No backup found at {BACKUP}.")
        copy_database(str(BACKUP), path)
        BACKUP.unlink()
        print(f"Restored the original record from {BACKUP.name}.")
        return

    if not Path(path).exists():
        raise SystemExit(f"No database at {path}. Run scripts/seed.py --demo first.")
    email = latest_email_fingerprint()
    if email is None:
        raise SystemExit("No FixTrail emails with fingerprints in outbox/. Run scripts/seed.py --demo first.")
    number, fingerprint, filename = email

    if "--yes" not in sys.argv:
        print(__doc__)
        print(f"It will modify {path} (after saving a backup to {BACKUP.name}).")
        print("Run again with --yes to continue.")
        return
    if BACKUP.exists():
        raise SystemExit(f"A backup already exists ({BACKUP.name}). Run --restore first.")

    copy_database(path, str(BACKUP))
    with closing(db.connect()) as conn:
        before = db.check_fingerprint(conn, number, fingerprint)["match"]
        change = rewrite_history(conn)
        chain = db.verify_chain(conn)
        after = db.check_fingerprint(conn, number, fingerprint)

    print("A dishonest operator just rewrote the record:")
    print(f"  event #{change['event']} report time moved {change['before'][:16]} -> {change['after'][:16]} UTC")
    print("  every hash recomputed, protections put back\n")
    print(f"FixTrail's own chain check:   {'Record intact' if chain['ok'] else 'BROKEN'} ({chain['count']} events)")
    print(f"Fingerprint from an old email: {'match' if before else 'NO MATCH'} before, "
          f"{'match' if after['match'] else 'NO MATCH'} after\n")
    print(f"Show it on the verify page ({settings.base_url}/verify):")
    print(f"  Event number: {number}")
    print(f"  Fingerprint:  {fingerprint}")
    print(f"  (from outbox/{filename})\n")
    print("Undo with: .venv\\Scripts\\python scripts\\tamper_demo.py --restore")


if __name__ == "__main__":
    main()
