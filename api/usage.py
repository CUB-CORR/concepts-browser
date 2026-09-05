"""Usage tracking: the audit log folded into a per-(user, concept) rollup.

The audit log already records every concept read with its user, its concept and its project
(see `api/audit.py`). What it does not do is answer aggregate questions cheaply: "which concepts
has this user used", "when were they last active", "which concepts are read most" are all scans
over a table that grows with every single API call, and the log is append-only forever. So the
answers are folded, once, into `concept_usage`: one row per (user, concept), carrying the read
count and the first/last time.

The fold is **incremental and idempotent**, keyed on a watermark (`usage_rollup_state`) holding
the highest `audit_log.id` already counted. That is what lets it run wherever it is convenient —
at boot, and on the read path of every usage endpoint — instead of needing a scheduler or a
write-path hook. Running it from the endpoints (rather than from the audit middleware) also
keeps a failing rollup from ever touching the request being audited.

`concept_usage` holds nothing that isn't derived: deleting it and rebuilding from the log
(`rebuild`) is always a valid repair.

What counts as usage: a *successful GET that resolved a concept*, by a known user, **calling the
API directly**. Writes are not reads; a 404 is not a use; a group read (one name resolving to
several concepts) has no single `concept_id` and is deliberately not folded — the rollup counts
concepts used, and that row names none.

"Directly" is the point of the panel this feeds: it answers "who is pulling concepts out of this
repository", not "who clicked around in the browser". The web app reads concepts on the logged-in
user's behalf on every concept page they open, and those reads are the app's, not theirs — a
person who never touched the API would otherwise accumulate usage simply by browsing. The audit
log already separates the two (`client_type`, set from the BFF's shared secret), so the filter
lives here, on the fold, and the log itself stays a complete record of every request.

Rows with no `client_type` at all are legacy (they predate the column) and are still counted:
they are the pre-existing history, and dropping them would silently rewrite it.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import CLIENT_APP, EVENT_API_CALL, AuditLog, ConceptUsage, UsageRollupState, _utcnow

log = logging.getLogger("concepts.usage")

_STATE_ID = 1


def _direct_call():
    """A call the user made themselves, rather than one our own web app made for them.

    Kept separate from `_read_filters` because it is not about *what* was read: `last_active_at`
    asks the same question of every API call, and both must draw the same line."""
    # `!= 'app'` alone would drop the legacy NULLs too — SQL's three-valued logic makes
    # `NULL != 'app'` unknown, not true.
    return or_(AuditLog.client_type != CLIENT_APP, AuditLog.client_type.is_(None))


def _read_filters():
    """The audit rows that count as a concept read."""
    return (
        AuditLog.event == EVENT_API_CALL,
        AuditLog.method == "GET",
        AuditLog.user_id.is_not(None),
        AuditLog.concept_id.is_not(None),
        AuditLog.status_code < 400,
        _direct_call(),
    )


def _merge_versions(stored: str | None, seen: set[int]) -> str | None:
    """The stored version list widened by the versions just folded, sorted and re-joined."""
    known = {int(v) for v in (stored or "").replace(" ", "").split(",") if v}
    known |= seen
    return ", ".join(str(v) for v in sorted(known)) or None


def refresh(db: Session) -> int:
    """Fold every audit row above the watermark into `concept_usage`. Returns the number of
    (user, concept) pairs touched. A no-op when nothing new has been logged.

    Commits on success. Concurrent refreshes are made safe by advancing the watermark with a
    compare-and-set: a second folder that read the same watermark finds it already moved and
    discards its own (identical) work rather than double-counting.
    """
    state = db.get(UsageRollupState, _STATE_ID)
    watermark = state.last_audit_id if state is not None else 0

    high = db.scalar(select(func.max(AuditLog.id))) or 0
    if high <= watermark:
        return 0

    # One group per (user, concept), plus the id of the newest row in the group — the name and
    # taxonomy to label the pair with are read off that row, so the label follows a rename.
    groups = db.execute(
        select(
            AuditLog.user_id,
            AuditLog.concept_id,
            func.count().label("reads"),
            func.min(AuditLog.created_at).label("first_at"),
            func.max(AuditLog.created_at).label("last_at"),
            func.max(AuditLog.id).label("newest_id"),
        )
        .where(*_read_filters(), AuditLog.id > watermark, AuditLog.id <= high)
        .group_by(AuditLog.user_id, AuditLog.concept_id)
    ).all()

    labels = {}
    if groups:
        labels = {
            row_id: (name, taxonomy)
            for row_id, name, taxonomy in db.execute(
                select(AuditLog.id, AuditLog.concept_name, AuditLog.taxonomy).where(
                    AuditLog.id.in_([g.newest_id for g in groups])
                )
            ).all()
        }

    # The distinct versions each pair read in this window. A separate pass because it is the one
    # thing about a read that does not aggregate to a single number per group.
    versions: dict[tuple[int, int], set[int]] = {}
    for user_id, concept_id, version in db.execute(
        select(AuditLog.user_id, AuditLog.concept_id, AuditLog.concept_version)
        .where(
            *_read_filters(),
            AuditLog.concept_version.is_not(None),
            AuditLog.id > watermark,
            AuditLog.id <= high,
        )
        .distinct()
    ).all():
        versions.setdefault((user_id, concept_id), set()).add(version)

    for g in groups:
        name, taxonomy = labels.get(g.newest_id, (None, None))
        seen_versions = versions.get((g.user_id, g.concept_id), set())
        row = db.get(ConceptUsage, (g.user_id, g.concept_id))
        if row is None:
            db.add(
                ConceptUsage(
                    user_id=g.user_id,
                    concept_id=g.concept_id,
                    reads=g.reads,
                    first_used_at=g.first_at,
                    last_used_at=g.last_at,
                    concept_name=name,
                    taxonomy=taxonomy,
                    versions=_merge_versions(None, seen_versions),
                )
            )
        else:
            row.reads += g.reads
            row.versions = _merge_versions(row.versions, seen_versions)
            row.first_used_at = min(row.first_used_at, g.first_at)
            if g.last_at >= row.last_used_at:
                row.last_used_at = g.last_at
                # Only a *newer* read may relabel the pair.
                row.concept_name = name
                row.taxonomy = taxonomy

    if state is None:
        db.add(UsageRollupState(id=_STATE_ID, last_audit_id=high))
    else:
        # Compare-and-set: 0 rows means somebody else folded the same window first.
        moved = db.execute(
            update(UsageRollupState)
            .where(
                UsageRollupState.id == _STATE_ID,
                UsageRollupState.last_audit_id == watermark,
            )
            .values(last_audit_id=high, updated_at=_utcnow())
        ).rowcount
        if not moved:
            db.rollback()
            return 0

    db.commit()
    return len(groups)


def refresh_quietly() -> None:
    """`refresh` on its own session, swallowing failures — for the boot path, where a rollup
    problem must not be what stops the app from serving."""
    try:
        with SessionLocal() as db:
            folded = refresh(db)
        if folded:
            log.info("usage rollup: folded %d (user, concept) pair(s)", folded)
    except Exception:  # pragma: no cover - defensive
        log.exception("usage rollup refresh failed")


def rebuild(db: Session) -> int:
    """Throw the rollup away and fold the whole log again. Not called in normal operation — the
    repair path for a rollup suspected of having drifted, and the honest answer to "can this be
    reconstructed?" (it is derived data; it always can)."""
    db.execute(delete(ConceptUsage))
    state = db.get(UsageRollupState, _STATE_ID)
    if state is not None:
        state.last_audit_id = 0
    db.commit()
    return refresh(db)


def last_active_at(db: Session, user_id: int):
    """When this user last called the API themselves — not only concept reads, which is why it
    comes from the log rather than the rollup. One indexed max(); `audit_log.user_id` is indexed.

    Web-app requests are excluded for the same reason the fold excludes them: this sits in the
    same panel as the read counts, and a "last active" that ticked on every page view would say
    something different from the two numbers beside it."""
    return db.scalar(
        select(func.max(AuditLog.created_at)).where(
            AuditLog.user_id == user_id, AuditLog.event == EVENT_API_CALL, _direct_call()
        )
    )
