"""Web pages: the things voice can't do well.

  /                      tenant dashboard            (tenant passcode)
  /issues/{id}           timeline of one issue       (tenant passcode)
  /issues/{id}/photos    upload photos               (tenant passcode)
  /respond/{token}       landlord response page      (secret link, no login)
  /photos/{event_id}     a stored photo              (tenant, or landlord link)
  /reports/{id|all}      printable report            (tenant, or landlord link)
  /simulator             Alexa+ simulator            (tenant passcode)
  /verify                check the record            (anyone)
"""

import hashlib
import hmac
import json
import secrets
import time
from collections import defaultdict, deque
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import db, inbound_email, models, reports, services
from app.config import settings
from app.photos import get_store

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _is_demo_data() -> bool:
    with closing(db.connect()) as conn:
        return db.is_demo(conn)


# Every page and report can show a "Demo data" banner (see app/demo.py).
templates.env.globals["is_demo_data"] = _is_demo_data

COOKIE_NAME = "fixtrail_tenant"


# ---------------------------------------------------------- tenant login
# Demo-level security: one tenant, one passcode from .env. The cookie holds
# a hash of the passcode, so changing the passcode logs everyone out.

def _cookie_value() -> str:
    return hashlib.sha256(f"fixtrail-tenant:{settings.tenant_passcode}".encode()).hexdigest()


def is_tenant(request: Request) -> bool:
    return hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), _cookie_value())


def _to_login(request: Request) -> RedirectResponse:
    return RedirectResponse(f"/login?next={request.url.path}", status_code=303)


def _safe_next(path: str) -> str:
    """Only allow redirects within this site."""
    return path if path.startswith("/") and not path.startswith("//") else "/"


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"next": _safe_next(next), "error": None})


# Slow down passcode guessing: at most 10 wrong tries per address per 10 minutes.
MAX_FAILURES, FAILURE_WINDOW = 10, 600
_failures: dict[str, deque] = defaultdict(deque)


def _too_many_failures(client: str) -> bool:
    attempts = _failures[client]
    while attempts and attempts[0] < time.monotonic() - FAILURE_WINDOW:
        attempts.popleft()
    return len(attempts) >= MAX_FAILURES


