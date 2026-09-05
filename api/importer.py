"""Import of the reference datasets shipped under ``reference/``.

Each variable in a dataset's vars file is a concept, named under the key taxonomy
(``corr_v1`` by default) and carrying one **published** config per dataset source. The JSON is
validated against the per-(source, type) schema; entries that don't conform are skipped with a
warning rather than imported (a broken schema likewise skips that one entry, never aborts the
run).

Several datasets are imported in one pass, so one concept can end up carrying a config per
source — which is the point of the model. The **primary** dataset (``import_source_key``) is
the richer one: its configs also hold the matching function from ``reference/variables.py``
as their ``py`` snippet, its data files are ingested into the source's versioned library from
the tree the sidecar stages (see ``api/services.py``), and it is the one a deployment's
``special_vars`` overlay contributes generated variables and extra taxonomy names to. Every
further dataset (``reference_datasets``) is definitions-only.

A snippet reaches a data file by uuid — ``getfile("<uuid>")`` — so which files a version reads
is read out of the snippet rather than declared beside it, and a file whose *bytes* changed
makes the definition that reads it a new version even though not one character of it moved.
That holds for every definition reading the file, not only the imported ones: once the pass has
upserted its own variables it runs the same cascade an upload runs (`_cascade_ingested_files`),
so a hand-authored snippet pointing at a restaged file comes forward too.

Two things a dataset may leave to this module rather than state per variable:

* **the type.** A dataset whose upstream JSON carries no ``type`` key gets one assigned by
  the rule its source registers in ``_TYPE_RULES``, before validation and before storage — so
  what is stored is what was validated. The rule is deliberately a restatement of that
  source's schemas (see ``reference/schema/reprodicu_*.json``), which is what keeps the two
  from drifting: an entry the rule mistypes fails validation and is skipped, loudly.
* **the unit.** Upstream keeps units in a ``units.json`` beside the definitions; a dataset
  that names one has it folded into each definition as a ``unit`` field, so the unit travels
  with the version like everything else about the variable.

The pass is an **upsert** and is meant to be re-run: it resolves each variable by name in the
key taxonomy, creates what is new, versions what changed (``change_type='sync'``) and leaves
what is identical alone. It never removes anything — a variable that disappeared upstream is
reported, not deleted, because retiring a concept is a reviewed decision (see
``api/routers/deprecation.py``). ``force=True`` is the exception: a development reset that
wipes the concept graph and rebuilds it from the current files.

The key taxonomy has to be 1:1 for the incoming names: a name that already points at several
concepts there is skipped, because the import would otherwise have to guess which of them
upstream meant.
"""
from __future__ import annotations

import ast
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from . import files as blobstore
from . import services
from .config import settings
from .db import SessionLocal
from .models import (
    ORIGIN_IMPORT,
    AuditLog,
    Concept,
    ConceptTaxonomy,
    Config,
    ConfigFileRef,
    DeprecationRequest,
    Source,
    SourceFile,
    Taxonomy,
    User,
)
from .schema_registry import registry
from .special_vars import load_special_variables

log = logging.getLogger("concepts.import")

# How many skipped rows an ImportStats itemises. The counters stay exact; this only bounds the
# per-row detail, so a caller posting thousands of rows gets a usable diagnosis instead of a
# response the size of its own request.
MAX_REPORTED_ERRORS = 50


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass
class ImportStats:
    imported: int = 0             # variables that became a new concept (or a source's first config)
    updated: int = 0              # variables whose definition changed upstream -> new version
    unchanged: int = 0            # variables identical to what is stored
    with_python: int = 0
    attached_files: int = 0       # file versions the imported configs ended up pinned to
    # Concept versions minted by the file cascade rather than by the upsert: definitions this
    # import does not own whose data file was restaged. Its own counter because imported +
    # updated + unchanged partitions the *upstream variables*, and these are not among them.
    files_synced: int = 0
    skipped_invalid: int = 0      # no usable type, or failed/un-runnable schema validation
    skipped_existing: int = 0     # the (concept, source) already had a config
    skipped_ambiguous: int = 0    # the name points at several concepts in the key taxonomy
    pointers_added: int = 0
    pointers_deprecated: int = 0
    pointers_adopted: int = 0     # user-created rows the import now maintains
    unmatched_python: list[str] = field(default_factory=list)  # functions with no variable
    missing_upstream: list[str] = field(default_factory=list)  # stored, no longer offered
    # Why individual variables were skipped, bounded to MAX_REPORTED_ERRORS. The file path has
    # the container log for this; a client posting rows over HTTP has only what comes back.
    errors: list[dict] = field(default_factory=list)

    def note(self, name: str, reason: str, detail: str | None = None) -> None:
        """Record why one variable was skipped, up to the reporting bound."""
        if len(self.errors) < MAX_REPORTED_ERRORS:
            self.errors.append({"name": name, "reason": reason, "detail": detail})

    def log_summary(self, source_key: str) -> None:
        log.info(
            "reference import for %r: %d new, %d updated, %d unchanged (%d with python, "
            "%d file attachment(s)), %d file-sync version(s), %d skipped invalid, %d skipped "
            "existing, %d skipped ambiguous; pointers +%d/-%d (%d adopted); %d python "
            "function(s) matched no variable: %s",
            source_key,
            self.imported,
            self.updated,
            self.unchanged,
            self.with_python,
            self.attached_files,
            self.files_synced,
            self.skipped_invalid,
            self.skipped_existing,
            self.skipped_ambiguous,
            self.pointers_added,
            self.pointers_deprecated,
            self.pointers_adopted,
            len(self.unmatched_python),
            ", ".join(self.unmatched_python) or "(none)",
        )
        if self.missing_upstream:
            # Not an error and not acted on: upstream dropping a variable is a signal for a
            # human, since taking a concept out of circulation is a reviewed decision.
            log.info(
                "reference import for %r: %d stored variable(s) no longer offered upstream: %s",
                source_key, len(self.missing_upstream), ", ".join(self.missing_upstream),
            )

    def merge(self, other: ImportStats) -> None:
        """Fold another dataset's counts in, so one pass over several datasets reports once."""
        self.imported += other.imported
        self.updated += other.updated
        self.unchanged += other.unchanged
        self.with_python += other.with_python
        self.attached_files += other.attached_files
        self.files_synced += other.files_synced
        self.skipped_invalid += other.skipped_invalid
        self.skipped_existing += other.skipped_existing
        self.skipped_ambiguous += other.skipped_ambiguous
        self.pointers_added += other.pointers_added
        self.pointers_deprecated += other.pointers_deprecated
        self.pointers_adopted += other.pointers_adopted
        self.unmatched_python += other.unmatched_python
        self.missing_upstream += other.missing_upstream
        self.errors += other.errors
        del self.errors[MAX_REPORTED_ERRORS:]

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "with_python": self.with_python,
            "attached_files": self.attached_files,
            "files_synced": self.files_synced,
            "skipped_invalid": self.skipped_invalid,
            "skipped_existing": self.skipped_existing,
            "skipped_ambiguous": self.skipped_ambiguous,
            "pointers_added": self.pointers_added,
            "pointers_deprecated": self.pointers_deprecated,
            "pointers_adopted": self.pointers_adopted,
            "unmatched_python": self.unmatched_python,
            "missing_upstream": self.missing_upstream,
            "errors": self.errors,
        }


