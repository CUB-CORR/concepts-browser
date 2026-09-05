"""Projects API.

A project is mostly self-contained: it governs external concept queries (clients name a
project), records CORR-license acceptance and carries the study context (the PICO frame and
the study team) describing the study it is. Anyone signed in may browse projects; only a
project's leads (or an admin) may edit it; creating one needs the `add_project` capability.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import security
from ..db import get_db
from ..deps import get_current_user, has_capability, require_capability
from ..models import CLIENT_APP, EVENT_API_CALL, AuditLog, License, Project, ProjectLead, User
from ..schemas import ProjectCreate, ProjectUpdate

router = APIRouter(tags=["projects"])

_can_add = require_capability(security.ADD_PROJECT)


def _now() -> datetime:
    """Naive UTC, matching the timestamps stored elsewhere (SQLite has no tz type)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean_name(raw: str | None) -> str:
    """Strip and validate a project name: required, no spaces, must start lowercase."""
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project name is required")
    if any(c.isspace() for c in name):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A project name must not contain spaces"
        )
    if not name[0].islower():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "A project name must start with a lowercase letter"
        )
    if name == "internal":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This name is reserved for internal use.",
        )
    return name


# --- helpers ---------------------------------------------------------------------------

def _current_license(db: Session) -> License | None:
    """The active license with the highest version — what a project must have accepted."""
    return db.scalar(
        select(License).where(License.active.is_(True)).order_by(License.version.desc())
    )


def _leads_by_project(db: Session, project_ids: list[str]) -> dict[str, list[dict]]:
    """Batched {project_id: [{id, username, display_name}]} for the given projects."""
    out: dict[str, list[dict]] = {pid: [] for pid in project_ids}
    if not project_ids:
        return out
    rows = db.execute(
        select(ProjectLead.project_id, User.id, User.username, User.display_name)
        .join(User, User.id == ProjectLead.user_id)
        .where(ProjectLead.project_id.in_(project_ids))
        .order_by(User.username)
    )
    for pid, uid, username, display_name in rows:
        out[pid].append({"id": uid, "username": username, "display_name": display_name})
    return out


def _status(p: Project) -> str:
    if p.deleted_on is not None:
        return "deleted"
    if p.completed_on is not None:
        return "completed"
    return "active"


def _can_edit(p: Project, user: User, lead_ids: set[int]) -> bool:
    """A lead or an admin may edit — never a deleted project."""
    if p.deleted_on is not None:
        return False
    return has_capability(user, security.CAN_ADMIN) or user.id in lead_ids


# The study context, in the canonical PICO order with the study team last. One tuple so the
# response, the PATCH and the migration in api/main.py cannot drift apart.
STUDY_CONTEXT_FIELDS = (
    "pico_population",
    "pico_intervention",
    "pico_comparison",
    "pico_outcome",
    "study_team",
)


def _project_dict(p: Project, leads: list[dict], current_version: int | None, user: User) -> dict:
    lead_ids = {lead["id"] for lead in leads}
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "ea_id": p.ea_id,
        "created_on": p.created_on,
        "completed_on": p.completed_on,
        "deleted_on": p.deleted_on,
        "status": _status(p),
        "leads": leads,
        "license_approval": p.license_approval,
        "license_current_version": current_version,
        # Approved and up to date with the active license version.
        "license_ok": current_version is not None and p.license_approval >= current_version,
        "license_approved_on": p.license_approved_on,
        "can_edit": _can_edit(p, user, lead_ids),
        # The study context rides along on the list too: it is five short text columns on the
        # same row, so serving it costs nothing and the list needs no second request.
        **{f: getattr(p, f) for f in STUDY_CONTEXT_FIELDS},
    }


def _load_editable(db: Session, project_id: str, user: User) -> tuple[Project, set[int]]:
    """Fetch a project and its lead ids, 404/403-ing if it's missing or the user can't edit."""
    p = db.get(Project, project_id)
    if p is None or p.deleted_on is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    lead_ids = set(db.scalars(select(ProjectLead.user_id).where(ProjectLead.project_id == p.id)))
    if not _can_edit(p, user, lead_ids):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a project lead or an admin may edit this project"
        )
    return p, lead_ids


