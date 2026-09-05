"""Read API over the usage rollup: what a user has used, and what a concept is used by.

Two directions out of one table (`concept_usage`, folded from the audit log by `api/usage.py`):

* `/usage/users/{user_id}` — the per-user view the profile page shows: last active, how many
  concepts, and which ones. **Admins see anyone; everybody else sees only themselves** (403).
  This is the same rule `/auth/users/{username}/profile` enforces, deliberately: the usage block
  sits on that page and must not be visible to anyone the page itself isn't.
* `/usage/concepts` — how much each concept is read, for the "most used" / "most used by me"
  sorts. Open to any authenticated caller, but *identity-free* unless they are an admin: the
  totals say how often a concept is read, never by whom. Only an admin gets the distinct-reader
  count; a non-admin additionally gets their own share (`my_reads`), which is their own data.

Both refresh the rollup first. The fold is incremental (a watermark over `audit_log.id`), so
this is a no-op scan of the rows appended since the last read — not a scan of the log.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import security, usage
from ..db import get_db
from ..deps import get_current_user, has_capability
from ..models import ConceptUsage, User
from ..schemas import ConceptUsageRow, UsageConceptRow, UserUsageOut

router = APIRouter(prefix="/usage", tags=["usage"])

_MAX_LIMIT = 200


def _is_admin(user: User) -> bool:
    return has_capability(user, security.CAN_ADMIN)


@router.get("/users/{user_id}", response_model=UserUsageOut)
def user_usage(
    user_id: int,
    caller: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """One user's API usage. Yourself, or anyone if you are an admin.

    The authorization check comes before the lookup on purpose: answering "no such user" to
    somebody who may not see that user either would still tell them which ids exist.
    """
    if caller.id != user_id and not _is_admin(caller):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to view this user's usage")

    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    usage.refresh(db)

    rows = db.scalars(
        select(ConceptUsage)
        .where(ConceptUsage.user_id == user_id)
        .order_by(ConceptUsage.last_used_at.desc(), ConceptUsage.concept_id)
    ).all()

    return UserUsageOut(
        user_id=target.id,
        username=target.username,
        display_name=target.display_name,
        last_active_at=usage.last_active_at(db, user_id),
        concepts_used=len(rows),
        total_reads=sum(r.reads for r in rows),
        concepts=[
            UsageConceptRow(
                concept_id=r.concept_id,
                name=r.concept_name,
                taxonomy=r.taxonomy,
                reads=r.reads,
                first_used_at=r.first_used_at,
                last_used_at=r.last_used_at,
                versions=r.versions,
            )
            for r in rows
        ],
    )


@router.get("/concepts", response_model=list[ConceptUsageRow])
def concept_usage(
    caller: User = Depends(get_current_user),
    sort: str = Query("reads", description="'reads' (most used), 'mine' (most used by me) or 'recent'"),
    mine_only: bool = Query(False, description="only concepts the caller has read"),
    limit: int = Query(50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Per-concept usage counts. Nothing here identifies a reader to a non-admin.

    No UI consumes this yet — it exists so the concept list can sort by "most used" and "most
    used by me" off the same rollup the per-user view reads, rather than growing a second one.
    """
    if sort not in {"reads", "mine", "recent"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "sort must be reads, mine or recent")

    usage.refresh(db)

    # The caller's own share, as a subquery joined per concept — "most used by me" is the same
    # aggregate narrowed to one user, so it stays one query.
    mine = (
        select(
            ConceptUsage.concept_id.label("concept_id"),
            ConceptUsage.reads.label("my_reads"),
            ConceptUsage.last_used_at.label("my_last_used_at"),
        )
        .where(ConceptUsage.user_id == caller.id)
        .subquery()
    )

    # `name`/`taxonomy` are the label of the most recently used row for the concept; max() over
    # the group would pick alphabetically, so pick the row and read its label back below.
    stmt = (
        select(
            ConceptUsage.concept_id,
            func.sum(ConceptUsage.reads).label("reads"),
            func.count().label("users"),
            func.max(ConceptUsage.last_used_at).label("last_used_at"),
            func.coalesce(mine.c.my_reads, 0).label("my_reads"),
            mine.c.my_last_used_at,
        )
        .outerjoin(mine, mine.c.concept_id == ConceptUsage.concept_id)
        .group_by(ConceptUsage.concept_id, mine.c.my_reads, mine.c.my_last_used_at)
    )
    if mine_only:
        stmt = stmt.where(mine.c.my_reads.is_not(None))

    order = {
        "reads": (func.sum(ConceptUsage.reads).desc(), ConceptUsage.concept_id),
        "mine": (func.coalesce(mine.c.my_reads, 0).desc(), ConceptUsage.concept_id),
        "recent": (func.max(ConceptUsage.last_used_at).desc(), ConceptUsage.concept_id),
    }[sort]
    rows = db.execute(stmt.order_by(*order).limit(limit).offset(offset)).all()

    labels = _labels(db, [r.concept_id for r in rows])
    is_admin = _is_admin(caller)
    return [
        ConceptUsageRow(
            concept_id=r.concept_id,
            name=labels.get(r.concept_id, (None, None))[0],
            taxonomy=labels.get(r.concept_id, (None, None))[1],
            reads=r.reads,
            last_used_at=r.last_used_at,
            # Distinct readers is a fact about people, so only an admin gets it.
            users=r.users if is_admin else None,
            my_reads=r.my_reads,
            my_last_used_at=r.my_last_used_at,
        )
        for r in rows
    ]


def _labels(db: Session, concept_ids: list[int]) -> dict[int, tuple[str | None, str | None]]:
    """The name/taxonomy each concept was most recently read under, one row per concept."""
    if not concept_ids:
        return {}
    newest = (
        select(
            ConceptUsage.concept_id,
            func.max(ConceptUsage.last_used_at).label("last_used_at"),
        )
        .where(ConceptUsage.concept_id.in_(concept_ids))
        .group_by(ConceptUsage.concept_id)
        .subquery()
    )
    rows = db.execute(
        select(ConceptUsage.concept_id, ConceptUsage.concept_name, ConceptUsage.taxonomy).join(
            newest,
            (newest.c.concept_id == ConceptUsage.concept_id)
            & (newest.c.last_used_at == ConceptUsage.last_used_at),
        )
    ).all()
    return {cid: (name, taxonomy) for cid, name, taxonomy in rows}