@dataclass(frozen=True)
class ReferenceDataset:
    """One source's bundled definitions and the optional extras that travel with them.

    Only the primary dataset has the last four: Python snippets, their data files and the
    variables a deployment's ``special_vars`` overlay generates are all things a *deployment's
    own* source has, not something a second bundled dataset brings along.
    """

    source_key: str
    # None = the authored layer is deliberately off (a deployment past its vars.json
    # migration imports only what special_vars generates).
    vars_file: Path | None
    units_file: Path | None = None
    # Optional `{variable: {taxonomy_key: [identifier, ...]}}` map naming the dataset's
    # variables in taxonomies other than the key one (LOINC, SNOMED, ...). Same shape
    # `special_vars` returns and the `/internal/variables/upsert` rows carry, so all three
    # pointer sources meet in `_sync_pointers` and stay import-owned.
    pointers_file: Path | None = None
    python_file: Path | None = None
    files_dir: Path | None = None
    special_vars: bool = False


def _datasets() -> list[ReferenceDataset]:
    """The primary dataset followed by the ones `reference_datasets` adds."""
    primary = ReferenceDataset(
        source_key=settings.import_source_key,
        vars_file=Path(settings.reference_vars_file) if settings.reference_vars_file else None,
        units_file=Path(settings.reference_units_file) if settings.reference_units_file else None,
        python_file=Path(settings.reference_python_file) if settings.reference_python_file else None,
        files_dir=Path(settings.reference_files_dir),
        pointers_file=(
            Path(settings.reference_pointers_file) if settings.reference_pointers_file else None
        ),
        special_vars=True,
    )
    out = [primary]
    for entry in settings.reference_datasets:
        key = (entry.get("source") or "").strip()
        vars_file = (entry.get("vars") or "").strip()
        if not key or not vars_file:
            log.warning("reference dataset %r names no source/vars file; ignoring", entry)
            continue
        if key in {d.source_key for d in out}:
            # Two datasets for one source would import the second into a source the first has
            # just populated — i.e. skipped_existing for every variable. Say so instead.
            log.warning("reference dataset for %r is already configured; ignoring %r", key, entry)
            continue
        units = (entry.get("units") or "").strip()
        ptrs = (entry.get("pointers") or "").strip()
        out.append(
            ReferenceDataset(
                source_key=key,
                vars_file=Path(vars_file),
                units_file=Path(units) if units else None,
                pointers_file=Path(ptrs) if ptrs else None,
            )
        )
    return out


def _reprodicu_type(definition: dict) -> str:
    """reprodICU's type, derived from which keys the entry carries.

    Upstream authors these definitions without a ``type``, but the shape already says what
    the variable is: a ``calculation`` makes it derived rather than native, and the ``dynamic``
    flag — only ever written out to mark the per-stay values — makes it static rather than
    time-resolved. The four ``reference/schema/reprodicu_*.json`` encode the same rule from
    the other side, so a mis-derived type cannot pass validation.
    """
    kind = "derived" if "calculation" in definition else "native"
    tense = "dynamic" if definition.get("dynamic", True) else "static"
    return f"{kind}_{tense}"


# Sources whose upstream definitions carry no `type` of their own. Anything not listed here
# keeps stating its type in the JSON, which stays the default and the simpler contract.
_TYPE_RULES: dict[str, Callable[[dict], str]] = {"reprodicu": _reprodicu_type}


def _load_variables(path: Path) -> dict[str, dict]:
    """The ``variables`` mapping from ``vars.json`` (empty if the file is missing/unreadable)."""
    if not path.is_file():
        log.warning("reference vars file %s not found; skipping its dataset", path)
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read %s (%s); skipping its dataset", path, exc)
        return {}
    return data.get("variables") or {}


