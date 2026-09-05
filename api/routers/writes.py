from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import audit, mailer, services
from ..config import settings
from ..db import get_db
from ..deps import get_current_user, has_capability, require_capability
from ..models import (
    ORIGIN_USER,
    Concept,
    ConceptTaxonomy,
    Config,
    ConfigFileRef,
    Source,
    Taxonomy,
    User,
)
from ..schema_registry import registry
from ..schemas import (
    ConceptCreate,
    DocumentationUpdate,
    DraftCreate,
    DraftUpdate,
    OpenDraftOut,
    PublishRequest,
)
from ..security import CAN_EDIT, CAN_PUBLISH, CAN_READ, CAN_READ_DETAIL
from .concepts import concept_or_404

router = APIRouter(tags=["write"])

# The review queues are read by whoever decides them: reviewing is `can_publish`.
_review_queue = require_capability(CAN_PUBLISH)


def _draft_out(
    db: Session, d: Config, source_key: str | None = None, *, detail: bool = True
) -> dict:
    """One draft as the editor reads it, plus the two things only a draft can be wrong about.

    `files_changed_since_draft` is the drift a file upload deliberately leaves behind: uploads
    cascade into published configs, never into open drafts, so a draft can be pinned to bytes
    the library has since replaced and nothing would say so. `unresolved_files` is every
    `getfile("…")` naming no file of this source — a warning here and a refusal at publish.
    """
    changed, unresolved = services.draft_file_state(db, d)
    return {
        "id": d.id,
        "concept_id": d.concept_id,
        "source_id": d.source_id,
        "source": source_key,
        "type": d.type,
        "json": d.json_def,
        # A draft's snippet is a snippet: withheld from a caller without `can_read_detail`,
        # and flagged rather than nulled, exactly as on the published concept read.
        "py": d.python_code if detail else None,
        "py_locked": (not detail) and bool(d.python_code),
        "status": d.status,
        "version_no": d.version_no,
        "change_type": d.change_type,
        "message": d.message,
        "validation_status": d.validation_status,
        "created_by": d.created_by,
        "created_at": d.created_at,
        "files_changed_since_draft": changed,
        "unresolved_files": unresolved,
    }


def _by_name(db: Session, taxonomy: str, name: str) -> Concept:
    """The one concept a name means, for a write. 400 when the name names a group: a draft, a
    publish or a documentation edit lands on exactly one concept, and picking a member for the
    caller is precisely what must not happen."""
    return services.resolve_single(db, taxonomy, name)[1]


def _validate_or_400(source_key: str, type_: str, definition: dict) -> tuple[str, dict | None]:
    """Validate against the (source, type) schema; raise 400 on failure.

    Returns ``(validation_status, validation_report)`` for persisting on the row:
    ``"passed"`` with a report for schema-governed sources, ``"skipped"`` / None for
    sources that have no schemas yet.
    """
    result = registry.validate(source_key, type_, definition)
    if result.governed and not result.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "schema_validation_failed",
                "source": source_key,
                "type": type_,
                "errors": result.errors,
            },
        )
    return ("passed", result.report()) if result.governed else ("skipped", None)


@router.post("/concepts", status_code=201)
def create_concept(
    request: Request,
    body: ConceptCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_EDIT)),
):
    """Create a concept and register `name` for it in `taxonomy`.

    A name already in use is refused unless `confirm_group` says the caller means it: one
    identifier naming several concepts is legitimate (an ATC code covering several substances),
    but it is never what somebody re-typing an existing name intended, so it has to be asked
    for. Forming a group is kept in the audit row's `detail`.
    """
    taxonomy_key = body.taxonomy or settings.default_taxonomy
    tax = db.scalar(select(Taxonomy).where(Taxonomy.key == taxonomy_key))
    if tax is None:
        raise HTTPException(404, f"Taxonomy '{taxonomy_key}' not found")

    existing = services.resolve_pointers(db, taxonomy_key, body.name)
    active = [(ct, c) for ct, c in existing if ct.deprecated_at is None]
    if active and not body.confirm_group:
        raise HTTPException(
            409,
            {
                "error": "name_exists",
                "taxonomy": taxonomy_key,
                "name": body.name,
                "members": [
                    {
                        "id": c.id,
                        "name": ct.identifier,
                        "display_name": ct.display_name,
                        "description": c.description,
                    }
                    for ct, c in active
                ],
            },
        )

    c = Concept(description=body.description)
    db.add(c)
    db.flush()  # assign c.id before linking the taxonomy entry
    db.add(
        ConceptTaxonomy(
            concept_id=c.id,
            taxonomy_id=tax.id,
            identifier=body.name,
            display_name=body.display_name,
            origin=ORIGIN_USER,
        )
    )
    db.commit()
    db.refresh(c)
    if active:
        audit.mark_detail(
            request,
            group_formed={
                "taxonomy": taxonomy_key,
                "name": body.name,
                "members": [x.id for _, x in active] + [c.id],
            },
        )
    return {"id": c.id, "taxonomy": taxonomy_key, "name": body.name}


