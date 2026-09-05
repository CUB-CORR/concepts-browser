"""Internal ops endpoints — NOT part of the public API.

Exist for the ``vars-sync`` sidecar, which feeds the API what upstream currently says. Two
ways in, because upstream says it in two ways:

* ``POST /internal/reimport`` — the sidecar stages fresh ``reference/vars.json`` +
  ``variables.py`` (and the data files those snippets read) into the shared volume and calls
  this to import them;
* ``POST /internal/variables/upsert`` — the sidecar *computes* variables (from a mapping
  table, say) and posts the rows straight in, with no file in between.

Both run the same upsert (see ``api/importer.py``): new variables become concepts, changed
ones get a new version, identical ones are left alone, and the taxonomy names the import owns
are brought in line. Neither ever removes anything. The sidecar needs no DB or upload
credentials for either; both are guarded by a shared secret and intended to be reachable only
over the compose network.

``?force=true`` is the development reset: it wipes the concept graph and rebuilds it, losing
every in-app edit and every version number. It is not what the sidecar calls.
"""
from fastapi import APIRouter, Depends, HTTPException, status

from ..config import settings
from ..deps import require_internal_token
from ..importer import ReportScope, RowsRejected, import_reference, upsert_variable_rows
from ..schemas import VariableUpsertRequest

router = APIRouter(tags=["internal"], dependencies=[Depends(require_internal_token)])


@router.post("/internal/reimport")
def reimport(force: bool = False, key_taxonomy: str | None = None):
    if force and settings.mode.upper() == "PRODUCTION":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "force=true wipes the concept graph and is disabled in MODE=PRODUCTION.",
        )
    stats = import_reference(force=force, key_taxonomy=key_taxonomy)
    if stats is None:
        return {"status": "noop"}
    return {"status": "ok", "mode": "rebuild" if force else "upsert", **stats.as_dict()}


@router.post("/internal/variables/upsert")
def upsert_variables(body: VariableUpsertRequest):
    """Upsert a batch of variables posted as rows, in one transaction.

    For a generator that owns part of a source's variables — the medication and laboratory
    definitions derived from mapping tables, say — and would otherwise have to write a
    vars.json for the file import to pick up. A row is created, versioned (`change_type`
    ``sync``) or left alone by exactly the rules the file import follows, so posting the same
    batch twice writes nothing the second time.

    **This never deprecates anything, in any mode.** ``mode=complete`` widens what the
    response's ``missing_upstream`` *reports* — stored names of `complete_for_types` that this
    batch does not carry — and that report has no side effect whatsoever. Taking a concept out
    of circulation is a reviewed decision (``api/routers/deprecation.py``), and a caller's
    claim of completeness is not that review: a generator that failed halfway through would
    otherwise retire a source's whole variable set between two polls. Anything that would
    change this has to argue with that sentence first.

    Errors come in two kinds. A malformed request — a row missing its definition, a duplicate
    name, ``mode=complete`` without types, a row outside the types it claims — is a 422 and
    nothing is written. A row the *JSON schema* turns away is skipped and itemised in
    ``errors`` (the file import's behaviour), unless ``on_invalid=reject`` makes the batch a
    422 instead; that is the default in complete mode, where a skipped row and a retired one
    would otherwise read the same in the report.
    """
    try:
        stats = upsert_variable_rows(
            [row.model_dump() for row in body.rows],
            source_key=body.source,
            key_taxonomy=body.key_taxonomy,
            scope=(
                ReportScope(True, frozenset(body.complete_for_types))
                if body.mode == "complete"
                else ReportScope(False, None)
            ),
            on_invalid=body.on_invalid or "skip",
            dry_run=body.dry_run,
        )
    except RowsRejected as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "rows rejected; nothing was written", "errors": exc.errors},
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return {
        "status": "ok",
        "mode": body.mode,
        "dry_run": body.dry_run,
        **stats.as_dict(),
    }