def _load_pointers(path: Path | None) -> dict[str, dict[str, list[str]]]:
    """``{variable: {taxonomy_key: [identifier, ...]}}`` from a dataset's pointers file.

    Empty when the dataset ships none. Entries naming a variable the dataset does not define
    are kept as-is: `_sync_pointers` only ever looks up the names it is importing, so a file
    that outlives a variable costs nothing, and a taxonomy that is not seeded is warned about
    and skipped there rather than here.
    """
    if path is None:
        return {}
    if not path.is_file():
        log.warning("pointers file %s not found; importing definitions without pointers", path)
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read pointers file %s (%s); importing without pointers", path, exc)
        return {}
    if not isinstance(data, dict):
        log.warning("pointers file %s is not an object; importing without pointers", path)
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    for name, by_tax in data.items():
        if not isinstance(by_tax, dict):
            log.warning("pointers file %s: entry %r is not an object; skipping", path, name)
            continue
        clean = {
            tax: [str(i) for i in ids]
            for tax, ids in by_tax.items()
            # An empty list would tell `_sync_pointers` to retire every import-owned name in
            # that taxonomy. A file that merely says nothing about one must not do that.
            if isinstance(ids, list) and ids
        }
        if clean:
            out[name] = clean
    return out


def _load_units(path: Path | None) -> dict[str, str]:
    """``{variable: unit}`` from a dataset's units file (empty when it has none).

    Only usable units come back. Upstream writes ``null`` or ``""`` for the dimensionless
    variables (scores, flags, categories) and its file also outlives variables that vars.json
    no longer defines — neither is an error, and neither should reach a definition.
    """
    if path is None:
        return {}
    if not path.is_file():
        log.warning("units file %s not found; importing definitions without units", path)
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read units file %s (%s); importing without units", path, exc)
        return {}
    if not isinstance(data, dict):
        log.warning("units file %s is not an object; importing without units", path)
        return {}
    return {k: v.strip() for k, v in data.items() if isinstance(v, str) and v.strip()}


def _prepare(
    variables: dict[str, dict], source_key: str, units: dict[str, str]
) -> dict[str, dict]:
    """The definitions as they will be validated *and* stored, for one dataset.

    Everything the import derives rather than reads — the type for sources that don't state
    one, the unit from the separate units file — is materialised here, so the JSON that goes
    through schema validation is byte-for-byte the JSON that lands in the config. Upstream's
    own keys are never rewritten: a consumer that drops the two added ones is back at the
    entry as authored.
    """
    rule = _TYPE_RULES.get(source_key)
    prepared: dict[str, dict] = {}
    for name, definition in variables.items():
        if not isinstance(definition, dict):
            prepared[name] = definition
            continue
        out = dict(definition)
        if rule is not None and "type" not in out:
            out = {"type": rule(definition), **out}
        if unit := units.get(name):
            out["unit"] = unit
        prepared[name] = out
    if units:
        log.info(
            "%s: folded units into %d of %d variable(s) (%d unit(s) named no variable)",
            source_key,
            sum(1 for n in prepared if n in units),
            len(prepared),
            sum(1 for n in units if n not in prepared),
        )
    return prepared


def _python_snippets(path: Path) -> dict[str, str]:
    """Map ``{function_name: source_text}`` for every top-level def in ``variables.py``.

    Every top-level function in that file is a variable function (signature
    ``(var, cohort, …)``); module imports and nested helpers are not module-level ``def``s,
    so reading only the module body's function nodes already drops "the stuff that's not
    variable functions". A function's name is the variable it implements.
    """
    if not path.is_file():
        log.warning("reference python file %s not found; importing variables without snippets", path)
        return {}
    src = path.read_text()
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        log.warning("could not parse %s (%s); importing variables without snippets", path, exc)
        return {}
    snippets: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            segment = ast.get_source_segment(src, node)
            if segment:
                snippets[node.name] = segment
    return snippets


@dataclass(frozen=True)
class ReportScope:
    """Which stored names a payload is entitled to call "no longer offered upstream".

    A payload only ever sees part of what a source stores, so "missing" is a claim it has to
    earn. `report=False` says the payload knows nothing about completeness and the comparison
    is skipped entirely; `types=None` says it speaks for every stored name of its source, and
    a set of types narrows it to those.
    """

    report: bool
    types: frozenset[str] | None = None


@dataclass
class _Payload:
    """Everything one dataset's files say, loaded and normalized."""

    source: Source
    variables: dict[str, dict]
    pointers: dict[str, dict[str, list[str]]]
    snippets: dict[str, str]
    files_root: Path | None
    # What this payload may claim to be complete for (see `_missing_upstream`).
    scope: ReportScope


def _payload(db: Session, dataset: ReferenceDataset) -> _Payload | None:
    """Read one dataset off disk, or None when there is nothing to import from it."""
    source = db.scalar(select(Source).where(Source.key == dataset.source_key))
    if source is None:
        log.warning("import source %r not seeded; skipping its dataset", dataset.source_key)
        return None

    variables = _load_variables(dataset.vars_file) if dataset.vars_file else {}
    # The names this dataset carries in other taxonomies, as shipped beside its vars file.
    pointers: dict[str, dict[str, list[str]]] = _load_pointers(dataset.pointers_file)
    if dataset.special_vars:
        # Variables a deployment generates rather than authors, plus the extra taxonomy names
        # they come with (see api/special_vars.py). Imported alongside the authored ones.
        generated, generated_pointers = load_special_variables()
        variables.update(generated)
        pointers.update(generated_pointers)
    if not variables:
        return None

    return _Payload(
        source=source,
        variables=_prepare(variables, source.key, _load_units(dataset.units_file)),
        pointers=pointers,
        snippets=_python_snippets(dataset.python_file) if dataset.python_file else {},
        files_root=dataset.files_dir,
        # With the authored layer on, the files are the whole of what this source offers. With
        # it off, only the generated (auto-typed) names can be judged against the payload —
        # everything authored is absent by design, not missing.
        scope=(
            ReportScope(True, None)
            if dataset.vars_file is not None
            else ReportScope(True, frozenset(settings.auto_generated_types))
        ),
    )


