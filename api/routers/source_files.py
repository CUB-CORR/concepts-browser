"""A source's file library: list, inspect, download, upload a version, retire.

Data files belong to a **source**, not to one concept's version. The same postcode table is
read by four variables, and under the older per-config model that was four rows to replace and
no answer at all to "which definitions read this?" — the question every replacement starts
with. Here it is one file with a version history, `referenced_by` says how many current
definitions read it, and `/references` names them.

Two things about the permissions, both deliberate:

* **reading the *metadata* is `can_read`.** The app's code editor completes `getfile("…")` from
  this list and marks a uuid that names nothing, and its file picker inserts from it — so
  everybody who may open an editor has to be able to fetch it. There is nothing sensitive in the
  metadata that isn't already in the concept read. The **bytes** are `can_read_detail`: the
  download route below refuses without it, loudly, rather than serving nothing.
* **uploading is `can_publish`, not `can_edit`.** An upload mints a new version of every
  concept whose current published config reads the file (see `services.cascade_file_version`).
  That is publishing, reached by another route: the definitions change what they compute, under
  new version numbers clients will pin to. Gating it on `can_edit` would let an editor publish.

Retiring is a **soft** delete and is refused with a 409 while any current published config still
reads the file — the referencing concepts come back at `detail.references` so the app can name
them instead of just reporting a conflict. It stays soft even then: older published versions
pin file versions forever, and a hard delete would break exactly the reproducibility the
versioning exists for.

Not marked `x-public`: external clients read files through the concept read (which hands out
the manifest and the per-version download URL), not by browsing a source's library.
"""
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import files as blobstore
from .. import services
from ..db import get_db
from ..deps import require_capability
from ..models import Blob, Config, ConfigFileRef, Source, SourceFile, SourceFileVersion, User
from ..schemas import FileUploadResult, SourceFileDetail, SourceFileRecord
from ..security import CAN_PUBLISH, CAN_READ, CAN_READ_DETAIL

router = APIRouter(tags=["source files"])


def _source_or_404(db: Session, key: str) -> Source:
    source = services.get_source_by_key(db, key)
    if source is None:
        raise HTTPException(404, f"Source '{key}' not found")
    return source


def _file_or_404(db: Session, source: Source, file_uuid: str) -> SourceFile:
    file = services.source_file_by_uuid(db, source.id, file_uuid)
    if file is None:
        raise HTTPException(404, f"No file '{file_uuid}' in the '{source.key}' library")
    return file


def _usernames(db: Session, user_ids: set[int | None]) -> dict[int | None, str | None]:
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    return {u.id: u.username for u in db.scalars(select(User).where(User.id.in_(ids)))}


def _record(
    file: SourceFile,
    version: SourceFileVersion,
    blob: Blob,
    author: str | None,
    referenced_by: int,
) -> dict:
    """One library row: the file as it stands now, plus how many definitions read it."""
    return {
        "uuid": file.uuid,
        "path": file.path,
        "description": file.description,
        "size": blob.size,
        "sha256": blob.sha256,
        "media_type": blob.media_type,
        "version_no": version.version_no,
        "updated_at": version.created_at,
        "updated_by": author,
        "referenced_by": referenced_by,
    }


@router.get(
    "/sources/{key}/files",
    response_model=list[SourceFileRecord],
    summary="List a source's data files",
)
def list_source_files(
    key: str,
    db: Session = Depends(get_db),
    _reader: User = Depends(require_capability(CAN_READ)),
):
    """Every live file in the source's library, at its current version, with the number of
    concepts whose current published config reads it — which is exactly how many concepts a
    new upload would publish a version of.

    Read-capability, not publish: this is what the editor completes `getfile("…")` from.
    """
    source = _source_or_404(db, key)

    # Current version per file, in one grouped query rather than one per row.
    current = (
        select(
            SourceFileVersion.file_id,
            func.max(SourceFileVersion.version_no).label("mv"),
        )
        .group_by(SourceFileVersion.file_id)
        .subquery()
    )
    rows = db.execute(
        select(SourceFile, SourceFileVersion, Blob)
        .join(current, current.c.file_id == SourceFile.id)
        .join(
            SourceFileVersion,
            (SourceFileVersion.file_id == SourceFile.id)
            & (SourceFileVersion.version_no == current.c.mv),
        )
        .join(Blob, Blob.id == SourceFileVersion.blob_id)
        .where(SourceFile.source_id == source.id, SourceFile.deleted_at.is_(None))
        .order_by(SourceFile.path)
    ).all()

    authors = _usernames(db, {v.created_by for _, v, _ in rows})
    return [
        _record(f, v, b, authors.get(v.created_by), len(services.file_references(db, f.id)))
        for f, v, b in rows
    ]