# --- drafts ---------------------------------------------------------------------------------
# Each operation has an id form and a name form. The name form resolves through
# `resolve_single` and then runs the very same body, so the two can never drift; the id routes
# are declared first so `/concept/id/5/drafts` isn't bound as taxonomy="id", name="5".


def _list_drafts(db: Session, concept: Concept, *, detail: bool = True) -> list[dict]:
    rows = list(
        db.scalars(
            select(Config)
            .where(Config.concept_id == concept.id, Config.status == "draft")
            .order_by(Config.id)
        )
    )
    keys = {s.id: s.key for s in db.scalars(select(Source))}
    return [_draft_out(db, d, keys.get(d.source_id), detail=detail) for d in rows]


def _open_drafts(db: Session) -> list[dict]:
    """Every unpublished draft, across all concepts, newest first — the review queue.

    The per-concept `_list_drafts` above answers "what is open on *this* concept", which only
    helps somebody already looking at it. This is the other direction: a draft is finished work
    waiting for a decision, and nothing surfaces it until a reviewer happens to open the right
    page. So the rows carry the concept's name and taxonomy too, resolved the same way an
    id-addressed response picks one (`services.display_pointer`: active, default taxonomy,
    primary name), which is what lets the queue link straight back to the draft.
    """
    rows = list(
        db.scalars(
            select(Config)
            .where(Config.status == "draft")
            .order_by(Config.created_at.desc(), Config.id.desc())
        )
    )
    if not rows:
        return []

    source_keys = {s.id: s.key for s in db.scalars(select(Source))}
    author_ids = {d.created_by for d in rows} - {None}
    authors = (
        {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(author_ids)))}
        if author_ids
        else {}
    )
    concepts = {
        c.id: c
        for c in db.scalars(select(Concept).where(Concept.id.in_({d.concept_id for d in rows})))
    }

    # One pointer lookup per *concept*, not per draft: a concept with a draft open on several
    # sources is several rows naming the same thing.
    pointers: dict[int, tuple[str | None, str | None, str | None]] = {}

    def pointer_of(concept_id: int) -> tuple[str | None, str | None, str | None]:
        if concept_id not in pointers:
            found = services.display_pointer(db, concept_id)
            pointers[concept_id] = (
                (found[1], found[0].identifier, found[0].display_name)
                if found is not None
                else (None, None, None)
            )
        return pointers[concept_id]

    out = []
    for d in rows:
        concept = concepts.get(d.concept_id)
        taxonomy, name, display_name = pointer_of(d.concept_id)
        out.append(
            {
                "id": d.id,
                "concept_id": d.concept_id,
                "taxonomy": taxonomy,
                "name": name,
                "display_name": display_name,
                "concept_deprecated_at": concept.deprecated_at if concept is not None else None,
                "source": source_keys.get(d.source_id),
                "type": d.type,
                "change_type": d.change_type,
                "message": d.message,
                "validation_status": d.validation_status,
                "author": authors.get(d.created_by),
                "created_at": d.created_at,
            }
        )
    return out