def _validated_type(source_key: str, name: str, definition: dict, stats: ImportStats):
    """The entry's type and validation result, or None when it must be skipped."""
    type_ = definition.get("type") if isinstance(definition, dict) else None
    if not type_:
        log.warning("variable %r has no 'type'; skipping", name)
        stats.skipped_invalid += 1
        stats.note(name, "no_type", "the definition names no type")
        return None

    # A schema that can't even be run (e.g. a non-Python-compatible regex) must skip this one
    # entry, not abort the whole pass — so the validate call is guarded.
    try:
        result = registry.validate(source_key, type_, definition)
    except Exception as exc:  # noqa: BLE001 — one bad schema shouldn't sink the import
        log.warning("variable %r (%s) could not be validated (%s); skipping", name, type_, exc)
        stats.skipped_invalid += 1
        stats.note(name, "unvalidatable", f"{type_}: {exc}")
        return None
    if result.governed and not result.ok:
        detail = "; ".join(f"{e['path']}: {e['message']}" for e in result.errors[:3])
        log.warning("variable %r (%s) does not fit its schema; skipping: %s", name, type_, detail)
        stats.skipped_invalid += 1
        stats.note(name, "schema", f"{type_}: {detail}")
        return None
    return type_, result


def _mint(
    db: Session,
    payload: _Payload,
    ctx_versions: dict[int, int],
    *,
    concept_id: int,
    type_: str,
    definition: dict,
    py: str | None,
    change_type: str,
    message: str | None,
    result,
    author_id: int | None,
    now: datetime,
    stats: ImportStats,
) -> Config:
    """Add one published config for an imported variable, and pin the files its snippet reads.

    The row itself is `services.mint_published_version`, shared with the publish path and the
    file cascade so an imported version and a cascaded one are the same kind of thing. What is
    local to the import is the pinning that follows: the snippet's `getfile("…")` calls are
    resolved against the source's library, which this pass has already brought up to date (see
    `_ingest_source_files`), so a definition lands pinned to the bytes that were staged with it.
    """
    config = services.mint_published_version(
        db,
        concept_id=concept_id,
        source_id=payload.source.id,
        type_=type_,
        definition=definition,
        py=py,
        change_type=change_type,
        message=message,
        validation_status="passed" if result.governed else "skipped",
        validation_report=result.report() if result.governed else None,
        author_id=author_id,
        now=now,
        versions=ctx_versions,
    )
    if py:
        refs = services.sync_config_file_refs(db, config)
        stats.attached_files += len(services.config_pinned_versions(db, config.id))
        if refs.unknown:
            # An imported snippet naming a file the library doesn't have. Not fatal — the
            # definition is still what upstream says — but it will not run, so it is loud.
            log.warning(
                "imported config #%d references %d unknown file uuid(s): %s",
                config.id, len(refs.unknown), ", ".join(refs.unknown),
            )
    return config


def _ingest_source_files(
    db: Session, source: Source, root: Path, now: datetime
) -> list[SourceFile]:
    """Bring a source's file library up to date from the tree the sidecar staged. Returns the
    files whose version actually advanced in this pass.

    Walking the tree **is** the truth: there is no manifest saying which variable needs which
    file, because a snippet says so itself (`getfile("<uuid>")`) and the API is the only thing
    that knows what uuid a path was given. So every data file under `root` is a file of this
    source, and a file whose bytes match its current version is left alone.

    `cascade=False` here is about *ordering*, not about skipping the cascade. The variable
    upsert runs immediately after this and mints its own version for every definition whose
    files moved; cascading now as well would give one replaced mapping table two versions in a
    single pass. The cascade runs afterwards instead, over exactly the files returned here (see
    `_cascade_ingested_files`), where the already-pinned guard makes the upsert's own versions
    a no-op and only the definitions the import does not own are brought forward.

    Files upstream *deleted* are not retired here. A staging tree that failed to populate would
    otherwise retire a source's whole library, and unlike a definition there is no
    "reported, not acted on" middle ground — retiring is a decision, made in the app.
    """
    if not root.is_dir():
        return []
    minted: list[SourceFile] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        try:
            result = services.store_file_version(
                db,
                source,
                rel,
                path.read_bytes(),
                message=settings.sync_import_message,
                now=now,
                cascade=False,
            )
        except blobstore.FileError as exc:
            log.warning("staged file %r is not storable (%s); skipping it", rel, exc)
            continue
        if not result.unchanged:
            minted.append(result.file)
    if minted:
        log.info(
            "%s: %d staged data file(s) changed and were versioned", source.key, len(minted)
        )
    return minted


def _cascade_ingested_files(
    db: Session,
    files: list[SourceFile],
    *,
    author_id: int | None,
    now: datetime,
    stats: ImportStats,
) -> None:
    """Run the file-update cascade for the files this pass restaged, after the upsert.

    Same machinery an upload goes through (`services.cascade_file_version`), same rules: current
    published configs of live concepts only, auto-generated types and deprecated concepts out,
    ``change_type="sync"`` with the file-sync message naming the file. Only the files whose
    version advanced in *this* run are passed in, so an unchanged tree cascades nothing and a
    re-run stays free.

    What the guard inside the cascade does here is the whole point of running it after the
    upsert: a config the upsert just minted already pins the new file version, so it is skipped
    and no definition gets two versions for one replaced file. What is left is the configs the
    import does not own — a snippet somebody wrote in the browser that reads a staged file by
    uuid — which would otherwise sit pinned to bytes the source has replaced, indefinitely and
    silently. Attribution is the import's own author (the bootstrap admin), because this is the
    import acting, not whoever happened to write the snippet.
    """
    for file in files:
        bumped = services.cascade_file_version(db, file, author_id=author_id, now=now)
        stats.files_synced += len(bumped)
        if bumped:
            log.info(
                "restaged file %r published %d dependent concept version(s): %s",
                file.path, len(bumped), ", ".join(str(b["name"]) for b in bumped),
            )