@router.get(
    "/sources/{key}/files/{file_uuid}",
    response_model=SourceFileDetail,
    summary="One data file and its version history",
)
def get_source_file(
    key: str,
    file_uuid: str,
    db: Session = Depends(get_db),
    _reader: User = Depends(require_capability(CAN_READ)),
):
    """The library row plus every version the file has had, newest first. Each entry is
    downloadable at `/sources/{key}/files/{uuid}/download?version=n`, which is how the history
    table lets somebody compare what a definition used to read with what it reads now.

    Each entry carries the `path` it was uploaded under, which is how a rename becomes visible:
    the row at the top is the file's current name, an older one may carry another. It is null
    for versions written before the column existed — read that as "the name it has now"."""
    source = _source_or_404(db, key)
    file = _file_or_404(db, source, file_uuid)

    rows = db.execute(
        select(SourceFileVersion, Blob)
        .join(Blob, Blob.id == SourceFileVersion.blob_id)
        .where(SourceFileVersion.file_id == file.id)
        .order_by(SourceFileVersion.version_no.desc())
    ).all()
    if not rows:
        raise HTTPException(404, f"File '{file_uuid}' has no stored version")

    authors = _usernames(db, {v.created_by for v, _ in rows})
    current, current_blob = rows[0]
    return {
        **_record(
            file,
            current,
            current_blob,
            authors.get(current.created_by),
            len(services.file_references(db, file.id)),
        ),
        "versions": [
            {
                "version_no": v.version_no,
                "path": v.path,
                "sha256": b.sha256,
                "size": b.size,
                "author": authors.get(v.created_by),
                "message": v.message,
                "created_at": v.created_at,
            }
            for v, b in rows
        ],
    }


@router.get(
    "/sources/{key}/files/{file_uuid}/download",
    summary="Download a data file, at any of its versions",
    response_class=Response,
)
def download_source_file(
    key: str,
    file_uuid: str,
    version: Annotated[int | None, Query(description="version number; omit for the current one")] = None,
    db: Session = Depends(get_db),
    _reader: User = Depends(require_capability(CAN_READ_DETAIL)),
):
    """The bytes of one version of one file — the current one unless `version` names another.

    A retired file is still served here: an older concept version pins one of its versions, and
    the whole point of pinning is that those bytes stay reachable.

    Needs `can_read_detail`, unlike the metadata routes around it: this is file *content*.
    """
    source = _source_or_404(db, key)
    file = services.source_file_by_uuid(db, source.id, file_uuid, include_deleted=True)
    if file is None:
        raise HTTPException(404, f"No file '{file_uuid}' in the '{source.key}' library")

    if version is None:
        row = services.current_file_version(db, file.id)
    else:
        row = db.scalar(
            select(SourceFileVersion).where(
                SourceFileVersion.file_id == file.id,
                SourceFileVersion.version_no == version,
            )
        )
    if row is None:
        raise HTTPException(404, f"File '{file_uuid}' has no version {version}")

    blob = db.get(Blob, row.blob_id)
    try:
        data = blobstore.read(blob)
    except blobstore.FileError as exc:
        # The row says the bytes exist but the store doesn't have them — the DB and the blob
        # directory have been separated. Nothing the caller can fix, so 500 and loud.
        raise HTTPException(500, str(exc)) from exc
    # Served under the name *that version* was uploaded with, not the file's current one: a
    # rename must not relabel the bytes somebody is fetching out of the history. Rows from
    # before the column existed fall back to the current path, which is what they had.
    filename = PurePosixPath(row.path or file.path).name
    return Response(
        content=data,
        media_type=blob.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": f'"{blob.sha256}"',
        },
    )


@router.get(
    "/sources/{key}/files/{file_uuid}/references",
    summary="Which concepts read this file",
)
def source_file_references(
    key: str,
    file_uuid: str,
    db: Session = Depends(get_db),
    _reader: User = Depends(require_capability(CAN_READ)),
):
    """The concepts whose **current published** config reads this file.

    Not "has ever read": an older version pins the bytes it was published against and is not
    affected by anything done here. This list is what a new upload publishes a version of, and
    what a retire is refused for.
    """
    source = _source_or_404(db, key)
    file = _file_or_404(db, source, file_uuid)
    return services.file_references(db, file.id)


