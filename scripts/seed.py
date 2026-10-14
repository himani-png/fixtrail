"""Create the demo property (from .env) and, optionally, sample issues.

    python scripts/seed.py            # just the property
    python scripts/seed.py --sample   # property + two example issues
"""

import sys
from pathlib import Path

# Let this script import the `app` package when run from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402


def main() -> None:
    conn = db.connect()
    prop = db.get_or_create_property(conn)
    print(f"Property: {prop['address']}")
    print(f"  tenant:   {prop['tenant_name']} <{prop['tenant_email']}>")
    print(f"  landlord: {prop['landlord_name']} <{prop['landlord_email']}>")

    if "--sample" in sys.argv and not db.list_issues(conn):
        sink = db.create_issue(conn, prop["id"], "Kitchen sink leaking", "kitchen", "water", "urgent")
        db.append_event(conn, sink["id"], "issue_reported", "tenant", "verified",
                        {"title": sink["title"], "location": sink["location"]})
        heat = db.create_issue(conn, prop["id"], "Heater not working", "living room", "heat", "urgent")
        db.append_event(conn, heat["id"], "issue_reported", "tenant", "verified",
                        {"title": heat["title"], "location": heat["location"]})
        print("Added 2 sample issues.")

    result = db.verify_chain(conn)
    print(f"Events: {result['count']}, record intact: {result['ok']}")


if __name__ == "__main__":
    main()
