"""FixTrail web server.

One process serves two things:
  * the MCP endpoint at /mcp (for Alexa+ and MCP Inspector)
  * regular web pages (app/web.py)

Run with:  .venv\\Scripts\\python -m uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.mcp_tools import mcp
from app.web import router as web_router

# Build the MCP Streamable HTTP app. It handles requests at /mcp.
mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The MCP session manager must be running while the server is up.
    # Mounted sub-apps don't get their own startup, so we start it here.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="FixTrail", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(web_router)


# Mount MCP last so the FastAPI routes above take priority.
app.mount("/", mcp_app)