def _create_draft(db: Session, concept: Concept, body: DraftCreate, user: User) -> dict:
    if concept.deprecated_at is not None:
        raise HTTPException(
            409,
            f"Concept #{concept.id} has been deprecated and no longer accepts new versions.",
        )
    source = services.get_source_by_key(db, body.source)
    if source is None:
        raise HTTPException(404, f"Source '{body.source}' not found")

    prior = services.latest_published_for_source(db, concept.id, source.id)

    # Auto-generated (medication/laboratory) variables are read-only: they're regenerated
    # from mapping files on every import and carry no editable history. Refuse both editing
    # an existing one and minting a new config of an auto-generated type.
    if prior is not None and prior.type in settings.auto_generated_types:
        raise HTTPException(
            409,
            f"Concept #{concept.id} is an auto-generated {prior.type} variable and cannot "
            f"be edited.",
        )
    if body.type in settings.auto_generated_types:
        raise HTTPException(
            400,
            f"Type '{body.type}' is auto-generated and cannot be authored manually.",
        )

    if body.empty:
        # Fresh definition: copy nothing. type + json are mandatory (and type may differ
        # from any prior version — this is how a variable's type is changed).
        if not body.type or body.definition is None:
            raise HTTPException(400, "empty=true requires both 'type' and 'json'")
        typ, definition, code = body.type, body.definition, body.code
    else:
        # Copy from the latest published version of this (concept, source).
        if prior is None:
            raise HTTPException(
                400,
                f"No published version of '{source.key}' for concept #{concept.id} to copy "
                f"from; pass empty=true with a 'type' and 'json' to start one.",
            )
        if body.type is not None and body.type != prior.type:
            raise HTTPException(
                400,
                f"Cannot change type from '{prior.type}' to '{body.type}' while copying; "
                f"use empty=true to start a new typed definition.",
            )
        typ = prior.type
        definition = body.definition if body.definition is not None else dict(prior.json_def)
        code = body.code if body.code is not None else prior.python_code

    vstatus, vreport = _validate_or_400(source.key, typ, definition)

    d = Config(
        concept_id=concept.id,
        source_id=source.id,
        type=typ,
        json_def=definition,
        python_code=code,
        change_type=body.change_type,
        message=body.message,
        status="draft",
        version_no=None,
        created_by=user.id,
        validation_status=vstatus,
        validation_report=vreport,
    )
    db.add(d)
    db.flush()  # assign d.id before its file pins can point at it

    # Which files the draft reads is not copied from anywhere: it is read out of the snippet
    # the draft now holds (`getfile("<uuid>")`), and each reference pins the file's *current*
    # version. A draft copied from v3 therefore starts on today's bytes, not v3's — which is
    # what an author opening an editor expects, and `files_changed_since_draft` is how the
    # difference stays visible on a draft that then sits open while the library moves.
    services.sync_config_file_refs(db, d)

    db.commit()
    db.refresh(d)
    return _draft_out(db, d, source.key, detail=has_capability(user, CAN_READ_DETAIL))


def _draft_or_404(db: Session, concept: Concept, draft_id: int) -> Config:
    d = db.get(Config, draft_id)
    if d is None or d.concept_id != concept.id or d.status != "draft":
        raise HTTPException(404, "Draft not found")
    return d


def _update_draft(
    db: Session, concept: Concept, draft_id: int, body: DraftUpdate, user: User
) -> dict:
    d = _draft_or_404(db, concept, draft_id)

    if body.type is not None:
        d.type = body.type
    if body.definition is not None:
        d.json_def = body.definition
    if body.code is not None:
        d.python_code = body.code
    if body.message is not None:
        d.message = body.message
    if body.change_type is not None:
        d.change_type = body.change_type

    # Re-validate the resulting (type, json); reject before persisting.
    source = db.get(Source, d.source_id)
    d.validation_status, d.validation_report = _validate_or_400(
        source.key, d.type, d.json_def
    )
    # The snippet may have gained or lost a `getfile("…")`, so the pins are recomputed from it
    # on every edit. Unknown uuids are only reported (via `_draft_out`) — a draft is allowed to
    # be half-written, and refusing the save would make the reference impossible to fix.
    services.sync_config_file_refs(db, d)
    db.commit()
    db.refresh(d)
    return _draft_out(db, d, source.key, detail=has_capability(user, CAN_READ_DETAIL))


def _delete_draft(db: Session, concept: Concept, draft_id: int) -> Response:
    d = _draft_or_404(db, concept, draft_id)
    # The draft's file pins go with it. The bytes do not: files live in the source's library
    # and are versioned there, so discarding a draft has never anything to collect.
    db.execute(delete(ConfigFileRef).where(ConfigFileRef.config_id == d.id))
    db.delete(d)
    db.commit()
    return Response(status_code=204)