@router.post(
    "/sources/{key}/files",
    response_model=FileUploadResult,
    status_code=201,
    summary="Add a data file, or a new version of one",
)
async def upload_source_file(
    key: str,
    path: Annotated[str, Form(description="the path this file is known by in the source")],
    file: Annotated[UploadFile, File(description="the file contents")],
    message: Annotated[str | None, Form(description="why this version was uploaded")] = None,
    uuid: Annotated[
        str | None,
        Form(description="replace this existing file, whatever it is currently called"),
    ] = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_PUBLISH)),
):
    """Store bytes at `path`, minting a version only when they differ from the current ones,
    and publish a new version of every concept whose current config reads the file.

    Without `uuid` the **path** picks the file: a path already in the library is a new version
    of that file, a new one creates a file (and its identity is derived from that path — see
    `models.source_file_uuid`). With `uuid` the **file** is picked directly and `path` is the
    name it should carry from now on, so a new version may rename it: the uuid is the identity,
    nothing that references the file breaks, and the library, the file page and every manifest
    minted afterwards show the new name. Renaming onto a path another file in the source holds
    is refused with a 409 `file_path_taken`.

    Identical bytes come back `unchanged: true` with an empty `bumped` and nothing written —
    re-uploading a file by accident is free, and the importer relies on the same property to
    re-walk its whole staged tree every poll without producing versions. A rename asked for
    alongside identical bytes still happens; it is the file's name, not its contents.

    Needs `can_publish`: `bumped` is a list of concept versions this call published.
    """
    source = _source_or_404(db, key)
    data = await file.read()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Size first, on its own, so an oversized body answers 413 — the request was well-formed,
    # it was just too big — while everything else the store refuses (a bad path, a suffix that
    # isn't on the allowlist) is a 400.
    try:
        blobstore.check_size(len(data))
    except blobstore.FileError as exc:
        raise HTTPException(413 if data else 400, str(exc)) from exc
    try:
        result = services.store_file_version(
            db,
            source,
            path,
            data,
            message=(message or None),
            media_type=file.content_type,
            author_id=user.id,
            now=now,
            file_uuid=(uuid or None),
        )
    except blobstore.FileError as exc:
        raise HTTPException(400, str(exc)) from exc

    # One transaction: the version row and every concept version it cascaded into land
    # together, so there is never a moment where the library has moved on but the definitions
    # reading it have not.
    db.commit()
    return {
        "uuid": result.file.uuid,
        "path": result.file.path,
        "version_no": result.version.version_no,
        "unchanged": result.unchanged,
        "bumped": result.bumped,
    }


@router.delete(
    "/sources/{key}/files/{file_uuid}",
    status_code=204,
    summary="Retire a data file",
)
def delete_source_file(
    key: str,
    file_uuid: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_capability(CAN_PUBLISH)),
):
    """Retire a file: it leaves the library and can no longer be referenced by anything new.

    A **soft** delete, always. Published configs pin file versions forever and have to keep
    serving them, so the rows and the bytes stay; what goes is the file's presence in the
    library, its completions in the editor, and its resolvability for a new `getfile("…")`.

    Refused with a 409 while any current published config still reads it, with those concepts
    at `detail.references`. Fix the definitions first — that is the reviewed change — and the
    file falls out of use by itself.
    """
    source = _source_or_404(db, key)
    file = _file_or_404(db, source, file_uuid)

    references = services.file_references(db, file.id)
    if references:
        raise HTTPException(
            409,
            {
                "error": "file_in_use",
                "message": (
                    f"'{file.path}' is read by {len(references)} published definition(s); "
                    f"remove the getfile(\"{file.uuid}\") reference from them first."
                ),
                "references": references,
            },
        )

    file.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
    file.deleted_by = user.id
    # Any draft that still names it now reports it under `unresolved_files`, which is what
    # stops it being published against a file nothing can serve.
    db.execute(
        ConfigFileRef.__table__.delete().where(
            ConfigFileRef.file_version_id.in_(
                select(SourceFileVersion.id).where(SourceFileVersion.file_id == file.id)
            ),
            ConfigFileRef.config_id.in_(
                select(Config.id).where(Config.status == "draft")
            ),
        )
    )
    db.commit()
    return Response(status_code=204)
