"""Downloading a concept version's data files.

A file belongs to a **source's** library and is versioned there (see
``api/routers/source_files.py``, which is where they are uploaded and retired). What a concept
version carries is a *pin*: this file uuid at this file version. These two routes serve that
pin — "give me the bytes this version of this concept was published against" — which is the
question a client running an old definition has to be able to ask.

Addressed by **uuid**, the same identifier the snippet itself uses
(``pd.read_csv(getfile("<uuid>"))``), so a client holding a snippet can build the URL from the
snippet. The concept read hands out the full manifest — uuid, path, version, digest, size —
so everything a snippet might reach for can be fetched before it runs.

Downloads run the same gate as `get_concept`: the project/license check in `concept_query`, the
same `v` / `date` / `draft` selectors, and the same `audit.mark_concept` attribution. A file is
part of the definition, so retrieving one is a concept read and is logged as one.
"""
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, files, services
from ..db import get_db
from ..deps import require_capability
from ..models import Blob, Concept, Config, ConfigFileRef, Source, SourceFile, SourceFileVersion, User
from ..schemas import ConceptFileSelector
from ..security import CAN_READ_DETAIL
from .concepts import _to_naive_utc, concept_or_404, concept_query

router = APIRouter(tags=["files"])

# Bytes are `can_read_detail`, not `can_read`: a file is an input to the snippet, and the split
# exists precisely so that reading *what a concept is* does not hand out *what it computes with*.
# A refusal here is a 403, never an empty or missing file — a client resolving a definition
# without the data it pins would silently compute something else.
_detail = require_capability(CAN_READ_DETAIL)


def _download(
    request: Request,
    db: Session,
    concept: Concept,
    taxonomy: str | None,
    name: str | None,
    file_uuid: str,
    sel: ConceptFileSelector,
) -> Response:
    if sum(p is not None for p in (sel.v, sel.date, sel.draft)) > 1:
        raise HTTPException(400, "Pass at most one of: v, date, draft")

    configs = services.latest_published_per_source(
        db, concept.id, at_version=sel.v, at_time=_to_naive_utc(sel.date)
    )
    if sel.draft is not None:
        d = db.get(Config, sel.draft)
        if d is None or d.concept_id != concept.id or d.status != "draft":
            raise HTTPException(404, "Draft not found for this concept")
        configs = [c for c in configs if c.source_id != d.source_id] + [d]

    keys = {s.id: s.key for s in db.scalars(select(Source))}
    if sel.source is not None:
        configs = [c for c in configs if keys.get(c.source_id) == sel.source]
    # A uuid belongs to exactly one file of exactly one source, so this ordering only decides
    # which config is *reported* as the one that pinned it; `source` narrows it explicitly.
    configs.sort(key=lambda c: keys.get(c.source_id) or "")

    hit: tuple[Config, SourceFileVersion, str] | None = None
    for c in configs:
        row = db.execute(
            select(SourceFileVersion, ConfigFileRef.path)
            .select_from(ConfigFileRef)
            .join(SourceFileVersion, SourceFileVersion.id == ConfigFileRef.file_version_id)
            .join(SourceFile, SourceFile.id == SourceFileVersion.file_id)
            .where(ConfigFileRef.config_id == c.id, SourceFile.uuid == file_uuid)
        ).first()
        if row is not None:
            hit = (c, row[0], row[1])
            break
    if hit is None:
        raise HTTPException(
            404, f"No file '{file_uuid}' for concept #{concept.id} at this version"
        )
    config, version, rel = hit

    audit.mark_concept(
        request,
        concept_id=concept.id,
        name=name,
        taxonomy=taxonomy,
        version=config.version_no,
        selector={
            "v": sel.v,
            "date": sel.date.isoformat() if sel.date is not None else None,
            "draft": sel.draft,
            "file": file_uuid,
            "file_version": version.version_no,
        },
    )

    blob = db.get(Blob, version.blob_id)
    try:
        data = files.read(blob)
    except files.FileError as exc:
        # The row says the file exists but the store doesn't have it: the DB and the blob
        # directory have been separated (a restore that forgot the volume). 500, not 404 —
        # nothing the caller can fix, and it must be loud.
        raise HTTPException(500, str(exc)) from exc
    return Response(
        content=data,
        media_type=blob.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{PurePosixPath(rel).name}"',
            "ETag": f'"{blob.sha256}"',
        },
    )


# The id route comes first so `/concept/id/5/...` isn't bound as taxonomy="id", name="5".


@router.get(
    "/concept/id/{concept_id}/files/{file_uuid}",
    openapi_extra={"x-public": True},
    summary="Download a concept's data file (by concept id)",
    response_class=Response,
)
def download_concept_file_by_id(
    request: Request,
    concept_id: int,
    file_uuid: str,
    sel: Annotated[ConceptFileSelector, Query()],
    db: Session = Depends(get_db),
    _ctx: User = Depends(concept_query),
    _detail_ok: User = Depends(_detail),
):
    """Stream one data file belonging to a concept's definition, addressed by concept id and
    file uuid. Takes the same selectors as the concept read — at most one of `v`, `date`/`d`,
    `draft` — so the bytes you get are the ones that version's `py` was written against. This
    is the form the `url` in a concept response carries."""
    concept = concept_or_404(db, concept_id)
    found = services.display_pointer(db, concept.id, _to_naive_utc(sel.date))
    pointer, taxonomy = found if found is not None else (None, None)
    return _download(
        request, db, concept, taxonomy,
        pointer.identifier if pointer is not None else None, file_uuid, sel,
    )


@router.get(
    "/concept/{taxonomy}/{name}/files/{file_uuid}",
    openapi_extra={"x-public": True},
    summary="Download a concept's data file",
    response_class=Response,
)
def download_concept_file(
    request: Request,
    taxonomy: str,
    name: str,
    file_uuid: str,
    sel: Annotated[ConceptFileSelector, Query()],
    db: Session = Depends(get_db),
    _ctx: User = Depends(concept_query),
    _detail_ok: User = Depends(_detail),
):
    """Stream one data file belonging to a concept's definition, addressed by name and file
    uuid. A file belongs to one concept's version, so a name that resolves to a group is an
    `ambiguous_name` 400 — use the id form."""
    _, concept = services.resolve_single(db, taxonomy, name, _to_naive_utc(sel.date))
    return _download(request, db, concept, taxonomy, name, file_uuid, sel)
