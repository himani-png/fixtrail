"""Web pages: the things voice can't do well.

  /                      tenant dashboard            (tenant passcode)
  /issues/{id}           timeline of one issue       (tenant passcode)
  /issues/{id}/photos    upload photos               (tenant passcode)
  /respond/{token}       landlord response page      (secret link, no login)
  /photos/{event_id}     a stored photo              (tenant, or landlord link)
  /verify                check the record            (anyone)
"""

import hashlib
import hmac
from contextlib import closing
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app import db, models, reports, services
from app.config import settings
from app.photos import get_store

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

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


@router.post("/login")
def login(request: Request, passcode: str = Form(""), next: str = Form("/")):
    if not hmac.compare_digest(passcode, settings.tenant_passcode):
        return templates.TemplateResponse(
            request, "login.html", {"next": _safe_next(next), "error": "That passcode isn't right."},
            status_code=401,
        )
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(COOKIE_NAME, _cookie_value(), httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
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
        if p.get("message_id"):
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
