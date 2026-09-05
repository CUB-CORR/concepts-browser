"""The audit log: what gets recorded, and how.

Three concerns live here so the routes stay thin:

1. `resolve_active_project` — turn a project *name* (what external clients pass) into a
   `Project`, rejecting unknown or soft-deleted projects and those that have not accepted the
   current CORR license. Completed projects stay usable.
2. `mark_*` — routes stash context on `request.state` (the resolved project, the concept that
   was served, the authenticated user). Nothing is written at that point.
3. `audit_middleware` — writes exactly one `audit_log` row per request, once the response
   status is known, merging in whatever the route stashed.

Recording in middleware rather than in a dependency is what lets the log cover *every* route
(including writes and failures) instead of only the concept reads, and guarantees one row per
request — a dependency can't see the status code, and several dependencies on one route would
each have logged their own row.

We record a request when it is authenticated (`mark_user` ran) or when it is a login attempt;
anonymous 401s against arbitrary paths are noise, not audit events.

Email is the one event that is *not* a request: it leaves in a background task, after the
response, so `mailer` appends its own row through `record_email` instead of the middleware.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from .db import SessionLocal
from .models import (
    CLIENT_APP,
    CLIENT_EXTERNAL,
    EVENT_API_CALL,
    EVENT_EMAIL,
    EVENT_LOGIN,
    AuditLog,
    License,
    Project,
)

log = logging.getLogger("concepts.audit")

APP_HEADER = "X-App-Secret"

# Paths that would only ever add noise: the health probe and the public docs (unauthenticated
# and static). Everything else an authenticated caller touches is auditable.
_SKIP_PREFIXES = ("/health", "/public/")

_MAX_UA = 256


def is_app_request(request: Request, app_secret: str) -> bool:
    """True when the request carries the BFF's shared secret — i.e. our own web app. Empty
    configured secret ⇒ nothing is trusted as app-originated (fail closed)."""
    if not app_secret:
        return False
    sent = request.headers.get(APP_HEADER)
    return bool(sent) and _consteq(sent, app_secret)


def resolve_active_project(db: Session, name: str | None) -> Project:
    """Resolve an external client's `project` argument. Raises 400 if missing, 404 if unknown,
    403 if soft-deleted or if its license acceptance is missing/outdated. Completed projects
    (only `completed_on` set) remain valid."""
    if not name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "A 'project' is required. Name an existing project to run this query.",
        )
    project = db.scalar(select(Project).where(Project.name == name))
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Project '{name}' not found")
    if project.deleted_on is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Project '{name}' has been deleted")
    _require_license(db, project)
    return project


def _require_license(db: Session, project: Project) -> None:
    """Reject a project whose CORR-license acceptance is missing or has been outrun by a newer
    license version.

    Accepting the license is a precondition for *retrieving concept definitions*, not merely a
    field on the project form — so it has to be enforced here, on the query path, and not only
    in the UI that records the acceptance. `license_approval` is the version a lead accepted
    (0 = never); publishing a higher `License` version is the deliberate mechanism for forcing
    every project to re-approve, which means "approved, but below the active version" has to
    fail exactly like "never approved".

    A deployment with no active license row can't ask anyone to accept anything, so a project
    that carries *some* approval stays usable — the one case where we cannot tell whether it is
    current, and locking every query out would be the wrong failure mode.
    """
    if project.license_approval:
        # Version currently in force: the highest active row (the same rule the projects API
        # uses to decide whether to prompt for re-approval).
        active = db.scalar(
            select(License.version)
            .where(License.active.is_(True))
            .order_by(License.version.desc())
        )
        if active is None or project.license_approval >= active:
            return

    from .config import settings

    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Project '{project.name}' has not accepted the current CORR license. "
        f"A project lead must (re-)accept it on the project page in "
        f"{settings.app_display_name} before this project can query concept definitions.",
    )


# --- what the routes stash -----------------------------------------------------------------
# Each writes onto `request.state`; the middleware reads it back after the response.


def mark_user(request: Request, *, user_id: int, auth_method: str) -> None:
    """Called by the auth dependency once a bearer credential resolves to a live user. This is
    also the flag that makes a request auditable at all."""
    request.state.audit_user_id = user_id
    request.state.audit_auth_method = auth_method


def mark_client(request: Request, *, client_type: str, project_id: str | None) -> None:
    """Called by the concept-read gate with the outcome of the app-vs-external decision."""
    request.state.audit_client_type = client_type
    request.state.audit_project_id = project_id


def mark_concept(
    request: Request,
    *,
    concept_id: int | None,
    name: str | None,
    taxonomy: str | None,
    version: int | None = None,
    selector: dict | None = None,
) -> None:
    """Called by the concept reads with the concept they served.

    `concept_id` is None when the read served a whole *group* — one name pointing at several
    concepts. The row then names the identifier that was read rather than any one member; the
    member ids go into `detail` (see `mark_detail`).

    Two different things, both worth having:

    * `version` — the version actually *served*. It lands in its own column, so the table can
      show it and an admin can see what a client really received.
    * `selector` — what the client actually *asked for*: `v`, `date`/`d` or `draft`. Recorded
      explicitly rather than parsed back out of the query string, because `date` has an alias
      (`d`) and an omitted selector ("give me the current version") is itself meaningful.

    The two differ whenever a client pins a version or reads as-of a past date, which is exactly
    the case the audit trail exists to answer.
    """
    request.state.audit_concept_id = concept_id
    request.state.audit_concept_name = name
    request.state.audit_taxonomy = taxonomy
    request.state.audit_concept_version = version
    if selector is not None:
        request.state.audit_selector = selector


def mark_detail(request: Request, **fields) -> None:
    """Extra context a route wants kept in its row's `detail`, merged in as-is.

    For the call whose *outcome* is the auditable fact rather than its arguments — a group read,
    whose member ids are the only record of what the name meant at that moment, or the creation
    of a second concept under an existing name. Everything else is reconstructable from the path
    and query params.
    """
    request.state.audit_detail_extra = {
        **(getattr(request.state, "audit_detail_extra", None) or {}),
        **fields,
    }


def mark_login(request: Request, *, username: str, user_id: int | None = None) -> None:
    """Called by the login route for *every* attempt, successful or not — a failed login is an
    audit event in its own right, and the attempted username is the only useful thing we can
    record when it doesn't resolve to a user. The password is never touched."""
    request.state.audit_event = EVENT_LOGIN
    request.state.audit_login_username = username
    if user_id is not None:
        request.state.audit_user_id = user_id