def _import_message(type_: str) -> str:
    """Auto-generated types carry a fixed "not versioned" message in place of a changelog."""
    return (
        settings.special_import_message
        if type_ in settings.auto_generated_types
        else settings.import_message
    )


def _matches_stored(prior: Config, type_: str, definition: dict, py: str | None) -> bool:
    """Whether the stored version already says exactly what upstream now says.

    Compared after a JSON round-trip so a tuple that came out of a generator and the list it
    was stored as are the same thing, and with empty python normalized to None — the difference
    between "" and NULL is not a change anybody wants a version for.
    """
    if prior.type != type_:
        return False
    if (prior.python_code or None) != (py or None):
        return False
    stored = json.loads(json.dumps(prior.json_def, sort_keys=True, default=str))
    incoming = json.loads(json.dumps(definition, sort_keys=True, default=str))
    return stored == incoming


def _files_match(db: Session, prior: Config, source_id: int, py: str | None) -> bool:
    """Whether the stored version already reads the file versions this snippet resolves to now.

    A definition can stay word-for-word the same while the mapping table its snippet reads is
    replaced, and a client pinned to a version has to get the table that version was written
    against — so a changed file is a changed definition and earns its own version.

    The comparison is between the *versions* the stored row pinned and the versions the same
    `getfile("…")` calls point at today. `_ingest_source_files` has already run by this point,
    so a file staged with new bytes is already at a new version here, and the mismatch is what
    makes the variable version. Nothing is compared by digest a second time.
    """
    return services.config_pinned_versions(db, prior.id) == services.snippet_current_versions(
        db, source_id, py
    )


@dataclass
class _Context:
    """What every payload of one pass is applied against: where names are resolved, who the
    rows are attributed to, and the version numbers already handed out in this pass."""

    key_tax: Taxonomy
    taxonomies: dict[str, Taxonomy]
    author_id: int | None
    now: datetime
    versions: dict[int, int] = field(default_factory=dict)


def _context(db: Session, key_taxonomy: str | None) -> _Context | None:
    """Set one pass up, or None when the taxonomy it would key on is not seeded."""
    tax_key = key_taxonomy or settings.default_taxonomy
    key_tax = db.scalar(select(Taxonomy).where(Taxonomy.key == tax_key))
    if key_tax is None:
        log.warning("key taxonomy %r not seeded; skipping reference import", tax_key)
        return None
    admin = db.scalar(select(User).where(User.username == settings.bootstrap_admin_username))
    return _Context(
        key_tax=key_tax,
        taxonomies={t.key: t for t in db.scalars(select(Taxonomy))},
        author_id=admin.id if admin else None,
        now=_utcnow(),
    )


def apply_payload(
    db: Session, payload: _Payload, ctx: _Context, *, force: bool = False
) -> ImportStats:
    """Apply one payload — whatever loaded it — and report what it did.

    The seam every source of variables goes through: a dataset read off disk (`_payload`) and
    a batch of rows posted to the API are the same thing by the time they get here, and are
    upserted by exactly the same rules. Nothing below this line knows about files.
    """
    stats = ImportStats()
    if force:
        _rebuild_dataset(
            db, payload, ctx.key_tax, ctx.taxonomies, ctx.versions, ctx.author_id, ctx.now, stats
        )
    else:
        _upsert_dataset(
            db, payload, ctx.key_tax, ctx.taxonomies, ctx.versions, ctx.author_id, ctx.now, stats
        )
    stats.unmatched_python = sorted(set(payload.snippets) - set(payload.variables))
    stats.log_summary(payload.source.key)
    return stats


class RowsRejected(Exception):
    """A posted batch was refused whole, before anything was written."""

    def __init__(self, errors: list[dict]) -> None:
        super().__init__(f"{len(errors)} row(s) rejected")
        self.errors = errors


def upsert_variable_rows(
    rows: list[dict],
    *,
    source_key: str | None = None,
    key_taxonomy: str | None = None,
    scope: ReportScope = ReportScope(False, None),
    on_invalid: str = "skip",
    dry_run: bool = False,
) -> ImportStats:
    """Upsert variables handed over as rows rather than read off disk.

    Each row is ``{name, type?, definition, python?, pointers?}`` — the same three things a
    dataset's files carry per variable, minus the file attachments, which only the primary
    dataset's staged tree has. They go through `apply_payload`, so a posted variable is
    created, versioned or left alone by exactly the rules a file-driven import follows, and a
    definition identical to what is stored writes nothing.

    **Nothing here deprecates anything.** `scope` only decides what the returned
    `missing_upstream` *reports*; the report has no side effect, in any mode. Retiring a
    concept is a reviewed decision (see ``api/routers/deprecation.py``), and a caller claiming
    completeness is not that review — a generator that fell over mid-run would otherwise take
    a whole source out of circulation between two polls.

    `on_invalid="reject"` validates every row first and raises `RowsRejected` without writing,
    for callers who cannot tell a row the schema turned away from one they never sent.
    `dry_run` runs the whole thing and rolls back.
    """
    with SessionLocal() as db:
        key = source_key or settings.import_source_key
        source = db.scalar(select(Source).where(Source.key == key))
        if source is None:
            raise LookupError(f"source {key!r} is not seeded")
        ctx = _context(db, key_taxonomy)
        if ctx is None:
            raise LookupError(
                f"key taxonomy {key_taxonomy or settings.default_taxonomy!r} is not seeded"
            )

        payload = _Payload(
            source=source,
            variables={row["name"]: _row_definition(row) for row in rows},
            pointers={r["name"]: r["pointers"] for r in rows if r.get("pointers")},
            snippets={r["name"]: r["python"] for r in rows if r.get("python")},
            files_root=None,
            scope=scope,
        )

        if on_invalid == "reject":
            # A pre-pass, so a batch that would lose rows is refused as a whole rather than
            # half-applied: the caller can fix its generator and post again unchanged.
            checked = ImportStats()
            for name, definition in payload.variables.items():
                _validated_type(source.key, name, definition, checked)
            if checked.errors:
                raise RowsRejected(checked.errors)

        stats = apply_payload(db, payload, ctx)
        if dry_run:
            db.rollback()
            log.info("row upsert for %r: dry run, rolled back", source.key)
        else:
            db.commit()
        return stats


