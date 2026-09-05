"""The blob store behind a source's file library.

Some ``py`` snippets don't stand alone: they read a mapping table sitting next to
``variables.py`` upstream (``postcode/postcode_mapping.csv``,
``mobilisation/mobilisation_linear_svc.pkl``, …). Those files are versioned in their source's
library and referenced by a config *at a version*, or a consumer reading v3 silently runs v3's
code against today's mapping.

Bytes are kept on disk, not in the database: content-addressed at ``<file_dir>/<sha[:2]>/<sha>``,
with `Blob` holding only the digest and `SourceFileVersion` naming which version of which file
those bytes are. Two consequences that are the whole point of the design:

* a file whose bytes are re-uploaded unchanged is stored **once** — and, because the digest is
  the identity, an upload of identical bytes is recognised as a no-op rather than minting a
  version and cascading new concept versions for nothing;
* writes are idempotent — storing bytes we already have re-uses the existing blob and never
  rewrites the file, so re-running an import is free.

`path` is untrusted input from an upload or from the upstream scan, and it ends up in filesystem
paths on whoever consumes it. `normalize_path` is the only way one is allowed in: it rejects
absolute paths, ``..``, backslashes and unknown suffixes. Deleting is deliberately separate —
`delete_unreferenced` is the GC pass, because a blob is normally still referenced by an older
file version long after a newer one replaced it.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Blob, SourceFileVersion

log = logging.getLogger("concepts.files")

DEFAULT_MEDIA_TYPE = "application/octet-stream"


class FileError(ValueError):
    """A rejected attachment: a bad path, a disallowed suffix, or an oversized upload. Routers
    turn this into a 400 — every case is something the caller sent, not a server fault."""


def normalize_path(path: str) -> str:
    """Validate a relative attachment path and return it in canonical (POSIX) form.

    Everything that could escape the directory a consumer lays these files out in is refused
    rather than sanitized: an absolute path, any ``..`` segment, a Windows-style backslash (a
    separator on the consumer's side even though it is a legal filename character here), and a
    leading or empty segment. Sanitizing would silently store the file somewhere other than
    where the snippet will look for it, which is worse than a 400.
    """
    raw = (path or "").strip()
    if not raw:
        raise FileError("A file path is required")
    if "\\" in raw:
        raise FileError(f"Invalid file path {raw!r}: backslashes are not allowed")
    if raw.startswith("/") or PurePosixPath(raw).is_absolute():
        raise FileError(f"Invalid file path {raw!r}: must be relative")
    parts = PurePosixPath(raw).parts
    if any(p in ("..", ".") for p in parts):
        raise FileError(f"Invalid file path {raw!r}: '.' and '..' segments are not allowed")
    if not parts:
        raise FileError(f"Invalid file path {raw!r}")
    normalized = str(PurePosixPath(*parts))
    suffix = PurePosixPath(normalized).suffix.lower()
    if suffix not in settings.allowed_file_suffixes:
        raise FileError(
            f"File type '{suffix or normalized}' is not allowed; "
            f"allowed: {', '.join(settings.allowed_file_suffixes)}"
        )
    if len(normalized) > 512:  # matches SourceFile.path
        raise FileError("File path is too long (max 512 characters)")
    return normalized


def guess_media_type(path: str, declared: str | None = None) -> str:
    """The media type to store, preferring what the client declared over the suffix guess."""
    if declared and declared != DEFAULT_MEDIA_TYPE:
        return declared[:128]
    return (mimetypes.guess_type(path)[0] or DEFAULT_MEDIA_TYPE)[:128]


def check_size(size: int) -> None:
    """Reject an upload above the configured ceiling (see settings.max_upload_bytes)."""
    if size > settings.max_upload_bytes:
        raise FileError(
            f"File is too large ({size} bytes); the limit is {settings.max_upload_bytes} bytes"
        )
    if size == 0:
        raise FileError("File is empty")


def store(db: Session, data: bytes, media_type: str | None = None) -> Blob:
    """Put bytes in the store and return their `Blob`, re-using an existing one when the
    contents already exist. Takes the session because dedupe is a lookup by digest; the row is
    flushed (not committed) so it joins the caller's transaction."""
    digest = hashlib.sha256(data).hexdigest()
    blob = db.scalar(select(Blob).where(Blob.sha256 == digest))
    if blob is None:
        blob = Blob(
            sha256=digest, size=len(data), media_type=media_type or DEFAULT_MEDIA_TYPE
        )
        db.add(blob)
        db.flush()  # assign blob.id so the caller can reference it straight away

    # The file may be absent even for a known digest (restored DB, wiped cache), so write on
    # the "already stored" path too — but only when it isn't there. Same digest ⇒ same bytes.
    target = path_for(blob)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and rename: a reader must never see a half-written blob at
        # a path whose name promises a complete file with that digest.
        tmp = target.with_name(f".{target.name}.part")
        tmp.write_bytes(data)
        tmp.replace(target)
    return blob


def path_for(blob: Blob) -> Path:
    """Where a blob's bytes live. Sharded by the digest's first two characters so no single
    directory has to hold every file in the store."""
    return Path(settings.file_dir) / blob.sha256[:2] / blob.sha256


def read(blob: Blob) -> bytes:
    """The blob's bytes, or FileError if the store has lost them (DB and store out of sync —
    a deployment error, but one a route has to answer for rather than crash on)."""
    target = path_for(blob)
    if not target.is_file():
        raise FileError(f"Stored file {blob.sha256[:12]} is missing from the blob store")
    return target.read_bytes()


def delete_unreferenced(db: Session) -> int:
    """Drop every blob no `SourceFileVersion` points at any more, and unlink its bytes. Returns
    how many went.

    Reference counting is deliberately not tracked on the row: a blob is shared across versions
    of a file (a revert re-uses the earlier bytes) and, in principle, across files, so the only
    honest count is the one this query computes.

    Note what this does *not* collect: a file version nothing references any more. Those are
    kept forever on purpose — a published config pins one, and the whole point of pinning is
    that the bytes stay reachable. In practice this pass now only ever finds blobs left behind
    by a `source_file_version` row that never committed, which is why it went from a routine
    step to a safety net.
    """
    orphans = list(
        db.scalars(
            select(Blob).where(
                ~select(SourceFileVersion.id)
                .where(SourceFileVersion.blob_id == Blob.id)
                .exists()
            )
        )
    )
    for blob in orphans:
        target = path_for(blob)
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:  # noqa: PERF203 — one unreadable file shouldn't stop the GC
            log.warning("could not delete blob %s (%s)", target, exc)
        db.delete(blob)
    if orphans:
        log.info("blob gc: removed %d unreferenced blob(s)", len(orphans))
    return len(orphans)