def _validate_lead_ids(db: Session, lead_ids: list[int]) -> list[int]:
    """Dedupe and confirm each id is an existing, active user."""
    ids = list(dict.fromkeys(lead_ids))
    if not ids:
        return ids
    found = set(db.scalars(select(User.id).where(User.id.in_(ids), User.is_active.is_(True))))
    missing = [i for i in ids if i not in found]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown or inactive user ids: {missing}")
    return ids


def _set_leads(db: Session, project_id: str, lead_ids: list[int]) -> None:
    """Replace a project's lead set with exactly `lead_ids`."""
    db.query(ProjectLead).filter(ProjectLead.project_id == project_id).delete()
    for uid in lead_ids:
        db.add(ProjectLead(project_id=project_id, user_id=uid))


# --- static sub-routes (declared before /projects/{id} so they aren't shadowed) --------

@router.get("/projects/user-options")
def user_options(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """Active users for the lead multi-select on the create/edit forms."""
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.username))
    return [
        {"id": u.id, "username": u.username, "display_name": u.display_name} for u in users
    ]


@router.get("/projects/license")
def current_license(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """The current CORR license text a project must accept (null if none configured)."""
    lic = _current_license(db)
    if lic is None:
        return None
    return {"version": lic.version, "body": lic.body, "created_on": lic.created_on}


# --- collection ------------------------------------------------------------------------

@router.get("/projects")
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    projects = db.scalars(
        select(Project).where(Project.deleted_on.is_(None)).order_by(Project.name)
    ).all()
    leads = _leads_by_project(db, [p.id for p in projects])
    lic = _current_license(db)
    version = lic.version if lic else None
    return [_project_dict(p, leads[p.id], version, user) for p in projects]


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(_can_add),
):
    name = _clean_name(body.name)
    if db.scalar(select(Project.id).where(Project.name == name)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"A project named '{name}' already exists")

    lic = _current_license(db)
    if not body.accept_license:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You must accept the CORR license to create a project"
        )
    if lic is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No CORR license is configured; cannot record acceptance"
        )

    # The creator always leads their project (so they can edit it); merge in any chosen leads.
    lead_ids = _validate_lead_ids(db, [user.id, *body.lead_ids])

    project = Project(
        name=name,
        description=(body.description or "").strip() or None,
        ea_id=(body.ea_id or "").strip() or None,
        license_approval=lic.version,
        license_approved_by=user.id,
        license_approved_on=_now(),
    )
    db.add(project)
    db.flush()  # assign project.id before linking leads
    _set_leads(db, project.id, lead_ids)
    db.commit()
    db.refresh(project)

    leads = _leads_by_project(db, [project.id])[project.id]
    return _project_dict(project, leads, lic.version, user)


# --- item ------------------------------------------------------------------------------

@router.get("/projects/{project_id}")
def get_project(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    leads = _leads_by_project(db, [p.id])[p.id]
    lic = _current_license(db)
    return _project_dict(p, leads, lic.version if lic else None, user)


@router.patch("/projects/{project_id}")
def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    p, _ = _load_editable(db, project_id, user)

    if body.name is not None:
        name = _clean_name(body.name)
        clash = db.scalar(select(Project.id).where(Project.name == name, Project.id != p.id))
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, f"A project named '{name}' already exists")
        p.name = name
    if body.description is not None:
        p.description = body.description.strip() or None
    if body.ea_id is not None:
        p.ea_id = body.ea_id.strip() or None
    if body.lead_ids is not None:
        lead_ids = _validate_lead_ids(db, body.lead_ids)
        if not lead_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A project needs at least one lead")
        _set_leads(db, p.id, lead_ids)
    if body.completed is not None:
        p.completed_on = _now() if body.completed else None
    # The study context is the one block where an explicit null means "clear it", so it goes by
    # what the body actually set rather than by the value being non-null. Same gate as
    # everything else here: `_load_editable` already required a lead or an admin.
    for field in (f for f in STUDY_CONTEXT_FIELDS if f in body.model_fields_set):
        value = getattr(body, field)
        setattr(p, field, (value or "").strip() or None)
    if body.accept_license:
        lic = _current_license(db)
        if lic is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "No CORR license is configured")
        p.license_approval = lic.version
        p.license_approved_by = user.id
        p.license_approved_on = _now()

    db.commit()
    db.refresh(p)
    leads = _leads_by_project(db, [p.id])[p.id]
    lic = _current_license(db)
    return _project_dict(p, leads, lic.version if lic else None, user)