def _row_definition(row: dict) -> dict:
    """The definition as it will be validated and stored, with the row's `type` folded in.

    The type may be stated either inside the definition or beside it, and the schemas the
    definition is validated against are ``additionalProperties: false`` — so this adds the one
    key they expect and nothing else. No provenance (who posted it, when, from what) goes in
    here: it would fail validation, and a definition is what the variable *is*, not where it
    came from.
    """
    definition = dict(row["definition"])
    if row.get("type") and "type" not in definition:
        definition = {"type": row["type"], **definition}
    return definition


def import_reference(
    force: bool = False, key_taxonomy: str | None = None
) -> ImportStats | None:
    """Import every configured reference dataset (see ``_datasets``), upserting by name.

    Returns the combined stats, or ``None`` when the import is disabled or no dataset had
    anything to import — because its source isn't seeded or its files are missing.

    `key_taxonomy` is the taxonomy the variable names are resolved in; it must be 1:1 for them
    and defaults to ``settings.default_taxonomy``. New concepts are named in it, and it is also
    where importer-owned pointers from other taxonomies hang off the concepts it finds.

    ``force=True`` is a development reset, not the production path: it **wipes the whole
    concept graph (file pins, configs, concept↔taxonomy names, and concepts), then rebuilds it
    from the current source files** — so the reference data mirrors upstream exactly, including
    removed or renamed variables. The wipe spans every source because the datasets share
    concepts, and a rebuild that kept another source's configs would resurrect them under
    freshly minted concept ids. The scaffolding the import needs (source, taxonomy, bootstrap
    admin) is left intact, the sources' **file libraries are left intact** (see `_wipe_graph`),
    and audit rows are kept but detached from the concepts they named.
    """
    if not settings.import_reference_on_first_run and not force:
        return None

    with SessionLocal() as db:
        ctx = _context(db, key_taxonomy)
        if ctx is None:
            return None

        if force:
            _wipe_graph(db)

        key_tax = ctx.key_tax
        taxonomies = ctx.taxonomies

        stats = ImportStats()
        imported_any = False
        for dataset in _datasets():
            payload = _payload(db, dataset)
            if payload is None:
                continue
            # The library first, the definitions second. The upsert decides whether a variable
            # changed partly by which file versions its snippet now resolves to, so the files
            # have to be current before it looks — and they are ingested with the cascade off,
            # because that same upsert is what versions the definitions reading them.
            restaged: list[SourceFile] = []
            if payload.files_root is not None:
                restaged = _ingest_source_files(db, payload.source, payload.files_root, ctx.now)
            dataset_stats = apply_payload(db, payload, ctx, force=force)
            # ...and the cascade third, over the files that actually moved, so a definition this
            # import does not own does not stay pinned to bytes the source has replaced.
            _cascade_ingested_files(
                db, restaged, author_id=ctx.author_id, now=ctx.now, stats=dataset_stats
            )
            stats.merge(dataset_stats)
            imported_any = True

        if not imported_any:
            # Nothing was written, so nothing may be committed — a forced run that found no
            # dataset must leave the wipe above unwritten rather than empty the database.
            return None

        # A safety net rather than a routine step now that file bytes are kept for as long
        # as any file version names them: this only ever finds blobs a version row abandoned.
        blobstore.delete_unreferenced(db)
        # Documentation names may live in a different taxonomy than the key taxonomy
        # (NOTION_DOCS_TAXONOMY; empty = the key one used above).
        docs_tax = key_tax
        if settings.notion_docs_taxonomy and settings.notion_docs_taxonomy != key_tax.key:
            docs_tax = taxonomies.get(settings.notion_docs_taxonomy)
        if docs_tax is None:
            log.warning(
                "notion docs taxonomy %r not found; skipping documentation import",
                settings.notion_docs_taxonomy,
            )
        else:
            _apply_notion_docs(db, docs_tax, Path(settings.reference_notion_docs_file))
        db.commit()
        return stats


def _wipe_graph(db: Session) -> None:
    """Clear the concept graph so a forced import rebuilds it from scratch.

    Order respects FKs (config_file_ref -> config -> concept_taxonomy -> concept).

    The source **file libraries survive**. Only the pins go: a file belongs to its source, not
    to the concept graph, and the versions published configs pinned are the whole reason it is
    versioned at all. A reset that took the libraries with it would also take every uuid with
    them, so every `getfile("…")` in the rebuilt snippets would resolve to nothing — the
    reimport would destroy exactly what it is meant to restore.
    """
    db.execute(delete(ConfigFileRef))
    db.execute(delete(Config))
    db.execute(delete(DeprecationRequest))
    db.execute(delete(ConceptTaxonomy))
    # Audit rows outlive the graph and point into it. Detach them first: the rebuild mints ids
    # from 1 again, so a kept concept_id would silently name a *different* concept. The row's
    # concept_name/taxonomy/concept_version still say what was read.
    db.execute(update(AuditLog).where(AuditLog.concept_id.is_not(None)).values(concept_id=None))
    db.execute(delete(Concept))
    db.flush()
    log.info("reimport: wiped concept graph before rebuilding")