def _publish_draft(
    db: Session,
    concept: Concept,
    draft_id: int,
    body: PublishRequest,
    user: User,
    background: BackgroundTasks | None = None,
) -> dict:
    d = _draft_or_404(db, concept, draft_id)

    # Final gate: a draft must still validate at publish time (the schema on disk may have
    # changed since the draft was last edited).
    source = db.get(Source, d.source_id)
    d.validation_status, d.validation_report = _validate_or_400(
        source.key, d.type, d.json_def
    )

    # Final re-pin, and the one place an unresolved file reference is fatal. A draft may name a
    # uuid that does not exist — it is being written, and the file may not be uploaded yet. A
    # *published* version may not: it is what clients read, and a snippet reaching for a file
    # nothing can serve is a definition that cannot run. Re-pinning here also means publishing
    # picks up the current bytes of every file, which is what resolves the drift a draft warns
    # about with `files_changed_since_draft`.
    refs = services.sync_config_file_refs(db, d)
    if refs.unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unresolved_file_references",
                "source": source.key,
                "uuids": refs.unknown,
                "errors": [
                    f"getfile(\"{u}\") names no file in the '{source.key}' library"
                    for u in refs.unknown
                ],
            },
        )

    # next per-concept version number
    max_v = (
        db.scalar(
            select(func.max(Config.version_no)).where(
                Config.concept_id == concept.id, Config.status == "published"
            )
        )
        or 0
    )
    # first published row for this (concept, source) => "initial"
    prior = db.scalar(
        select(func.count())
        .select_from(Config)
        .where(
            Config.concept_id == concept.id,
            Config.source_id == d.source_id,
            Config.status == "published",
        )
    )

    d.version_no = max_v + 1
    d.status = "published"
    d.change_type = "initial" if not prior else (body.change_type or d.change_type)
    if body.message is not None:
        d.message = body.message
    if body.corrects_since_version_no is not None:
        d.corrects_since_version_no = body.corrects_since_version_no
    d.approved_by = user.id
    d.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # The pins need no further work: `config_file_ref` rows point at this row's id, and
    # publishing is a state change on that same row (draft -> published, version_no assigned),
    # not a copy. From here they are immutable — a later upload of one of those files publishes
    # a *new* version rather than re-pointing this one.

    db.commit()
    db.refresh(d)

    if body.notify and background is not None:
        # Everything the message needs is read here, off the committed row, and handed over as
        # plain values: the send runs after the response, when this session is gone.
        found = services.display_pointer(db, concept.id)
        pointer, taxonomy = found if found is not None else (None, None)
        background.add_task(
            mailer.notify_concept_published,
            concept_id=concept.id,
            concept_name=pointer.identifier if pointer is not None else f"concept {concept.id}",
            taxonomy=taxonomy,
            change_type=d.change_type,
            version_no=d.version_no,
            message=d.message,
            published_by=user.id,
        )

    return _draft_out(db, d, source.key, detail=has_capability(user, CAN_READ_DETAIL))


def _update_documentation(
    db: Session, concept: Concept, body: DocumentationUpdate, user: User
) -> dict:
    fields = body.model_fields_set
    if not fields:
        raise HTTPException(400, "No documentation fields in body")
    # Nothing here is versioned: these columns sit on `concept`, so an edit is visible on
    # every version at once and a later publish leaves it alone.

    if fields - {"doc_status"} and not has_capability(user, CAN_EDIT):
        raise HTTPException(403, f"Missing capability: {CAN_EDIT}")
    if "doc_status" in fields and not has_capability(user, CAN_PUBLISH):
        raise HTTPException(403, f"Missing capability: {CAN_PUBLISH}")

    for field in fields:
        setattr(concept, field, getattr(body, field))
    db.commit()
    # Echo the whole documentation block, not just what changed, so a client can replace its
    # copy wholesale. `notion_url` rides along because it renders with them, but it is not
    # editable here — it comes from the upstream export.
    return {f: getattr(concept, f) for f in DocumentationUpdate.model_fields} | {
        "notion_url": concept.notion_url
    }