@router.post("/login")
def login(request: Request, passcode: str = Form(""), next: str = Form("/")):
    client = request.client.host if request.client else "unknown"
    if _too_many_failures(client):
        return templates.TemplateResponse(
            request, "login.html", {"next": _safe_next(next), "error": "Too many attempts. Try again in a few minutes."},
            status_code=429,
        )
    if not hmac.compare_digest(passcode, settings.tenant_passcode):
        _failures[client].append(time.monotonic())
        return templates.TemplateResponse(
            request, "login.html", {"next": _safe_next(next), "error": "That passcode isn't right."},
            status_code=401,
        )
    _failures.pop(client, None)
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(COOKIE_NAME, _cookie_value(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30,
                        secure=settings.base_url.startswith("https://"))
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response


# ---------------------------------------------------------- view helpers

def _when(iso: str) -> str:
    """'2026-10-14T19:44:33.1+00:00' -> '2026-10-14 19:44 UTC'"""
    return f"{iso[:10]} {iso[11:16]} UTC"


def _timeline(events: list[dict], landlord_token: str | None = None) -> list[dict]:
    rows = []
    for e in events:
        p = e["payload"]
        row = {
            "id": e["id"],
            "when": _when(e["created_at"]),
            "actor": e["actor"],
            "verification": e["verification"],
            "label": models.VERIFICATION_LABELS[e["verification"]],
            "text": models.describe_event(e),
            "photo_url": None,
            "details": [],
            "hash": e["hash"],
        }
        if e["type"] == "photo_added":
            row["photo_url"] = f"/photos/{e['id']}" + (f"?t={landlord_token}" if landlord_token else "")
            row["details"].append(("Photo fingerprint (sha256)", p.get("sha256")))
            if p.get("source") == "email_reply":
                row["details"].append(("Emailed by", p.get("sender")))
                verdicts = p.get("verdicts")
                if isinstance(verdicts, dict):
                    verdicts = ", ".join(f"{k.upper()} {v}" for k, v in sorted(verdicts.items()))
                row["details"].append(("Email checks", verdicts))
                row["details"].append(("Email Message-ID", p.get("message_id")))
        elif e["type"] in ("landlord_notified", "follow_up_sent"):
            row["details"].append(("Sent to", p.get("to")))
            row["details"].append(("Message-ID", p.get("message_id")))
        rows.append(row)
    return rows


def _issue_summary(conn, issue: dict) -> dict:
    events = db.list_events(conn, issue["id"])
    days = models.days_since(issue["created_at"])
    return {
        **issue,
        "status_label": models.STATUS_LABELS.get(issue["status"], issue["status"]),
        "days_open": models.describe_days(days) if days > 0 else "today",
        "reported": _when(issue["created_at"]),
        "photo_count": sum(1 for e in events if e["type"] == "photo_added"),
        "landlord_responses": sum(1 for e in events if e["actor"] == "landlord"),
    }


# ---------------------------------------------------------- tenant pages

@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    if not is_tenant(request):
        return _to_login(request)
    with closing(db.connect()) as conn:
        issues = [_issue_summary(conn, i) for i in db.list_issues(conn)]
        prop = db.get_or_create_property(conn)
        chain = db.verify_chain(conn)
    open_issues = [i for i in issues if i["status"] != "closed"]
    closed_issues = [i for i in issues if i["status"] == "closed"]
    return templates.TemplateResponse(request, "dashboard.html", {
        "property": prop, "open_issues": open_issues[::-1], "closed_issues": closed_issues[::-1],
        "chain": chain,
    })


@router.get("/issues/{issue_id}", response_class=HTMLResponse)
def issue_page(request: Request, issue_id: str, added: int = 0):
    if not is_tenant(request):
        return _to_login(request)
    with closing(db.connect()) as conn:
        issue = db.get_issue(conn, issue_id)
        if issue is None:
            return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
        summary = _issue_summary(conn, issue)
        rows = _timeline(db.list_events(conn, issue_id))
    message = f"{added} photo{'s' if added != 1 else ''} added to the record." if added else None
    return templates.TemplateResponse(request, "issue.html", {
        "issue": summary, "timeline": rows, "message": message,
    })


@router.get("/issues/{issue_id}/photos", response_class=HTMLResponse)
def upload_page(request: Request, issue_id: str):
    if not is_tenant(request):
        return _to_login(request)
    with closing(db.connect()) as conn:
        issue = db.get_issue(conn, issue_id)
    if issue is None:
        return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
    return templates.TemplateResponse(request, "upload.html", {
        "issue": issue, "error": None, "max_mb": settings.max_photo_mb,
    })


@router.post("/issues/{issue_id}/photos")
async def upload_photos(request: Request, issue_id: str, files: list[UploadFile] = File(...)):
    if not is_tenant(request):
        return _to_login(request)
    with closing(db.connect()) as conn:
        issue = db.get_issue(conn, issue_id)
        if issue is None:
            return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
        added = 0
        try:
            for upload in files:
                if not upload.filename:
                    continue
                data = await upload.read()
                services.add_photo(conn, issue_id, upload.filename, data)
                added += 1
        except services.ActionError as error:
            return templates.TemplateResponse(request, "upload.html", {
                "issue": issue, "max_mb": settings.max_photo_mb,
                "error": f"{error}" + (f" ({added} photo(s) before it were saved.)" if added else ""),
            }, status_code=400)
    if added == 0:
        return templates.TemplateResponse(request, "upload.html", {
            "issue": issue, "max_mb": settings.max_photo_mb, "error": "Please choose at least one photo.",
        }, status_code=400)
    return RedirectResponse(f"/issues/{issue_id}?added={added}", status_code=303)


@router.get("/photos/{event_id}")
def photo(request: Request, event_id: int, t: str = ""):
    with closing(db.connect()) as conn:
        event = next((e for e in db.list_events(conn) if e["id"] == event_id and e["type"] == "photo_added"), None)
        if event is None:
            return Response(status_code=404)
        allowed = is_tenant(request) or (t and db.lookup_token(conn, t, "landlord") == event["issue_id"])
    if not allowed:
        return Response(status_code=403)
    data = get_store().load(event["payload"]["key"])
    return Response(data, media_type=event["payload"]["content_type"])


# ---------------------------------------------------------- landlord page

def _respond_context(conn, token: str, issue_id: str, message=None, error=None) -> dict:
    issue = db.get_issue(conn, issue_id)
    return {
        "token": token,
        "issue": _issue_summary(conn, issue),
        "property": db.get_or_create_property(conn),
        "timeline": _timeline(db.list_events(conn, issue_id), landlord_token=token),
        "message": message,
        "error": error,
    }


@router.get("/respond/{token}", response_class=HTMLResponse)
def respond_page(request: Request, token: str, done: int = 0):
    with closing(db.connect()) as conn:
        issue_id = db.lookup_token(conn, token, "landlord")
        if issue_id is None:
            return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
        message = "Thanks. Your response is recorded and the tenant has been notified." if done else None
        return templates.TemplateResponse(request, "respond.html", _respond_context(conn, token, issue_id, message))


@router.post("/respond/{token}")
def respond(request: Request, token: str, action: str = Form(...), when: str = Form(""),
            time: str = Form(""), note: str = Form("")):
    with closing(db.connect()) as conn:
        issue_id = db.lookup_token(conn, token, "landlord")
        if issue_id is None:
            return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
        try:
            services.landlord_respond(conn, issue_id, action, when or None, time or None, note or None)
        except services.ActionError as error:
            return templates.TemplateResponse(
                request, "respond.html", _respond_context(conn, token, issue_id, error=str(error)),
                status_code=400,
            )
    # Redirect after posting, so refreshing the page doesn't submit twice.
    return RedirectResponse(f"/respond/{token}?done=1", status_code=303)


# ------------------------------------------------------------ report page

@router.get("/reports/{issue_id}", response_class=HTMLResponse)
def report_page(request: Request, issue_id: str, t: str = ""):
    """Printable report. 'all' covers every issue (tenant only); a single
    issue's report is also open to the landlord through their secret link."""
    with closing(db.connect()) as conn:
        landlord_ok = bool(t) and issue_id != "all" and db.lookup_token(conn, t, "landlord") == issue_id
        if not (is_tenant(request) or landlord_ok):
            return _to_login(request) if not t else Response(status_code=403)
        if issue_id != "all" and db.get_issue(conn, issue_id) is None:
            return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)
        report = reports.build_report(conn, None if issue_id == "all" else [issue_id])
    landlord_token = t if landlord_ok and not is_tenant(request) else None
    for section in report["sections"]:
        section["timeline"] = _timeline(section["events"], landlord_token=landlord_token)
    return templates.TemplateResponse(request, "report.html", {
        **report,
        "generated": _when(report["generated_at"]),
        "scope": "All issues" if issue_id == "all" else report["sections"][0]["issue"]["title"],
        "base_url": settings.base_url,
    })


