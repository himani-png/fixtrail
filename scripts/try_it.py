"""Talk to a running FixTrail server the way Alexa+ would, without MCP Inspector.

Start the server first (in another terminal):
    .venv\\Scripts\\python -m uvicorn app.main:app --reload

Then run:
    .venv\\Scripts\\python scripts\\try_it.py
    .venv\\Scripts\\python scripts\\try_it.py http://localhost:8000/mcp   # custom URL
"""

import asyncio
import sys

from mcp import Client

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000/mcp"

# (what the tenant might say, tool name, tool inputs)
SCENARIO = [
    ("Is FixTrail running?", "ping", {}),
    ("Alexa, the kitchen sink is leaking.", "report_issue",
     {"title": "Kitchen sink leaking", "location": "kitchen"}),
    ("Alexa, what's still broken?", "list_open_issues", {}),
    ("Alexa, I called the landlord about the sink.", "log_contact_attempt",
     {"issue": "the sink", "method": "call"}),
    ("Alexa, what's the history of the sink?", "get_issue_history", {"issue": "the sink"}),
    ("Alexa, the sink is fixed.", "confirm_fixed", {"issue": "the sink"}),
]


async def main() -> None:
    print(f"Connecting to {URL} ...\n")
    async with Client(URL) as client:
        tools = await client.list_tools()
        print("Tools available:", ", ".join(t.name for t in tools.tools), "\n")
        for said, tool, args in SCENARIO:
            result = await client.call_tool(tool, args)
            print(f"Tenant:   {said}")
            print(f"FixTrail: {result.content[0].text}\n")
    print("Done. Open the outbox/ folder to see the emails FixTrail sent.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"Could not talk to the server at {URL}: {error}")
        print("Is the server running? Start it with:")
        print("    .venv\\Scripts\\python -m uvicorn app.main:app --reload")