@router.get(
    "/drafts",
    response_model=list[OpenDraftOut],
    summary="The draft review queue (all concepts)",
)
def list_open_drafts(
    db: Session = Depends(get_db),
    _reviewer: User = Depends(_review_queue),
):
    """Open drafts across every concept, newest first. Sits next to `GET /deprecation-requests`
    as the other half of what is waiting for a reviewer."""
    return _open_drafts(db)


@router.get("/concept/id/{concept_id}/drafts")
def list_drafts_by_id(
    concept_id: int,
    db: Session = Depends(get_db),
    reader: User = Depends(require_capability(CAN_READ)),
):
    return _list_drafts(
        db, concept_or_404(db, concept_id), detail=has_capability(reader, CAN_READ_DETAIL)
    )


@router.post("/concept/id/{concept_id}/drafts", status_code=201)
def create_draft_by_id(
    concept_id: int,
    body: DraftCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_EDIT)),
):
    return _create_draft(db, concept_or_404(db, concept_id), body, user)


@router.put("/concept/id/{concept_id}/drafts/{draft_id}")
def update_draft_by_id(
    concept_id: int,
    draft_id: int,
    body: DraftUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_EDIT)),
):
    return _update_draft(db, concept_or_404(db, concept_id), draft_id, body, user)


@router.delete("/concept/id/{concept_id}/drafts/{draft_id}", status_code=204)
def delete_draft_by_id(
    concept_id: int,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_EDIT)),
):
    return _delete_draft(db, concept_or_404(db, concept_id), draft_id)


@router.post("/concept/id/{concept_id}/drafts/{draft_id}/publish")
def publish_draft_by_id(
    concept_id: int,
    draft_id: int,
    body: PublishRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_PUBLISH)),
):
    return _publish_draft(
        db, concept_or_404(db, concept_id), draft_id, body, user, background
    )


@router.patch("/concept/id/{concept_id}/documentation")
def update_documentation_by_id(
    concept_id: int,
    body: DocumentationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _update_documentation(db, concept_or_404(db, concept_id), body, user)


@router.get("/concept/{taxonomy}/{name}/drafts")
def list_drafts(
    taxonomy: str,
    name: str,
    db: Session = Depends(get_db),
    reader: User = Depends(require_capability(CAN_READ)),
):
    return _list_drafts(
        db, _by_name(db, taxonomy, name), detail=has_capability(reader, CAN_READ_DETAIL)
    )


@router.post("/concept/{taxonomy}/{name}/drafts", status_code=201)
def create_draft(
    taxonomy: str,
    name: str,
    body: DraftCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_EDIT)),
):
    return _create_draft(db, _by_name(db, taxonomy, name), body, user)


@router.put("/concept/{taxonomy}/{name}/drafts/{draft_id}")
def update_draft(
    taxonomy: str,
    name: str,
    draft_id: int,
    body: DraftUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_EDIT)),
):
    return _update_draft(db, _by_name(db, taxonomy, name), draft_id, body, user)


@router.delete("/concept/{taxonomy}/{name}/drafts/{draft_id}", status_code=204)
def delete_draft(
    taxonomy: str,
    name: str,
    draft_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_EDIT)),
):
    """Discard an unpublished draft. Only `status='draft'` rows are deletable; published
    versions are immutable history and can never be removed here."""
    return _delete_draft(db, _by_name(db, taxonomy, name), draft_id)


@router.post("/concept/{taxonomy}/{name}/drafts/{draft_id}/publish")
def publish_draft(
    taxonomy: str,
    name: str,
    draft_id: int,
    body: PublishRequest,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_PUBLISH)),
):
    return _publish_draft(
        db, _by_name(db, taxonomy, name), draft_id, body, user, background
    )


@router.patch("/concept/{taxonomy}/{name}/documentation")
def update_documentation(
    taxonomy: str,
    name: str,
    body: DocumentationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Edit a concept's documentation in place: the clinical and implementation prose, the
    caveats and the workflow status.

    Partial: only the fields present in the body change; an explicit null clears a field.
    The text fields need `can_edit`; `doc_status` needs `can_publish` (a plain workflow
    flip, deliberately not tracked in the audit log). Deployments syncing documentation
    from Notion should expect these edits to be overwritten by the next reimport.
    """
    return _update_documentation(db, _by_name(db, taxonomy, name), body, user)