# ------------------------------------------------------- Alexa+ simulator

SIM_COOKIE = "fixtrail_sim"
_simulator = None  # created on first use; tests swap in a fake


def get_simulator():
    global _simulator
    if _simulator is None:
        from app.simulator import Simulator
        _simulator = Simulator()
    return _simulator


@router.get("/simulator", response_class=HTMLResponse)
def simulator_page(request: Request):
    """Stands in for Alexa+: the tenant talks, an agent calls FixTrail's MCP tools."""
    if not is_tenant(request):
        return _to_login(request)
    from app.simulator import mode_label
    response = templates.TemplateResponse(request, "simulator.html", {"mode": mode_label()})
    if not request.cookies.get(SIM_COOKIE):
        response.set_cookie(SIM_COOKIE, secrets.token_urlsafe(16), httponly=True, samesite="lax")
    return response


@router.post("/simulator/ask")
async def simulator_ask(request: Request):
    if not is_tenant(request):
        return JSONResponse({"error": "Please log in again."}, status_code=401)
    body = await request.json()
    text = str(body.get("text", "")).strip()[:500]
    if not text:
        return JSONResponse({"error": "Say or type something first."}, status_code=400)
    session = request.cookies.get(SIM_COOKIE) or "default"
    try:
        # The agent makes blocking calls (to the model and to /mcp), so run it
        # in a worker thread and keep the server free to answer those calls.
        result = await run_in_threadpool(get_simulator().ask, session, text)
    except Exception as error:  # e.g. missing AWS credentials in bedrock mode
        return JSONResponse({"error": f"The assistant couldn't answer: {error}"}, status_code=502)
    return JSONResponse(result)


