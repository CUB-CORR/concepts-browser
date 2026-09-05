"""Read API over the audit log, gated by `can_admin`. Backs the `routes/audit` page.

Writing the log is `api/audit.py`'s job (a middleware, plus `record_email` for the one event
that isn't a request); this module only reads it back. Two endpoints: a filtered, paged list of
events, and the set of values worth offering as filters.

The page's three tabs are the same query with a different `event`: `login` for sign-ins,
`api_call` for everything an authenticated client did, `email` for every message we sent them.
The filters that matter most — user, project, concept, send status — are columns on the row, so
none of this parses `path`.
"""
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import security
from ..db import get_db
from ..deps import require_capability
from ..models import AuditLog, Project, User
from ..schemas import AuditFilterOptions, AuditPage

router = APIRouter(prefix="/audit", tags=["audit"])

# The audit log is admin-only — it is a record of who read what.
_admin = require_capability(security.CAN_ADMIN)

_MAX_LIMIT = 200


@router.get("/events", response_model=AuditPage)
def list_events(
    db: Session = Depends(get_db),
    _: User = Depends(_admin),
    event: str | None = Query(None, description="'login', 'api_call' or 'email'"),
    client_type: str | None = Query(None, description="'app' or 'external'"),
    user_id: int | None = None,
    project_id: str | None = None,
    concept_id: int | None = None,
    email_status: str | None = Query(None, description="'sent', 'failed' or 'skipped'"),
    date_from: date | None = Query(None, description="inclusive, UTC day"),
    date_to: date | None = Query(None, description="inclusive, UTC day"),
    q: str | None = Query(
        None, description="substring of the path, concept name, subject or recipient"
    ),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
):
    """One page of audit events, newest first, plus the total matching the filters."""
    filters = []
    if event:
        filters.append(AuditLog.event == event)
    if client_type:
        filters.append(AuditLog.client_type == client_type)
    if user_id is not None:
        # On an email row this is the recipient, so the same filter answers both
        # "what did they do" and "what were they told".
        filters.append(AuditLog.user_id == user_id)
    if email_status:
        filters.append(AuditLog.email_status == email_status)
    if project_id:
        filters.append(AuditLog.project_id == project_id)
    if concept_id is not None:
        filters.append(AuditLog.concept_id == concept_id)
    if date_from is not None:
        filters.append(AuditLog.created_at >= datetime.combine(date_from, time.min))
    if date_to is not None:
        # Inclusive of the whole day the admin picked (timestamps are naive UTC).
        filters.append(AuditLog.created_at <= datetime.combine(date_to, time.max))
    if q:
        # One search box across all three tabs; each event kind only populates its own columns,
        # so the irrelevant halves of this OR are simply NULL.
        like = f"%{q.strip()}%"
        filters.append(
            or_(
                AuditLog.path.ilike(like),
                AuditLog.concept_name.ilike(like),
                AuditLog.email_subject.ilike(like),
                AuditLog.email_to.ilike(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(AuditLog).where(*filters)) or 0

    rows = db.execute(
        select(AuditLog, User, Project.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .outerjoin(Project, Project.id == AuditLog.project_id)
        .where(*filters)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()

    items = []
    for row, user, project_name in rows:
        items.append(
            {
                "id": row.id,
                "created_at": row.created_at,
                "event": row.event,
                # NULL for a failed login: nobody was authenticated. The name that was tried is
                # in `detail.username`, which is the only trace such an attempt leaves.
                # On an email row this is the recipient.
                "user": user,
                "client_type": row.client_type,
                "auth_method": row.auth_method,
                "method": row.method,
                "path": row.path,
                "query_string": row.query_string,
                "status_code": row.status_code,
                "email_kind": row.email_kind,
                "email_to": row.email_to,
                "email_subject": row.email_subject,
                "email_status": row.email_status,
                "project_id": row.project_id,
                "project_name": project_name,
                "concept_id": row.concept_id,
                "concept_name": row.concept_name,
                "taxonomy": row.taxonomy,
                "concept_version": row.concept_version,
                "ip_address": row.ip_address,
                "user_agent": row.user_agent,
                "detail": row.detail,
            }
        )

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/filter-options", response_model=AuditFilterOptions)
def filter_options(db: Session = Depends(get_db), _: User = Depends(_admin)):
    """The users, projects and concepts that actually appear in the log, so the filter
    dropdowns never offer a value with no rows behind it."""
    users = db.scalars(
        select(User)
        .where(User.id.in_(select(AuditLog.user_id).where(AuditLog.user_id.is_not(None))))
        .order_by(User.username)
    ).all()

    projects = db.execute(
        select(Project.id, Project.name)
        .where(Project.id.in_(select(AuditLog.project_id).where(AuditLog.project_id.is_not(None))))
        .order_by(Project.name)
    ).all()

    # Concepts someone actually read (`get_concept` / its history) — the event we care about most.
    concepts = db.execute(
        select(AuditLog.concept_id, AuditLog.concept_name, AuditLog.taxonomy)
        .where(AuditLog.concept_id.is_not(None))
        .group_by(AuditLog.concept_id, AuditLog.concept_name, AuditLog.taxonomy)
        .order_by(AuditLog.concept_name)
    ).all()

    return {
        "users": users,
        "projects": [{"id": pid, "name": name} for pid, name in projects],
        "concepts": [
            {"id": cid, "name": name, "taxonomy": tax} for cid, name, tax in concepts
        ],
    }
