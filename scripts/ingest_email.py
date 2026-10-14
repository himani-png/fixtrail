"""Process photo-reply emails saved as .eml files in inbox/ (local testing).

    .venv\\Scripts\\python scripts\\ingest_email.py              # every .eml in inbox/
    .venv\\Scripts\\python scripts\\ingest_email.py some.eml     # one file

Accepted emails move to inbox/processed/, rejected ones to inbox/rejected/,
so running it again doesn't process them twice. In production, AWS SES
receives the real emails and calls the same code (Phase 7).
"""

import shutil
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, inbound_email, services  # noqa: E402

INBOX = Path("inbox")


def main() -> None:
    # A one-off script: send the confirmation email right away, not in the background.
    services.RUN_IN_BACKGROUND = False
    files = [Path(p) for p in sys.argv[1:]] or sorted(INBOX.glob("*.eml"))
    if not files:
        print(f"No .eml files found in {INBOX.resolve()}")
        print("Create a test reply with: .venv\\Scripts\\python scripts\\make_test_reply.py")
        return

    with closing(db.connect()) as conn:
        for path in files:
            result = inbound_email.process_email(conn, path.read_bytes())
            status = "ACCEPTED" if result.accepted else "REJECTED"
            print(f"{status}  {path.name}: {result.reason}")
            for note in result.skipped:
                print(f"          skipped: {note}")
            if path.parent.resolve() == INBOX.resolve():
                target = INBOX / ("processed" if result.accepted else "rejected")
                target.mkdir(exist_ok=True)
                shutil.move(str(path), target / path.name)


if __name__ == "__main__":
    main()
