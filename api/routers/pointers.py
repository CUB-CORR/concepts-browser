"""Naming a concept, and un-naming it.

A taxonomy entry is a *pointer*: "this identifier means this concept, from here until it is
retired". Adding and retiring pointers is how every naming change is made — renaming a concept
is add-then-retire, giving it a second spelling is add-and-leave-both, and a code that turns
out to cover two substances becomes a group by pointing at both. Nothing is ever deleted: an
identifier that once resolved keeps resolving, which is the whole reason the rows carry a
window instead of being edited in place.

Addressed by concept id throughout — the operations are about *which* concept a name points at,
so naming the concept by one of its names would be circular the moment it has more than one.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import require_capability
from ..models import ORIGIN_USER, ConceptTaxonomy, Taxonomy, User, _utcnow
from ..schemas import PointerCreate, PointerOut
from ..security import CAN_EDIT
from .. import services
from .concepts import concept_or_404

router = APIRouter(tags=["pointers"])

_editor = require_capability(CAN_EDIT)


@router.post(
    "/concept/id/{concept_id}/pointers",
    response_model=PointerOut,
    status_code=201,
    summary="Point an identifier at a concept",
)
def add_pointer(
    concept_id: int,
    body: PointerCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(_editor),
):
    """Register `identifier` for this concept in `taxonomy`.

    Two 409s, deliberately different: the identifier already pointing at *this* concept is a
    mistake with no meaning to confirm, while it pointing at *another* concept is a group —
    legitimate, but never accidental, so it takes `confirm_group`. Re-adding an identifier this
    concept once held and retired mints a new row rather than reviving the old one, so the
    history says the name was gone in between.
    """
    concept = concept_or_404(db, concept_id)
    taxonomy_key = body.taxonomy or settings.default_taxonomy
    tax = db.scalar(select(Taxonomy).where(Taxonomy.key == taxonomy_key))
    if tax is None:
        raise HTTPException(404, f"Taxonomy '{taxonomy_key}' not found")

    now = _utcnow()
    active = list(
        db.scalars(
            select(ConceptTaxonomy).where(
                ConceptTaxonomy.taxonomy_id == tax.id,
                ConceptTaxonomy.identifier == body.identifier,
                services.pointer_active_at(now),
            )
        )
    )
    if any(ct.concept_id == concept.id for ct in active):
        raise HTTPException(
            409,
            f"Concept #{concept.id} is already named '{body.identifier}' in "
            f"'{taxonomy_key}'.",
        )
    if active and not body.confirm_group:
        raise HTTPException(
            409,
            {
                "error": "name_exists",
                "taxonomy": taxonomy_key,
                "name": body.identifier,
                "members": [
                    {"id": ct.concept_id, "name": ct.identifier, "display_name": ct.display_name}
                    for ct in active
                ],
            },
        )

    ct = ConceptTaxonomy(
        concept_id=concept.id,
        taxonomy_id=tax.id,
        identifier=body.identifier,
        display_name=body.display_name,
        relationship=body.relationship,
        origin=ORIGIN_USER,
        created_at=now,
    )
    db.add(ct)
    db.commit()
    db.refresh(ct)
    return {"taxonomy": taxonomy_key, "concept_id": concept.id, **services.pointer_info(ct)}


@router.post(
    "/concept/id/{concept_id}/pointers/{pointer_id}/deprecate",
    response_model=PointerOut,
    summary="Retire one of a concept's names",
)
def deprecate_pointer(
    concept_id: int,
    pointer_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(_editor),
):
    """Close a pointer's window. The identifier keeps resolving — reads fall back to retired
    pointers when nothing active matches — but it no longer lists, and the app badges it.

    Orphan guard: a live concept must keep at least one active name, or nothing could reach it
    but its id. Retiring the last one is only allowed once the concept itself is deprecated.
    """
    concept = concept_or_404(db, concept_id)
    ct = db.get(ConceptTaxonomy, pointer_id)
    if ct is None or ct.concept_id != concept.id:
        raise HTTPException(404, f"Concept #{concept.id} has no pointer #{pointer_id}")
    now = _utcnow()
    if ct.deprecated_at is not None:
        raise HTTPException(409, f"Pointer #{pointer_id} is already retired")

    remaining = db.scalar(
        select(ConceptTaxonomy.id).where(
            ConceptTaxonomy.concept_id == concept.id,
            ConceptTaxonomy.id != ct.id,
            services.pointer_active_at(now),
        )
    )
    if remaining is None and concept.deprecated_at is None:
        raise HTTPException(
            409,
            f"'{ct.identifier}' is the last name of concept #{concept.id}; add another name "
            f"first, or deprecate the concept.",
        )

    ct.deprecated_at = now
    ct.deprecated_by = user.id
    db.commit()
    db.refresh(ct)
    tax_key = db.get(Taxonomy, ct.taxonomy_id).key
    return {"taxonomy": tax_key, "concept_id": concept.id, **services.pointer_info(ct)}
