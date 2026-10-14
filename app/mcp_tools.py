"""MCP tool definitions for FixTrail.

An MCP "tool" is a function that an AI assistant (like Alexa+) can call.
The function's name, docstring, and parameter descriptions are sent to the
assistant so it can decide when to call it. Each tool returns one short,
speakable sentence. The real work happens in app/services.py.
"""

from contextlib import closing
from typing import Annotated

from pydantic import Field

from mcp.server.mcpserver import MCPServer

from app import db, services

DATABASE_PATH: str | None = None  # None = use the path from .env; tests override

mcp = MCPServer(
    name="FixTrail",
    instructions=(
        "FixTrail keeps a shared, tamper-evident record of home repair issues "
        "between a tenant and their landlord. The person talking is the tenant. "
        "Every new issue is emailed to the landlord automatically. When the tenant "
        "refers to an issue, pass their own words (like 'the heater') as the issue; "
        "FixTrail matches it. Read tool results to the tenant as they are."
    ),
)

IssueRef = Annotated[str, Field(description="Which issue, in the tenant's words, e.g. 'the heater' or 'kitchen sink'.")]


def _conn():
    return closing(db.connect(DATABASE_PATH))


@mcp.tool()
def ping() -> str:
    """Check that the FixTrail server is running."""
    return "FixTrail is running."


@mcp.tool()
def report_issue(
    title: Annotated[str, Field(description="Short description of the problem, e.g. 'Kitchen sink leaking'.")],
    location: Annotated[str, Field(description="Where in the home, e.g. 'kitchen' or 'bathroom'.")],
    category: Annotated[str | None, Field(description="One of: heat, water, electrical, pest, mold, lock, appliance, other. Leave empty to auto-detect.")] = None,
    urgency: Annotated[str | None, Field(description="One of: emergency (danger, flooding, no heat in freezing weather, gas), urgent, routine. Default routine.")] = None,
) -> str:
    """Report a NEW repair problem in the tenant's home, such as a leak, no heat,
    a broken lock, or pests. Logs it and emails the landlord automatically.
    Use this when the tenant says something is broken or not working. If they
    are talking about a problem already reported, use another tool instead."""
    with _conn() as conn:
        return services.report_issue(conn, title, location, category, urgency)


@mcp.tool()
def list_open_issues() -> str:
    """List the tenant's open repair issues, how long each has been open, and the
    landlord's latest response. Use for questions like 'what's still broken?'"""
    with _conn() as conn:
        return services.list_open_issues(conn)


@mcp.tool()
def get_issue_history(issue: IssueRef) -> str:
    """Summarize the history of one repair issue: when it was reported, how many
    times the landlord was emailed, and how the landlord has responded."""
    with _conn() as conn:
        return services.get_issue_history(conn, issue)


@mcp.tool()
def log_contact_attempt(
    issue: IssueRef,
    method: Annotated[str, Field(description="How the tenant contacted the landlord: call, text, in person, email, or letter.")],
    note: Annotated[str | None, Field(description="Optional details, e.g. 'left a voicemail'.")] = None,
) -> str:
    """Record that the tenant contacted the landlord outside FixTrail, for example
    'I called my landlord about the sink'. FixTrail can't verify this, so it is
    labeled as tenant-reported."""
    with _conn() as conn:
        return services.log_contact_attempt(conn, issue, method, note)


@mcp.tool()
def confirm_fixed(issue: IssueRef) -> str:
    """The tenant confirms a repair is done and working, e.g. 'the sink is fixed'.
    Closes the issue and lets the landlord know."""
    with _conn() as conn:
        return services.confirm_fixed(conn, issue)


@mcp.tool()
def dispute_fix(
    issue: IssueRef,
    reason: Annotated[str, Field(description="What is still wrong, in the tenant's words.")],
) -> str:
    """The tenant says a repair is NOT actually done or the problem came back,
    e.g. 'the heater still isn't working'. Records it and tells the landlord."""
    with _conn() as conn:
        return services.dispute_fix(conn, issue, reason)
