"""Retiring a name, or the concept that turned out to be a duplicate.

Split in two on purpose. Noticing that two concepts describe one idea is editorial work
(`can_edit`); taking one of them out of circulation is not, because every client pinned to it —
by name, by id, by version — is affected, and the successor is a claim about equivalence that
somebody has to stand behind. So an editor files a request and a reviewer (`can_publish`)
decides it.

A request is filed against one of the concept's *names*, because that is what the person
filing it was looking at. What approving does therefore depends on how much of the concept
that name is: a concept reachable under other live names loses only the pointer the request
targeted — the definition, its history and its other names are untouched, because nothing
about the concept was being retired, only one way of naming it. Only when the targeted name is
the last live one is the concept itself out of circulation, and only then does approving stamp
the concept: `deprecated_at`, who decided, and the `successor_id` clients should follow.

Nothing is deleted and no version is renumbered — a retired concept's history stays exactly
where it was, and its names keep resolving to it. Rejecting only closes the request.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import services
from ..db import get_db
from ..deps import require_capability
from ..models import (
    DEPRECATION_APPROVED,
    DEPRECATION_PENDING,
    DEPRECATION_REJECTED,
    Concept,
    ConceptTaxonomy,
    DeprecationRequest,
    Taxonomy,
    User,
    _utcnow,
)
from ..schemas import DeprecationDecision, DeprecationRequestIn, DeprecationRequestOut
from ..security import CAN_EDIT, CAN_PUBLISH
from .concepts import concept_or_404

router = APIRouter(tags=["deprecation"])

_editor = require_capability(CAN_EDIT)
# Reading the queue and answering it are one capability: whoever reviews, publishes. The
# queue lands on the same screen as the open drafts (`GET /drafts`).
_reviewer = require_capability(CAN_PUBLISH)


def _concept_ref(db: Session, concept_id: int | None) -> dict | None:
    """A concept as the review queue names it: id plus the name a reviewer recognises."""
    if concept_id is None:
        return None
    found = services.display_pointer(db, concept_id)
    if found is None:
        return {"id": concept_id, "taxonomy": None, "name": None, "display_name": None}
    ct, tax_key = found
    return {
        "id": concept_id,
        "taxonomy": tax_key,
        "name": ct.identifier,
        "display_name": ct.display_name,
    }


def _pointer_ref(db: Session, pointer_id: int | None) -> dict | None:
    """The name a request was filed against. None when it was filed against the concept."""
    if pointer_id is None:
        return None
    ct = db.get(ConceptTaxonomy, pointer_id)
    if ct is None:
        return None
    tax = db.get(Taxonomy, ct.taxonomy_id)
    return {
        "id": ct.id,
        "taxonomy": tax.key if tax is not None else None,
        "name": ct.identifier,
        "display_name": ct.display_name,
        "deprecated_at": ct.deprecated_at,
    }


def _other_active_pointer(db: Session, concept_id: int, pointer_id: int, at_time) -> int | None:
    """The id of some *other* name this concept answered to at `at_time`, if it had one.

    The same existence check the orphan guard in ``routers/pointers.py`` makes, and for the
    same reason: a name is only the concept when it is the concept's last way in.
    """
    return db.scalar(
        select(ConceptTaxonomy.id).where(
            ConceptTaxonomy.concept_id == concept_id,
            ConceptTaxonomy.id != pointer_id,
            services.pointer_active_at(at_time),
        )
    )


def _retires(db: Session, req: DeprecationRequest) -> str:
    """What this request takes out of circulation: one `name`, or the whole `concept`.

    Asked as of the moment that matters. An open request is answered as of now — it is the
    decision a reviewer is about to make, and the concept may have gained or lost names since
    it was filed. A resolved one is answered as of `resolved_at`, which is exactly what the
    approval did, and stays true however the concept is named afterwards.
    """
    if req.pointer_id is None:
        return "concept"
    at_time = req.resolved_at or _utcnow()
    other = _other_active_pointer(db, req.concept_id, req.pointer_id, at_time)
    return "name" if other is not None else "concept"


def _out(db: Session, req: DeprecationRequest, usernames: dict[int, str]) -> dict:
    return {
        "id": req.id,
        "concept": _concept_ref(db, req.concept_id),
        "pointer": _pointer_ref(db, req.pointer_id),
        "retires": _retires(db, req),
        "reason": req.reason,
        "successor": _concept_ref(db, req.suggested_successor_id),
        "status": req.status,
        "requested_by": usernames.get(req.requested_by),
        "resolved_by": usernames.get(req.resolved_by),
        "resolved_at": req.resolved_at,
        "created_at": req.created_at,
    }


def _usernames(db: Session, requests: list[DeprecationRequest]) -> dict[int, str]:
    ids = {r.requested_by for r in requests} | {r.resolved_by for r in requests}
    ids.discard(None)
    if not ids:
        return {}
    return {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(ids)))}


@router.post(
    "/concept/id/{concept_id}/deprecation-request",
    response_model=DeprecationRequestOut,
    status_code=201,
    summary="Ask for a concept to be retired",
)
def request_deprecation(
    concept_id: int,
    body: DeprecationRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(_editor),
):
    """File a request to retire one of this concept's names — or, when `pointer_id` is omitted
    or names its only one, the concept itself — optionally naming what replaces it."""
    concept = concept_or_404(db, concept_id)
    if concept.deprecated_at is not None:
        raise HTTPException(409, f"Concept #{concept.id} is already deprecated")
    if body.pointer_id is not None:
        pointer = db.get(ConceptTaxonomy, body.pointer_id)
        if pointer is None or pointer.concept_id != concept.id:
            raise HTTPException(
                404, f"Concept #{concept.id} has no pointer #{body.pointer_id}"
            )
        if pointer.deprecated_at is not None:
            raise HTTPException(409, f"'{pointer.identifier}' is already retired")
    if body.successor_id is not None:
        if body.successor_id == concept.id:
            raise HTTPException(400, "A concept cannot succeed itself")
        concept_or_404(db, body.successor_id)
    open_request = db.scalar(
        select(DeprecationRequest).where(
            DeprecationRequest.concept_id == concept.id,
            DeprecationRequest.status == DEPRECATION_PENDING,
        )
    )
    if open_request is not None:
        raise HTTPException(
            409, f"Concept #{concept.id} already has an open deprecation request"
        )

    req = DeprecationRequest(
        concept_id=concept.id,
        pointer_id=body.pointer_id,
        requested_by=user.id,
        reason=body.reason,
        suggested_successor_id=body.successor_id,
        status=DEPRECATION_PENDING,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return _out(db, req, _usernames(db, [req]))


@router.get(
    "/deprecation-requests",
    response_model=list[DeprecationRequestOut],
    summary="The deprecation review queue",
)
def list_deprecation_requests(
    status: str | None = Query(
        None, description="'pending', 'approved' or 'rejected'; omitted = all"
    ),
    db: Session = Depends(get_db),
    _user: User = Depends(_reviewer),
):
    """Deprecation requests, newest first, optionally narrowed to one status."""
    q = select(DeprecationRequest).order_by(DeprecationRequest.created_at.desc())
    if status is not None:
        q = q.where(DeprecationRequest.status == status)
    rows = list(db.scalars(q))
    usernames = _usernames(db, rows)
    return [_out(db, r, usernames) for r in rows]


def _resolve(db: Session, request_id: int) -> DeprecationRequest:
    req = db.get(DeprecationRequest, request_id)
    if req is None:
        raise HTTPException(404, f"Deprecation request #{request_id} not found")
    if req.status != DEPRECATION_PENDING:
        raise HTTPException(409, f"Request #{request_id} was already {req.status}")
    return req


@router.post(
    "/deprecation-requests/{request_id}/approve",
    response_model=DeprecationRequestOut,
    summary="Approve a deprecation request",
)
def approve_deprecation(
    request_id: int,
    body: DeprecationDecision | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(_reviewer),
):
    """Retire what the request asked for.

    A request filed against a name the concept can spare closes that pointer's window and
    stops: the identifier stops listing, the concept stays live under its other names, and
    neither its definition nor its `successor_id` is touched — nothing was retired that a
    client pinned to the concept would notice. A request against the concept, or against its
    last live name, retires the concept: stamp `deprecated_at`/`deprecated_by` and the
    successor clients should follow, leaving its names and version history exactly as they are.

    `successor_id` in the body overrides what the request suggested. It is recorded on the
    request either way, but only reaches the concept when the concept is what is being retired
    — a successor is a claim about the definition, and a spare name going is not that.
    """
    req = _resolve(db, request_id)
    concept = db.get(Concept, req.concept_id)
    if concept is None:
        raise HTTPException(404, f"Concept #{req.concept_id} no longer exists")

    successor_id = req.suggested_successor_id
    if body is not None and "successor_id" in body.model_fields_set:
        successor_id = body.successor_id
    if successor_id is not None:
        if successor_id == concept.id:
            raise HTTPException(400, "A concept cannot succeed itself")
        concept_or_404(db, successor_id)

    now = _utcnow()
    pointer = None
    if req.pointer_id is not None:
        pointer = db.get(ConceptTaxonomy, req.pointer_id)
        if pointer is None or pointer.concept_id != concept.id:
            raise HTTPException(
                409, f"The name request #{req.id} was filed against no longer exists"
            )

    if pointer is not None and _other_active_pointer(db, concept.id, pointer.id, now):
        # A name the concept can spare: close its window and leave the concept alone.
        if pointer.deprecated_at is None:
            pointer.deprecated_at = now
            pointer.deprecated_by = user.id
    else:
        concept.deprecated_at = now
        concept.deprecated_by = user.id
        concept.successor_id = successor_id

    req.suggested_successor_id = successor_id
    req.status = DEPRECATION_APPROVED
    req.resolved_by = user.id
    req.resolved_at = now
    db.commit()
    db.refresh(req)
    return _out(db, req, _usernames(db, [req]))


@router.post(
    "/deprecation-requests/{request_id}/reject",
    response_model=DeprecationRequestOut,
    summary="Reject a deprecation request",
)
def reject_deprecation(
    request_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_reviewer),
):
    """Close the request without touching the concept."""
    req = _resolve(db, request_id)
    req.status = DEPRECATION_REJECTED
    req.resolved_by = user.id
    req.resolved_at = _utcnow()
    db.commit()
    db.refresh(req)
    return _out(db, req, _usernames(db, [req]))
