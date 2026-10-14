"""Set up the database.

    python scripts/seed.py            # just the property (from .env)
    python scripts/seed.py --demo     # property + a two-week demo history (empty database only)

Demo data uses simulated dates and is clearly marked as demo data on every
page and report. To start over, stop the server and delete fixtrail.db.
"""

import sys
from contextlib import closing
from pathlib import Path

# Let this script import the `app` package when run from the project root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, demo  # noqa: E402


def main() -> None:
    with closing(db.connect()) as conn:
        prop = db.get_or_create_property(conn)
        print(f"Property: {prop['address']}")
        print(f"  tenant:   {prop['tenant_name']} <{prop['tenant_email']}>")
        print(f"  landlord: {prop['landlord_name']} <{prop['landlord_email']}>")

        if "--demo" in sys.argv:
            if db.list_issues(conn):
                print("\nThe database already has issues, so no demo data was added.")
                print("To start fresh: stop the server, delete fixtrail.db, and run this again.")
                return
            demo.seed_demo(conn)
            print(f"\nAdded demo data: {len(db.list_issues(conn))} issues. Emails are in outbox/.")

        result = db.verify_chain(conn)
        print(f"Events: {result['count']}, record intact: {result['ok']}")


if __name__ == "__main__":
    main()