def _rebuild_dataset(
    db: Session,
    payload: _Payload,
    key_tax: Taxonomy,
    taxonomies: dict[str, Taxonomy],
    versions: dict[int, int],
    author_id: int | None,
    now: datetime,
    stats: ImportStats,
) -> None:
    """The forced path: every variable becomes a fresh concept + config, no comparison."""
    for name, definition in payload.variables.items():
        checked = _validated_type(payload.source.key, name, definition, stats)
        if checked is None:
            continue
        type_, result = checked

        ct = db.scalar(
            select(ConceptTaxonomy).where(
                ConceptTaxonomy.taxonomy_id == key_tax.id,
                ConceptTaxonomy.identifier == name,
            )
        )
        if ct is not None:
            concept_id = ct.concept_id
            if db.scalar(
                select(func.count())
                .select_from(Config)
                .where(Config.concept_id == concept_id, Config.source_id == payload.source.id)
            ):
                stats.skipped_existing += 1
                stats.note(name, "existing", f"{payload.source.key} already configures it")
                continue
        else:
            concept = Concept(description=None)
            db.add(concept)
            db.flush()  # assign concept.id before linking / configuring
            concept_id = concept.id
            db.add(
                ConceptTaxonomy(
                    concept_id=concept_id,
                    taxonomy_id=key_tax.id,
                    identifier=name,
                    display_name=None,
                    origin=ORIGIN_IMPORT,
                    created_at=now,
                )
            )

        py = payload.snippets.get(name)
        _mint(
            db,
            payload,
            versions,
            concept_id=concept_id,
            type_=type_,
            definition=definition,
            py=py,
            # Per (concept, source): every dataset's config is that source's first, whatever
            # number the concept-wide sequence gave it.
            change_type="initial",
            message=_import_message(type_),
            result=result,
            author_id=author_id,
            now=now,
            stats=stats,
        )
        stats.imported += 1
        if py:
            stats.with_python += 1
        _sync_pointers(db, concept_id, payload.pointers.get(name), taxonomies, now, stats)


def _upsert_dataset(
    db: Session,
    payload: _Payload,
    key_tax: Taxonomy,
    taxonomies: dict[str, Taxonomy],
    versions: dict[int, int],
    author_id: int | None,
    now: datetime,
    stats: ImportStats,
) -> None:
    """The production path: create what is new, version what changed, leave the rest alone."""
    for name, definition in payload.variables.items():
        checked = _validated_type(payload.source.key, name, definition, stats)
        if checked is None:
            continue
        type_, result = checked

        pointers = list(
            db.scalars(
                select(ConceptTaxonomy).where(
                    ConceptTaxonomy.taxonomy_id == key_tax.id,
                    ConceptTaxonomy.identifier == name,
                    services.pointer_active_at(now),
                )
            )
        )
        concept_ids = {ct.concept_id for ct in pointers}
        if len(concept_ids) > 1:
            log.warning(
                "variable %r names %d concepts in %r; skipping it (the key taxonomy must be "
                "1:1 for the import to know which concept upstream means)",
                name, len(concept_ids), key_tax.key,
            )
            stats.skipped_ambiguous += 1
            stats.note(
                name, "ambiguous", f"names {len(concept_ids)} concepts in {key_tax.key!r}"
            )
            continue

        py = payload.snippets.get(name)
        if not concept_ids:
            concept = Concept(description=None)
            db.add(concept)
            db.flush()  # assign concept.id before linking / configuring
            concept_id = concept.id
            db.add(
                ConceptTaxonomy(
                    concept_id=concept_id,
                    taxonomy_id=key_tax.id,
                    identifier=name,
                    display_name=None,
                    origin=ORIGIN_IMPORT,
                    created_at=now,
                )
            )
            change_type, message = "initial", _import_message(type_)
            stats.imported += 1
        else:
            concept_id = next(iter(concept_ids))
            # The name the import resolves through is a name the import maintains, whoever
            # first wrote it down — see the adoption rule in `_sync_pointers`.
            for ct in pointers:
                if ct.origin != ORIGIN_IMPORT:
                    ct.origin = ORIGIN_IMPORT
                    stats.pointers_adopted += 1
            prior = services.latest_published_for_source(db, concept_id, payload.source.id)
            if prior is None:
                change_type, message = "initial", _import_message(type_)
                stats.imported += 1
            elif _matches_stored(prior, type_, definition, py) and _files_match(
                db, prior, payload.source.id, py
            ):
                stats.unchanged += 1
                _sync_pointers(db, concept_id, payload.pointers.get(name), taxonomies, now, stats)
                continue
            else:
                # A definition that moved upstream is a real new version of the concept, with
                # its own number and a message that says who wrote it.
                change_type, message = "sync", settings.sync_import_message
                stats.updated += 1

        _mint(
            db,
            payload,
            versions,
            concept_id=concept_id,
            type_=type_,
            definition=definition,
            py=py,
            change_type=change_type,
            message=message,
            result=result,
            author_id=author_id,
            now=now,
            stats=stats,
        )
        if py:
            stats.with_python += 1
        _sync_pointers(db, concept_id, payload.pointers.get(name), taxonomies, now, stats)

    stats.missing_upstream = _missing_upstream(db, payload, key_tax)