@router.post("/simulator/reset")
def simulator_reset(request: Request):
    if not is_tenant(request):
        return JSONResponse({"error": "Please log in again."}, status_code=401)
    get_simulator().reset(request.cookies.get(SIM_COOKIE) or "default")
    return JSONResponse({"ok": True})


# ------------------------------------------------------- policy pages

@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return templates.TemplateResponse(request, "privacy.html", {})


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return templates.TemplateResponse(request, "terms.html", {})


# ------------------------------------------- inbound email (production)

@router.post("/inbound/ses")
async def inbound_ses(request: Request, secret: str = ""):
    """Amazon SNS calls this when SES receives a photo-reply email.

    Protection: a long secret in the subscription URL, the SNS topic must be
    ours, and emails are only read from our own S3 bucket. (Verifying SNS
    message signatures would be a further step for a production service.)
    """
    if not settings.inbound_secret or not hmac.compare_digest(secret, settings.inbound_secret):
        return Response(status_code=403)
    try:
        envelope = json.loads(await request.body())  # SNS sends JSON as text/plain
    except ValueError:
        return Response(status_code=400)
    if envelope.get("TopicArn") != settings.inbound_sns_topic_arn:
        return Response(status_code=403)

    kind = envelope.get("Type")
    if kind == "SubscriptionConfirmation":
        url = envelope.get("SubscribeURL", "")
        host = urlparse(url).hostname or ""
        if not (url.startswith("https://") and host.startswith("sns.") and host.endswith(".amazonaws.com")):
            return Response(status_code=400)
        async with httpx.AsyncClient(timeout=10) as client:
            await client.get(url)  # confirms the subscription with AWS
        return JSONResponse({"subscribed": True})
    if kind != "Notification":
        return JSONResponse({"ignored": kind})

    notification = json.loads(envelope.get("Message", "{}"))
    with closing(db.connect()) as conn:
        result = await run_in_threadpool(inbound_email.handle_ses_notification, conn, notification)
    return JSONResponse({"accepted": result.accepted, "reason": result.reason,
                         "photos_added": result.photos_added})


# ------------------------------------------------------------ verify page

def _verify_context(conn, check=None, event_id="", fingerprint="") -> dict:
    latest = db.latest_fingerprint(conn)
    return {
        "chain": db.verify_chain(conn),
        "latest": latest,
        "check": check,
        "event_id": event_id,
        "fingerprint": fingerprint,
    }


@router.get("/verify", response_class=HTMLResponse)
def verify_page(request: Request):
    with closing(db.connect()) as conn:
        return templates.TemplateResponse(request, "verify.html", _verify_context(conn))


@router.post("/verify", response_class=HTMLResponse)
def verify_fingerprint(request: Request, event_id: str = Form(""), fingerprint: str = Form("")):
    with closing(db.connect()) as conn:
        try:
            number = int(event_id.strip().lstrip("#"))
            check = db.check_fingerprint(conn, number, fingerprint)
        except ValueError:
            check = {"match": False, "reason": "Please enter the event number as a number, e.g. 14."}
        return templates.TemplateResponse(
            request, "verify.html", _verify_context(conn, check, event_id, fingerprint)
        )
