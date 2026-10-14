"""Create a realistic photo-reply email in inbox/, as if the tenant had replied
to a FixTrail email with a photo attached. For local testing only.

    .venv\\Scripts\\python scripts\\make_test_reply.py
    .venv\\Scripts\\python scripts\\make_test_reply.py --issue heater --photo C:\\path\\to\\photo.jpg
    .venv\\Scripts\\python scripts\\make_test_reply.py --from stranger@example.com   # should be rejected

Then process it with:  .venv\\Scripts\\python scripts\\ingest_email.py
"""

import argparse
import sys
from contextlib import closing
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, services  # noqa: E402
from app.demo import sample_png  # noqa: E402
from app.config import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--issue", default="", help="which issue, in everyday words (default: the newest open one)")
    parser.add_argument("--photo", help="path to a JPEG or PNG to attach (default: a generated sample image)")
    parser.add_argument("--from", dest="sender", help="sender address (default: the tenant's address)")
    args = parser.parse_args()

    with closing(db.connect()) as conn:
        prop = db.get_or_create_property(conn)
        open_issues = [i for i in db.list_issues(conn) if i["status"] != "closed"]
        if not open_issues:
            print("No open issues. Report one first (e.g. run scripts\\try_it.py).")
            return
        if args.issue:
            issue, problem = services.find_issue(conn, args.issue)
            if issue is None:
                print(problem)
                return
        else:
            issue = open_issues[-1]
        token = db.get_token_for_issue(conn, issue["id"], "photo_reply")

    if args.photo:
        photo_path = Path(args.photo)
        data, filename = photo_path.read_bytes(), photo_path.name
        subtype = "png" if filename.lower().endswith(".png") else "jpeg"
    else:
        data, filename, subtype = sample_png(), "photo.png", "png"

    msg = EmailMessage()
    msg["From"] = f"{prop['tenant_name']} <{args.sender or prop['tenant_email']}>"
    msg["To"] = f"photos+{token}@{settings.inbound_email_domain}"
    msg["Subject"] = f"Re: FixTrail logged: {issue['title']}"
    msg["Date"] = format_datetime(datetime.now(timezone.utc))
    msg["Message-ID"] = make_msgid(domain="tenant-mail.example")
    msg.set_content("Here is a photo of the problem.\n")
    msg.add_attachment(data, maintype="image", subtype=subtype, filename=filename)

    inbox = Path("inbox")
    inbox.mkdir(exist_ok=True)
    out = inbox / f"reply-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.eml"
    out.write_bytes(msg.as_bytes())
    print(f"Created {out} (reply about: {issue['title']}, from {args.sender or prop['tenant_email']})")
    print("Now run: .venv\\Scripts\\python scripts\\ingest_email.py")


if __name__ == "__main__":
    main()