def _missing_upstream(db: Session, payload: _Payload, key_tax: Taxonomy) -> list[str]:
    """Names this source still stores that the current files no longer offer.

    Reported, never acted on: a variable disappearing upstream may be a rename, a temporary
    build failure, or a genuine retirement, and only the last one should take a concept out of
    circulation — which is a reviewed decision, not an import's to make.

    What counts as judgeable is the payload's `ReportScope`: a payload that does not claim to
    be complete for anything reports nothing, and one complete only for certain types is
    compared against those types alone.
    """
    if not payload.scope.report:
        return []
    filters = [
        ConceptTaxonomy.taxonomy_id == key_tax.id,
        ConceptTaxonomy.origin == ORIGIN_IMPORT,
        ConceptTaxonomy.deprecated_at.is_(None),
        Config.source_id == payload.source.id,
        Config.status == "published",
    ]
    if payload.scope.types is not None:
        filters.append(Config.type.in_(sorted(payload.scope.types)))
    elif settings.externally_managed_types:
        # Types somebody else maintains (see `externally_managed_types`): this payload never
        # carried them, which says nothing about whether they still exist.
        filters.append(Config.type.not_in(settings.externally_managed_types))
    stored = db.execute(
        select(ConceptTaxonomy.identifier)
        .join(Config, Config.concept_id == ConceptTaxonomy.concept_id)
        .where(*filters)
        .distinct()
    )
    return sorted({identifier for (identifier,) in stored} - set(payload.variables))


def _sync_pointers(
    db: Session,
    concept_id: int,
    wanted: dict[str, list[str]] | None,
    taxonomies: dict[str, Taxonomy],
    now: datetime,
    stats: ImportStats,
) -> None:
    """Make the concept's importer-owned names in each taxonomy match what upstream lists.

    Only rows the import owns are touched: it adds the identifiers upstream now lists, retires
    the ones it added that upstream dropped, and leaves every ``user`` pointer exactly as it
    is — somebody typed those in, and an upstream mapping file is not evidence they were wrong.

    **Adoption:** a live user pointer that is exactly what the import wants is taken over
    (``origin`` flipped) rather than duplicated, so a database that predates the distinction
    ends up owned by whoever maintains the name rather than growing a second copy of it.

    An identifier already pointing at *other* concepts is not a conflict — that is a group, and
    the whole reason the pointer table has no unique constraint.
    """
    if not wanted:
        return
    for tax_key, identifiers in wanted.items():
        tax = taxonomies.get(tax_key)
        if tax is None:
            log.warning(
                "taxonomy %r is not seeded; skipping the pointers upstream lists in it", tax_key
            )
            continue
        active = list(
            db.scalars(
                select(ConceptTaxonomy).where(
                    ConceptTaxonomy.concept_id == concept_id,
                    ConceptTaxonomy.taxonomy_id == tax.id,
                    services.pointer_active_at(now),
                )
            )
        )
        held = {ct.identifier: ct for ct in active}
        desired = set(identifiers)

        for identifier in sorted(desired):
            ct = held.get(identifier)
            if ct is None:
                db.add(
                    ConceptTaxonomy(
                        concept_id=concept_id,
                        taxonomy_id=tax.id,
                        identifier=identifier,
                        origin=ORIGIN_IMPORT,
                        created_at=now,
                    )
                )
                stats.pointers_added += 1
            elif ct.origin != ORIGIN_IMPORT:
                ct.origin = ORIGIN_IMPORT
                stats.pointers_adopted += 1

        for identifier, ct in held.items():
            if identifier not in desired and ct.origin == ORIGIN_IMPORT:
                ct.deprecated_at = now
                stats.pointers_deprecated += 1


def _apply_notion_docs(db: Session, tax: Taxonomy, path: Path) -> None:
    """Copy the sidecar's Notion export onto the concept rows, matched by taxonomy name.

    The file maps ``{name: {clinical, implementation, caveats, status, url}}``. Every listed
    field overwrites the concept's current value (in-app edits are meant to be superseded by
    the upstream documentation on the next reimport); concepts not in the file keep theirs. A
    name pointing at several concepts documents all of them — they are one idea by construction
    — and a concept two names already documented keeps the first one in name order, so the
    outcome does not depend on dict order. A missing file is the normal case for deployments
    without the Notion sync: a no-op.
    """
    if not path.exists():
        return
    try:
        docs = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read notion docs %s (%s); skipping", path, exc)
        return
    if not isinstance(docs, dict):
        log.warning("notion docs %s is not an object; skipping", path)
        return

    applied: dict[int, str] = {}
    for name in sorted(docs):
        doc = docs[name]
        if not isinstance(doc, dict):
            continue
        concept_ids = db.scalars(
            select(ConceptTaxonomy.concept_id).where(
                ConceptTaxonomy.taxonomy_id == tax.id,
                ConceptTaxonomy.identifier == name,
                ConceptTaxonomy.deprecated_at.is_(None),
            )
        )
        for concept_id in concept_ids:
            if concept_id in applied:
                log.warning(
                    "notion docs: %r and %r both document concept #%d; keeping %r",
                    applied[concept_id], name, concept_id, applied[concept_id],
                )
                continue
            concept = db.get(Concept, concept_id)
            if concept is None:
                continue
            concept.doc_clinical = doc.get("clinical")
            concept.doc_implementation = doc.get("implementation")
            concept.doc_caveats = doc.get("caveats")
            concept.doc_status = doc.get("status")
            concept.notion_url = doc.get("url")
            applied[concept_id] = name
    log.info("notion docs: applied documentation to %d concept(s) from %s", len(applied), path)
