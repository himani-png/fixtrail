"""FixTrail web server.

One process serves two things:
  * the MCP endpoint at /mcp (for Alexa+, the simulator, and MCP Inspector)
  * regular web pages (app/web.py)

Run with:  .venv\\Scripts\\python -m uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from mcp.server.transport_security import TransportSecuritySettings

from app.config import settings
from app.mcp_tools import mcp
from app.web import router as web_router


def transport_security() -> TransportSecuritySettings:
    """Which Host/Origin headers the MCP endpoint accepts.

    The SDK's DNS-rebinding protection only allows "localhost" by default, which
    would reject Alexa+ or the simulator calling https://your-domain/mcp. Keep the
    protection on, and add the public address from BASE_URL plus any extras
    (e.g. a temporary tunnel address) from ALLOWED_HOSTS.
    """
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
    origins = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]
    public = urlparse(settings.base_url)
    for host in [public.hostname, *settings.allowed_hosts]:
        if host and host not in ("localhost", "127.0.0.1"):
            hosts += [host, f"{host}:*"]
            origins += [f"https://{host}", f"http://{host}"]
    return TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                     allowed_hosts=hosts, allowed_origins=origins)


# Build the MCP Streamable HTTP app. It handles requests at /mcp.
mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", transport_security=transport_security())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The MCP session manager must be running while the server is up.
    # Mounted sub-apps don't get their own startup, so we start it here.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="FixTrail", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    # Landlord links carry a secret token in the URL. "no-referrer" stops the
    # browser from sending that URL to any other site the page links to.
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(web_router)


# Mount MCP last so the FastAPI routes above take priority.
app.mount("/", mcp_app)
