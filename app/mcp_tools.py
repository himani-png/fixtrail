"""MCP tool definitions for FixTrail.

An MCP "tool" is a function that an AI assistant (like Alexa+) can call.
The function's name, docstring, and parameter types are sent to the
assistant so it can decide when to call it. Return short, speakable text.
"""

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(
    name="FixTrail",
    instructions=(
        "FixTrail keeps a shared, tamper-evident record of home repair issues "
        "between a tenant and their landlord."
    ),
)


@mcp.tool()
def ping() -> str:
    """Check that the FixTrail server is running."""
    return "FixTrail is running."