# --- the middleware ------------------------------------------------------------------------


async def audit_middleware(request: Request, call_next):
    """Record one row per auditable request, after the response status is known."""
    response: Response = await call_next(request)

    if _should_record(request):
        # The insert is sync SQLAlchemy; keep it off the event loop.
        await run_in_threadpool(_write, request, response.status_code)

    return response


def _should_record(request: Request) -> bool:
    if request.method == "OPTIONS":
        return False
    if request.url.path.startswith(_SKIP_PREFIXES):
        return False
    state = request.state
    # Authenticated (any route), or a login attempt (authenticated by definition of the event).
    return (
        getattr(state, "audit_user_id", None) is not None
        or getattr(state, "audit_event", None) == EVENT_LOGIN
    )


def _write(request: Request, status_code: int) -> None:
    """Append the row. Best-effort: an audit failure must never fail the request the user
    already got a response for."""
    state = request.state
    try:
        with SessionLocal() as db:
            db.add(
                AuditLog(
                    event=getattr(state, "audit_event", EVENT_API_CALL),
                    user_id=getattr(state, "audit_user_id", None),
                    project_id=getattr(state, "audit_project_id", None),
                    client_type=getattr(state, "audit_client_type", None) or _fallback_client(request),
                    method=request.method,
                    path=request.url.path,
                    status_code=status_code,
                    concept_id=getattr(state, "audit_concept_id", None),
                    concept_name=getattr(state, "audit_concept_name", None),
                    taxonomy=getattr(state, "audit_taxonomy", None),
                    concept_version=getattr(state, "audit_concept_version", None),
                    auth_method=getattr(state, "audit_auth_method", None),
                    query_string=request.url.query or None,
                    ip_address=_client_ip(request),
                    user_agent=_user_agent(request),
                    detail=_detail(request),
                )
            )
            db.commit()
    except Exception:  # pragma: no cover - defensive
        log.exception("failed to write audit row for %s %s", request.method, request.url.path)


# --- email --------------------------------------------------------------------------------


def record_email(
    *,
    user_id: int | None,
    kind: str,
    subject: str,
    status: str,
    to: str | None = None,
    detail: dict | None = None,
) -> None:
    """Append one `email` row: a message we sent, or decided not to / failed to.

    Called by `mailer` from a background task, so there is no request to hang this off — hence
    its own session, and the same best-effort contract as `_write`: recording a send must never
    be what breaks the action that triggered it.

    Failures and skips are recorded, not just successes. "This user says they were never told"
    is the question the log has to answer, and silence would answer it only by omission.
    """
    try:
        with SessionLocal() as db:
            db.add(
                AuditLog(
                    event=EVENT_EMAIL,
                    user_id=user_id,  # the recipient
                    email_kind=kind,
                    email_to=to,
                    email_subject=subject,
                    email_status=status,
                    detail=detail,
                )
            )
            db.commit()
    except Exception:  # pragma: no cover - defensive
        log.exception("failed to write audit row for %s email to user %s", kind, user_id)


def _fallback_client(request: Request) -> str:
    """Client type for routes that never ran the concept gate (logins, writes, admin calls):
    the app secret alone decides. Kept out of the gate's way — when the gate ran, its verdict
    (which also validated the project) wins."""
    from .config import settings

    if not settings.app_shared_secret:
        return CLIENT_APP
    return CLIENT_APP if is_app_request(request, settings.app_shared_secret) else CLIENT_EXTERNAL


def _user_agent(request: Request) -> str | None:
    ua = request.headers.get("user-agent")
    return ua[:_MAX_UA] if ua else None


def _client_ip(request: Request) -> str | None:
    """The caller's address. Behind the reverse proxy the socket peer is the proxy, so prefer
    the first hop in X-Forwarded-For when it's present."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host[:64] if request.client else None


def _detail(request: Request) -> dict:
    """The request as the detail view shows it: the raw query and path params exactly as sent,
    plus the concept selector the route parsed out of them. For a login the only body field we
    keep is the attempted username — never the password."""
    detail: dict = {
        "query_params": dict(request.query_params),
        "path_params": dict(request.scope.get("path_params") or {}),
    }
    selector = getattr(request.state, "audit_selector", None)
    if selector is not None:
        # What the client asked for (v / date / draft), normalized; the version actually served
        # is the `concept_version` column.
        detail["selector"] = selector
    username = getattr(request.state, "audit_login_username", None)
    if username is not None:
        detail["username"] = username
    detail.update(getattr(request.state, "audit_detail_extra", None) or {})
    return detail


def _consteq(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a, b)