@router.post("/projects/{project_id}/delete")
def delete_project(
    project_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Soft-delete: stamps `deleted_on`; external queries naming it are then rejected."""
    p, _ = _load_editable(db, project_id, user)
    p.deleted_on = _now()
    db.commit()
    return {"ok": True}


@router.get("/projects/{project_id}/activity")
def project_activity(
    project_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """Request counts for the last 24h (hourly), week and month (daily) from the audit log."""
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    now = _now()
    return {
        "last_24h": _buckets(db, p.id, now, span=timedelta(hours=24), step=timedelta(hours=1)),
        "last_week": _buckets(db, p.id, now, span=timedelta(days=7), step=timedelta(days=1)),
        "last_month": _buckets(db, p.id, now, span=timedelta(days=30), step=timedelta(days=1)),
    }


@router.get("/projects/{project_id}/usage")
def project_usage(
    project_id: str, db: Session = Depends(get_db), _: User = Depends(get_current_user)
):
    """Which concepts were read in this project's context, how often, when last, and in which
    versions.

    The same table the profile page shows, narrowed to a project — which the `concept_usage`
    rollup cannot answer, having no project dimension, so it is computed from the log. The rows
    that count are the ones the fold counts (`api/usage.py`): a successful concept GET the user
    made against the API, never one our own web app made while somebody browsed.
    """
    p = db.get(Project, project_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")

    where = (
        AuditLog.project_id == project_id,
        AuditLog.event == EVENT_API_CALL,
        AuditLog.method == "GET",
        AuditLog.concept_id.is_not(None),
        AuditLog.status_code < 400,
        or_(AuditLog.client_type != CLIENT_APP, AuditLog.client_type.is_(None)),
    )

    groups = db.execute(
        select(
            AuditLog.concept_id,
            func.count().label("reads"),
            func.min(AuditLog.created_at).label("first_at"),
            func.max(AuditLog.created_at).label("last_at"),
            func.max(AuditLog.id).label("newest_id"),
        )
        .where(*where)
        .group_by(AuditLog.concept_id)
        .order_by(func.max(AuditLog.created_at).desc(), AuditLog.concept_id)
    ).all()
    if not groups:
        return []

    # The name/taxonomy to label a concept with is the one its newest read carried, exactly as
    # the rollup picks it.
    labels = {
        row_id: (name, taxonomy)
        for row_id, name, taxonomy in db.execute(
            select(AuditLog.id, AuditLog.concept_name, AuditLog.taxonomy).where(
                AuditLog.id.in_([g.newest_id for g in groups])
            )
        ).all()
    }

    versions: dict[int, set[int]] = {}
    for concept_id, version in db.execute(
        select(AuditLog.concept_id, AuditLog.concept_version)
        .where(*where, AuditLog.concept_version.is_not(None))
        .distinct()
    ).all():
        versions.setdefault(concept_id, set()).add(version)

    return [
        {
            "concept_id": g.concept_id,
            "name": labels.get(g.newest_id, (None, None))[0],
            "taxonomy": labels.get(g.newest_id, (None, None))[1],
            "reads": g.reads,
            "first_used_at": g.first_at,
            "last_used_at": g.last_at,
            "versions": ", ".join(str(v) for v in sorted(versions.get(g.concept_id, ()))) or None,
        }
        for g in groups
    ]


def _buckets(
    db: Session, project_id: str, now: datetime, *, span: timedelta, step: timedelta
) -> dict:
    """Fixed-width time buckets over [now-span, now]; total plus a per-bucket series."""
    start = now - span
    times = db.scalars(
        select(AuditLog.created_at).where(
            AuditLog.project_id == project_id, AuditLog.created_at >= start
        )
    ).all()
    n = max(1, round(span / step))
    counts = [0] * n
    for ts in times:
        idx = int((ts - start) / step)
        if idx < 0:
            idx = 0
        if idx >= n:
            idx = n - 1
        counts[idx] += 1
    buckets = [
        {"ts": start + step * i, "count": counts[i]} for i in range(n)
    ]
    return {"total": len(times), "buckets": buckets}
