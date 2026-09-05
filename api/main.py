import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_redoc_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import func, inspect, select, text

from . import audit, models, security, services, usage
from .config import settings
from .db import Base, SessionLocal, engine
from .importer import import_reference
from .routers import (
    admin,
    api_keys,
    audit_log,
    auth,
    concepts,
    deprecation,
    files,
    internal,
    pointers,
    projects,
    reference,
    source_files,
    usage as usage_routes,
    writes,
)
from .schema_registry import registry

# Uvicorn only configures its own loggers, so without a root handler every
# `concepts.*` INFO record — the import stats, migrations, seeding — is dropped.
# basicConfig is a no-op if a deployment already installed a root handler.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(levelname)s:     [%(name)s] %(message)s",
)

log = logging.getLogger("concepts.seed")

# A capability that used to exist and no longer does; `_drop_can_review` clears it out of
# databases written while it did. Spelled here rather than in `security`, which only knows
# about capabilities that are still real.
_RETIRED_REVIEW = "can_review"

# The study-context columns. They live on `projects` (see models.Project); a database booted
# on the feature branch that first put them on `concept` has them dropped there again.
_STUDY_CONTEXT_COLUMNS = (
    "pico_population",
    "pico_intervention",
    "pico_comparison",
    "pico_outcome",
    "study_team",
)

# The license a project lead must accept before the project is valid. Bump by inserting a
# higher-version row (deactivating this one) to force every project to re-approve.
_CORR_LICENSE_V1 = """\
CORR License v1

The Charité Outcomes Research Repository (CORR) comprises all concept definitions, data \
mappings, and data transformations built by the CORR team, as well as the front-end \
applications such as the CORR concept browser, the CORR cohort builder, and the CORR data \
exploration widgets.

By accessing or using CORR, we agree to be bound by the following terms:

We will only share access to CORR or any part thereof with those whose own access request \
has been approved by the administrators of CORR, and only after specific additional \
approval by e-mail from the administrators of CORR. We will not share our personal access \
credentials with anyone.

We will only access CORR for the specific project registered with and approved through the \
CORR project management tool, and will not use CORR for any purpose outside the scope of \
the project as approved. Projects must be scientific, time-bound, and non-commercial in \
nature.

We will comply with all applicable legal and institutional requirements in connection with \
our use of CORR, including data protection law and any ethics approvals or data use \
agreements applicable to our project.

In return for using CORR infrastructure, which was built largely by unpaid volunteer work, \
we will actively contribute to the development of CORR by means reasonably available to \
us, which may include 1) definition or creation of new clinical concepts or 2) technical \
refinements of CORR's underlying infrastructure by contributing to the CORR-Vars GitHub \
repository or related projects.

We will actively involve CORR team members and intensivists from all participating ZfI \
(Zentrum für Intensivmedizin) departments at Charité in our CORR-related projects, drawing \
on their domain, data, and technical expertise. We will present each project at least once \
at a CORR Team Meeting. We will invite the CORR team to contribute as co-authors in the \
resulting publications and will reference CORR appropriately therein.

We acknowledge that access to CORR is granted on a non-exclusive, non-transferable, and \
revocable basis, and that the administrators of CORR may suspend or revoke our access at \
any time, in particular in the event of non-compliance with these terms.

We acknowledge that CORR is provided "as is", without warranty of any kind, including as \
to accuracy, completeness, or fitness for a particular purpose, and that, to the extent \
permitted by applicable law, neither the CORR team nor Charité – Universitätsmedizin \
Berlin accepts any liability arising from our use of CORR or from results derived with it.

We acknowledge that our obligations with respect to CORR that by their nature extend \
beyond termination (in particular those concerning access restrictions, data protection, \
and attribution of CORR) shall continue after termination of this agreement for any reason.
"""


def _ensure_sqlite_dir() -> None:
    if settings.database_url.startswith("sqlite"):
        path = settings.database_url.split("sqlite:///")[-1]
        if path and path != ":memory:":
            directory = os.path.dirname(os.path.abspath(path))
            if directory:
                os.makedirs(directory, exist_ok=True)


def _add_column(table: str, column: str, ddl: str, *, index: str | None = None) -> None:
    """Add one column (and optionally its index) if the table doesn't already have it."""
    if column in {c["name"] for c in inspect(engine).get_columns(table)}:
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        if index:
            conn.execute(
                text(f"CREATE INDEX IF NOT EXISTS {index} ON {table} ({column})")
            )
    log.info("migrated: added %s.%s", table, column)


def _ensure_index(table: str, index: str, columns: str) -> None:
    """Create an index on columns that already exist. `_add_column` only indexes columns it
    itself adds, so a column that predates the query needing an index needs this instead."""
    if any(ix["name"] == index for ix in inspect(engine).get_indexes(table)):
        return
    with engine.begin() as conn:
        conn.execute(text(f"CREATE INDEX IF NOT EXISTS {index} ON {table} ({columns})"))
    log.info("migrated: added index %s", index)


def _migrate() -> None:
    """Idempotent column adds for pre-existing DBs — we have no Alembic and
    ``create_all()`` only creates missing *tables*, never missing *columns*. Safe to re-run on
    every boot: each add is skipped when the column is already there."""
    tables = set(inspect(engine).get_table_names())

    if "users" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("users")}
        if "ldap_guid" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN ldap_guid VARCHAR(128)"))
                # Matches the index create_all() makes for a fresh DB (unique=True, index=True).
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_ldap_guid "
                        "ON users (ldap_guid)"
                    )
                )
            log.info("migrated: added users.ldap_guid")
        if "ldap_profile" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN ldap_profile JSON"))
            log.info("migrated: added users.ldap_profile")

    # The audit log grew from "concept reads only" to a full event log (logins + every API call,
    # with the request kept for the detail view). Rows written before this backfill keep their
    # NULLs and default to the `api_call` event, which is what they were.
    if "audit_log" in tables:
        _add_column(
            "audit_log", "event", "VARCHAR(16) DEFAULT 'api_call'", index="ix_audit_log_event"
        )
        _add_column(
            "audit_log", "concept_id", "INTEGER", index="ix_audit_log_concept_id"
        )
        _add_column(
            "audit_log", "concept_name", "VARCHAR(128)", index="ix_audit_log_concept_name"
        )
        _add_column("audit_log", "taxonomy", "VARCHAR(64)")
        _add_column("audit_log", "concept_version", "INTEGER")
        _add_column("audit_log", "auth_method", "VARCHAR(16)")
        _add_column("audit_log", "query_string", "TEXT")
        _add_column("audit_log", "ip_address", "VARCHAR(64)")
        _add_column("audit_log", "user_agent", "VARCHAR(256)")
        _add_column("audit_log", "detail", "JSON")

        # …and then a third kind, `email`, which is not a request at all (see AuditLog).
        _add_column("audit_log", "email_kind", "VARCHAR(32)")
        _add_column("audit_log", "email_to", "VARCHAR(256)")
        _add_column("audit_log", "email_subject", "VARCHAR(256)")
        _add_column("audit_log", "email_status", "VARCHAR(16)")
        _relax_audit_request_columns()

    # Data files moved out of the concept versions and into their source's library
    # (`source_file` / `source_file_version` / `config_file_ref`). Those three are new
    # *tables*, which `create_all()` above already made; what needs doing by hand is carrying
    # the old per-config attachments across and dropping the table they lived in.
    if "config_file" in tables:
        _move_files_into_source_libraries()

    # A new version of a file may rename it (the identity is the uuid, not the path), so each
    # version records the name it was uploaded under. Rows written before this stay NULL and
    # are read as "the name the file has now" — backfilling them from the file's current path
    # would be an invention: nothing knows whether those versions carried it.
    if "source_file_version" in tables:
        _add_column("source_file_version", "path", "VARCHAR(512)")

    # Clinical documentation moved onto the concept row (in-app editable, refreshed from the
    # sidecar's Notion export on reimport).
    if "concept" in tables:
        _add_column("concept", "doc_clinical", "TEXT")
        _add_column("concept", "doc_implementation", "TEXT")
        _add_column("concept", "doc_caveats", "TEXT")
        _add_column("concept", "doc_status", "VARCHAR(64)")
        _add_column("concept", "notion_url", "VARCHAR(512)")
        # A retired concept and what replaces it (see the deprecation requests in
        # api/routers/deprecation.py). `deprecation_request` is a new *table*, so create_all()
        # makes it.
        _add_column("concept", "deprecated_at", "DATETIME")
        _add_column("concept", "deprecated_by", "INTEGER")
        _add_column("concept", "successor_id", "INTEGER", index="ix_concept_successor_id")
        _fold_merges_into_successors()
        # The concepts table filters and facets on the status; the column predates the query.
        _ensure_index("concept", "ix_concept_doc_status", "doc_status")
        # The study context briefly lived on the concept; it belongs to the project (see
        # below), so those columns are dropped again.
        _drop_study_context_from_concept()

    # The study context — the PICO frame the project studies and the study team behind it.
    # In-app only: nothing outside the project page writes it, so the columns start NULL
    # everywhere and stay whatever a lead last typed.
    if "projects" in tables:
        for column in _STUDY_CONTEXT_COLUMNS:
            _add_column("projects", column, "TEXT")

    if "concept_taxonomy" in tables:
        # Taxonomy entries are pointers with a membership window and an owner.
        _add_column("concept_taxonomy", "created_at", "DATETIME")
        _add_column("concept_taxonomy", "deprecated_at", "DATETIME")
        _add_column("concept_taxonomy", "deprecated_by", "INTEGER")
        _add_column("concept_taxonomy", "origin", "VARCHAR(16) DEFAULT 'user'")
        _backfill_pointer_columns()
        _drop_pointer_unique_constraint()

    # A deprecation request records which of the concept's names it was filed against, so
    # approving can retire that one name instead of the whole concept. Rows written before this
    # stay NULL and keep meaning "the concept" — which is what they were.
    if "deprecation_request" in tables:
        _add_column("deprecation_request", "pointer_id", "INTEGER")

    if "config" in tables:
        _ensure_published_version_unique()

    if "concept_merge" in tables:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS concept_merge"))
        log.info("migrated: dropped concept_merge")

    if "usage_rollup_state" in tables:
        _refold_usage_on_rule_change()

    if "users" in tables:
        _grant_read_detail_to_existing_readers()
        _drop_can_review()


def _refold_usage_on_rule_change() -> None:
    """Rebuild `concept_usage` when what counts as usage has changed since it was folded.

    The fold is incremental behind a watermark, so a new rule would otherwise apply only to
    rows logged after it and leave everything already counted under the old one — here, a
    rollup in which the web app's own reads still count as the user's API usage. The rollup is
    derived data, so the fix is simply to throw it away and refold the whole log; the stamp on
    the watermark row is what keeps that a one-time cost rather than a per-boot one.
    """
    _add_column("usage_rollup_state", "filter_version", "INTEGER DEFAULT 0")
    _add_column("concept_usage", "versions", "TEXT")
    with SessionLocal() as db:
        state = db.get(models.UsageRollupState, 1)
        # No rollup yet ⇒ nothing folded under the old rule; the first one is stamped current.
        if state is None or (state.filter_version or 0) >= models.USAGE_FILTER_VERSION:
            return
        pairs = usage.rebuild(db)
        state = db.get(models.UsageRollupState, 1)
        if state is not None:
            state.filter_version = models.USAGE_FILTER_VERSION
            db.commit()
    log.info("migrated: usage rollup refolded under the current rule (%d pair(s))", pairs)


def _drop_can_review() -> None:
    """Retire `can_review` from stored grants and API-key scopes.

    Reviewing is not a capability of its own any more: whoever reviews, publishes, so the
    queues are gated on `can_publish` and `can_review` is not in `ALL_CAPABILITIES`. A grant
    that no longer means anything must not sit in the database either — the admin UI has no
    checkbox to render it with, and a scope list is validated against the known capabilities.

    Nothing is granted in exchange: an account whose only queue access was `can_review` loses
    it, which is the decision. Idempotent by observable state (per README_DEV): once the
    string is gone there is nothing left to match, so every later boot is a no-op.
    """
    with SessionLocal() as db:
        touched_users = touched_keys = 0
        for u in db.scalars(select(models.User)):
            caps = list(u.capabilities or [])
            if _RETIRED_REVIEW in caps:
                # Reassign rather than mutate: a JSON column doesn't see in-place list edits.
                u.capabilities = [c for c in caps if c != _RETIRED_REVIEW]
                touched_users += 1
        for k in db.scalars(select(models.ApiKey)):
            scopes = list(k.scopes or [])
            if _RETIRED_REVIEW in scopes:
                k.scopes = [c for c in scopes if c != _RETIRED_REVIEW]
                touched_keys += 1
        if touched_users or touched_keys:
            db.commit()
            log.info(
                "migrated: dropped can_review from %d user(s) and %d API key(s)",
                touched_users,
                touched_keys,
            )


def _grant_read_detail_to_existing_readers() -> None:
    """Split `can_read` into read + read-detail without locking anybody out, once.

    `can_read_detail` (snippets and file bytes) did not exist before; everybody who could read
    could read those too. Introducing it silently would take working access away from every
    existing account and every API key already deployed against this instance — so the first
    boot that sees the capability grants it to whoever had `can_read` **and nothing above it**,
    and to every API key scoped the same way. Keys matter as much as users: an effective scope
    is `key.scopes ∩ owner.capabilities` (see `deps._authenticate_api_key`), so widening only
    the owner would still have cut corr-vars off at the key.

    Only the `can_read`-only grants need touching, because capabilities are a chain
    (`security.CAPABILITY_CHAIN`): an editor, reviewer or publisher already entails
    `can_read_detail` and never lost anything to fix. That is also why this does not fight
    entailment — it edits stored grants for the one case entailment cannot reach, a grant that
    genuinely sits *below* the new capability, and leaves evaluation alone.

    New accounts are deliberately *not* covered — that is the whole point of the feature. The
    LDAP auto-grant (`routers/auth.py`) hands out `can_read` alone, so a directory user who has
    never been reviewed browses concepts and their JSON and gets an explicit refusal on code.

    Idempotent by observable state, per README_DEV: it runs only while *no* row holds the
    capability, which is true exactly once — of a database written before it existed. A fresh
    database has no users at all at this point (`_seed()` runs after `_migrate()`) and the
    bootstrap admin it then creates holds `ALL_CAPABILITIES`, so the guard closes on boot two.
    """
    with SessionLocal() as db:
        users = list(db.scalars(select(models.User)))
        if any(security.CAN_READ_DETAIL in (u.capabilities or []) for u in users):
            return  # already carried across

        keys = list(db.scalars(select(models.ApiKey).where(models.ApiKey.revoked.is_(False))))
        touched_users = touched_keys = 0
        def _needs_detail(granted: list) -> bool:
            """Held `can_read`, and nothing that already entails reading code."""
            return (
                security.CAN_READ in granted
                and security.CAN_READ_DETAIL not in security.expand_capabilities(granted)
            )

        for u in users:
            caps = list(u.capabilities or [])
            if _needs_detail(caps):
                # Reassign rather than mutate: a JSON column doesn't see in-place list edits.
                u.capabilities = caps + [security.CAN_READ_DETAIL]
                touched_users += 1
        for k in keys:
            scopes = list(k.scopes or [])
            if _needs_detail(scopes):
                k.scopes = sorted(scopes + [security.CAN_READ_DETAIL])
                touched_keys += 1
        if touched_users or touched_keys:
            db.commit()
            log.info(
                "migrated: granted can_read_detail to %d existing user(s) and %d API key(s)",
                touched_users,
                touched_keys,
            )


def _ensure_published_version_unique() -> None:
    """Give a pre-existing `config` table the `(concept_id, version_no)` unique index, once.

    `version_no` is the number clients pin to (`/concept/{tax}/{name}?v=3`), so two published
    rows sharing one is not a cosmetic problem: it makes that URL ambiguous. The model has
    declared the index since the first release, but `create_all()` only builds indexes for
    tables it creates — a database from before it, or one whose `config` table predates the
    declaration, never got it. Nothing enforced the rule but the importer's own bookkeeping.

    It is a *partial* index (published rows with a number; drafts all carry NULL), which SQLite
    creates in place — no table rebuild, unlike the constraints
    `_drop_pointer_unique_constraint` and `_relax_audit_request_columns` deal with.

    A database that already violates the rule keeps it unenforced and says so: creating the
    index there would fail the boot, and picking which of the colliding rows to renumber is
    not a migration's call — the versions have been served under those numbers.
    """
    if "uq_config_published_version" in {
        i["name"] for i in inspect(engine).get_indexes("config")
    }:
        return

    with engine.connect() as conn:
        duplicates = conn.execute(
            text(
                "SELECT concept_id, version_no, COUNT(*) FROM config "
                "WHERE status = 'published' AND version_no IS NOT NULL "
                "GROUP BY concept_id, version_no HAVING COUNT(*) > 1"
            )
        ).all()
    if duplicates:
        log.warning(
            "config has %d (concept, version) pair(s) published more than once (%s); leaving "
            "uq_config_published_version uncreated — resolve them by hand, then reboot",
            len(duplicates),
            ", ".join(f"concept {c} v{v} x{n}" for c, v, n in duplicates[:5]),
        )
        return

    with engine.begin() as conn:
        # Spelled exactly as create_all() writes it for a fresh database, so the migrated shape
        # and the built-from-scratch shape are the same shape.
        conn.execute(
            text(
                "CREATE UNIQUE INDEX uq_config_published_version ON config "
                "(concept_id, version_no) "
                "WHERE status = 'published' AND version_no IS NOT NULL"
            )
        )
    log.info("migrated: config (concept_id, version_no) is unique among published rows")


def _move_files_into_source_libraries() -> None:
    """Carry the per-config file attachments over to the source-level library, then drop
    `config_file`.

    The old shape stored (config, relative path) -> blob: the same mapping table read by four
    variables was four rows, and replacing it meant replacing all four. The new shape stores
    the file once per source, versioned, and a config points at one of those *versions*.

    Reconstructing the version history is the only interesting part. Every attachment row for
    one ``(source, path)`` is one observation of that file's contents at the moment its config
    was written, so walking the rows in ``(config.created_at, config.id)`` order and minting a
    version each time the blob differs from the one before recovers exactly the sequence of
    distinct contents the file went through — and every original row then pins the version that
    was current when it was written. A file that never changed ends up with one version and N
    pins, which is the shape the new model would have produced had it always been there.

    **The collision report** is a cheap assertion, not a repair. If one ``(source, path)`` had
    two *different* blobs live in current published configs at the same time, the linear history
    above is a fiction — two definitions disagreed about what the file contained, and the
    reconstruction quietly picks one. That cannot happen for imported files (``_attach_files``
    cached ``blobs[rel] -> blob_id`` across a whole run, so one path had one blob per pass), and
    the app only ever let one draft at a time hold a path. It is logged loudly rather than
    raised: the data is already migrated at that point and a boot failure would help nobody.

    Guarded on `config_file` still existing and ending by dropping it, so re-running is a no-op.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT cf.id AS ref_id, cf.config_id, cf.path, cf.blob_id, "
                "       c.source_id, c.created_by "
                "FROM config_file cf JOIN config c ON c.id = cf.config_id "
                "ORDER BY c.created_at, c.id, cf.id"
            )
        ).mappings().all()

        # The current published config per (concept, source) — the only rows whose pins are
        # "live", and therefore the only ones a disagreement about contents would matter for.
        live = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT id FROM config c WHERE c.status = 'published' "
                    "AND c.version_no IS NOT NULL AND c.version_no = ("
                    "  SELECT MAX(c2.version_no) FROM config c2 "
                    "  WHERE c2.concept_id = c.concept_id AND c2.source_id = c.source_id "
                    "    AND c2.status = 'published'"
                    ")"
                )
            )
        }

        files: dict[tuple[int, str], dict] = {}
        pins: list[tuple[int, int, str]] = []  # (config_id, file_version_id, path)
        now = models._utcnow()

        for row in rows:
            key = (row["source_id"], row["path"])
            entry = files.get(key)
            if entry is None:
                file_id = conn.execute(
                    text(
                        "INSERT INTO source_file "
                        "(uuid, source_id, path, description, created_at, created_by) "
                        "VALUES (:uuid, :source_id, :path, NULL, :created_at, :created_by)"
                    ),
                    {
                        "uuid": str(uuid.uuid4()),
                        "source_id": row["source_id"],
                        "path": row["path"],
                        "created_at": now,
                        "created_by": row["created_by"],
                    },
                ).lastrowid
                entry = files[key] = {"file_id": file_id, "versions": {}, "last": None, "live": set()}

            if row["blob_id"] != entry["last"]:
                version_no = len(entry["versions"]) + 1
                version_id = conn.execute(
                    text(
                        "INSERT INTO source_file_version "
                        "(file_id, version_no, blob_id, message, created_by, created_at) "
                        "VALUES (:file_id, :version_no, :blob_id, :message, :created_by, :at)"
                    ),
                    {
                        "file_id": entry["file_id"],
                        "version_no": version_no,
                        "blob_id": row["blob_id"],
                        "message": "Carried over from the per-version attachments",
                        "created_by": row["created_by"],
                        "at": now,
                    },
                ).lastrowid
                entry["versions"][row["blob_id"]] = version_id
                entry["last"] = row["blob_id"]

            # A row whose blob matches the one before it pins that same version; a revert to
            # bytes the file held earlier is a *new* version carrying them again, which is
            # exactly what an upload of those bytes does today (`services.store_file_version`
            # compares against the current version, not the whole history).
            version_id = entry["versions"][row["blob_id"]]
            pins.append((row["config_id"], version_id, row["path"]))
            if row["config_id"] in live:
                entry["live"].add(row["blob_id"])

        for config_id, version_id, path in pins:
            conn.execute(
                text(
                    "INSERT INTO config_file_ref (config_id, file_version_id, path, origin) "
                    "VALUES (:config_id, :file_version_id, :path, :origin)"
                ),
                {
                    "config_id": config_id,
                    "file_version_id": version_id,
                    "path": path,
                    "origin": models.FILE_REF_LEGACY,
                },
            )

        conn.execute(text("DROP TABLE config_file"))

    for (source_id, path), entry in files.items():
        if len(entry["live"]) > 1:
            log.warning(
                "file migration: source #%d path %r had %d different contents live in "
                "published configs at once; its reconstructed version history is a guess — "
                "check source_file #%d",
                source_id, path, len(entry["live"]), entry["file_id"],
            )
    log.info(
        "migrated: %d attachment(s) became %d source file(s) with %d version(s); "
        "dropped config_file",
        len(pins),
        len(files),
        sum(len(e["versions"]) for e in files.values()),
    )


def _fold_merges_into_successors() -> None:
    """Carry `concept.merged_into_id` over to `successor_id`, then drop the old column.

    Both name the concept that took over from this one, so the values transfer unchanged. The
    copy is guarded on the column still existing, and only fills successors that are not
    already set, so re-running it is a no-op.
    """
    columns = {c["name"] for c in inspect(engine).get_columns("concept")}
    if "merged_into_id" not in columns:
        return
    with engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE concept SET successor_id = merged_into_id "
                "WHERE successor_id IS NULL AND merged_into_id IS NOT NULL"
            )
        )
        conn.execute(text("DROP INDEX IF EXISTS ix_concept_merged_into_id"))
    # `concept` is referenced by four other tables, so it cannot be rebuilt the way `audit_log`
    # is — SQLite rewrites their FK clauses to follow the rename. Dropping the one column in
    # place is the only shape-changing operation that leaves them alone; on a SQLite too old to
    # support it the column simply stays behind, unread.
    try:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE concept DROP COLUMN merged_into_id"))
    except Exception:  # noqa: BLE001 — a dead column is not worth failing a boot over
        log.warning("could not drop concept.merged_into_id; leaving it unused")
    log.info("migrated: concept.merged_into_id folded into successor_id")


def _drop_study_context_from_concept() -> None:
    """Remove the PICO/study-team columns from `concept` — they moved to `projects`.

    A PICO frame and a study team describe a *study*, i.e. a project, not a concept
    definition. The columns never reached a release: only a database booted on the feature
    branch carries them, and whatever was typed there is test data, so nothing is carried
    across. Idempotent by observable state — once the columns are gone there is nothing left
    to drop and every later boot is a no-op.
    """
    columns = {c["name"] for c in inspect(engine).get_columns("concept")}
    dead = [c for c in _STUDY_CONTEXT_COLUMNS if c in columns]
    if not dead:
        return
    # Same constraint as `merged_into_id` above: `concept` is referenced by other tables, so it
    # cannot be rebuilt — an in-place DROP COLUMN is the only shape change that leaves them
    # alone, and on a SQLite too old to support it the columns simply stay behind, unread.
    for column in dead:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE concept DROP COLUMN {column}"))
        except Exception:  # noqa: BLE001 — a dead column is not worth failing a boot over
            log.warning("could not drop concept.%s; leaving it unused", column)
        else:
            log.info("migrated: dropped concept.%s (study context moved to projects)", column)


def _backfill_pointer_columns() -> None:
    """Give pre-existing pointer rows the window and owner the model requires.

    `created_at` and `origin` are NOT NULL on the current shape, so they have to hold values
    before the rebuild below copies the rows across. A pointer that predates the distinction is
    dated from its concept and owned by `user`; the next upsert import adopts the ones it
    recognises (see `api/importer.py`).
    """
    with engine.begin() as conn:
        conn.execute(text("UPDATE concept_taxonomy SET origin = 'user' WHERE origin IS NULL"))
        conn.execute(
            text(
                "UPDATE concept_taxonomy SET created_at = "
                "(SELECT created_at FROM concept WHERE concept.id = concept_taxonomy.concept_id) "
                "WHERE created_at IS NULL"
            )
        )
        conn.execute(
            text(
                "UPDATE concept_taxonomy SET created_at = CURRENT_TIMESTAMP "
                "WHERE created_at IS NULL"
            )
        )


def _drop_pointer_unique_constraint() -> None:
    """Drop `uq_taxonomy_identifier` from `concept_taxonomy`, once.

    One identifier may name several concepts (a group), so the constraint has to go — and
    SQLite cannot drop one in place, so the table is rebuilt from the current model exactly as
    ``_relax_audit_request_columns`` rebuilds the audit log: create the new shape, copy every
    row across, swap. Nothing references `concept_taxonomy`, so the rename is safe. No-op once
    the constraint is gone, and on a fresh DB, where ``create_all()`` built the right shape.
    """
    with engine.connect() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='concept_taxonomy'")
        ).scalar()
    if not ddl or "uq_taxonomy_identifier" not in ddl:
        return

    table = models.ConceptTaxonomy.__table__
    columns = {c["name"] for c in inspect(engine).get_columns("concept_taxonomy")}
    carried = ", ".join(c.name for c in table.columns if c.name in columns)
    indexes = [
        row[0]
        for row in engine.connect().execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='concept_taxonomy' AND sql IS NOT NULL"
            )
        )
    ]

    with engine.begin() as conn:
        # The indexes follow the table through the rename and keep their names, which would
        # then collide with the ones the new table declares. Drop them; `table.create` rebuilds.
        for name in indexes:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        conn.execute(text("ALTER TABLE concept_taxonomy RENAME TO concept_taxonomy_legacy"))
        table.create(conn)
        conn.execute(
            text(
                f"INSERT INTO concept_taxonomy ({carried}) "
                f"SELECT {carried} FROM concept_taxonomy_legacy"
            )
        )
        kept = conn.execute(text("SELECT count(*) FROM concept_taxonomy")).scalar_one()
        conn.execute(text("DROP TABLE concept_taxonomy_legacy"))
    log.info("migrated: concept_taxonomy rebuilt without the unique constraint (%d rows)", kept)


def _relax_audit_request_columns() -> None:
    """Make `audit_log.method`/`path`/`client_type` nullable, once.

    They were NOT NULL while every row was an HTTP request. An `email` row has no method, path
    or client, so the constraint has to go — and SQLite cannot drop one in place, so the table
    is rebuilt from the current model: create the new shape, copy every row across, swap. DDL
    is transactional in SQLite, so this either lands whole or not at all; the log is never left
    half-migrated. No-op once the column is already nullable, and on a fresh DB, where
    ``create_all()`` built the right shape to begin with.
    """
    columns = {c["name"]: c for c in inspect(engine).get_columns("audit_log")}
    if columns["method"]["nullable"]:
        return

    table = models.AuditLog.__table__
    # Copy only what both shapes have: anything the old table lacks (the email columns, on a DB
    # that skipped straight past the _add_column pass) is NULL on a request row anyway.
    carried = ", ".join(c for c in columns if c in table.columns)
    indexes = [
        row[0]
        for row in engine.connect().execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='audit_log' "
                "AND sql IS NOT NULL"  # skip the implicit indexes SQLite owns
            )
        )
    ]

    with engine.begin() as conn:
        # The indexes follow the table through a rename and keep their names, which would then
        # collide with the ones the new table declares. Drop them; `table.create` rebuilds them.
        for name in indexes:
            conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
        conn.execute(text("ALTER TABLE audit_log RENAME TO audit_log_legacy"))
        table.create(conn)
        conn.execute(
            text(f"INSERT INTO audit_log ({carried}) SELECT {carried} FROM audit_log_legacy")
        )
        kept = conn.execute(text("SELECT count(*) FROM audit_log")).scalar_one()
        conn.execute(text("DROP TABLE audit_log_legacy"))
    log.info("migrated: audit_log request columns now nullable (rebuilt, %d rows kept)", kept)


def _load_seed() -> dict:
    """Reference data from the YAML seed file (empty dict if the file is missing)."""
    path = Path(settings.seed_file)
    if not path.is_file():
        log.warning("seed file %s not found; skipping reference-data seed", settings.seed_file)
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _seed() -> None:
    """Idempotent first-run seed: bootstrap admin (from env) + reference data (from YAML).

    Sources/taxonomies are inserted by key; concepts by (taxonomy, name) — only when
    absent — so the seed file is safe to re-run and to extend later.
    """
    data = _load_seed()
    with SessionLocal() as db:
        if not db.scalar(select(func.count()).select_from(models.User)):
            db.add(
                models.User(
                    username=settings.bootstrap_admin_username,
                    password_hash=security.hash_password(settings.bootstrap_admin_password),
                    display_name="Bootstrap Admin",
                    capabilities=list(security.ALL_CAPABILITIES),
                    is_active=True,
                )
            )

        # First CORR license version, so projects have something to accept. Bump by inserting
        # a new row with a higher `version` (and deactivating the old one) to force re-approval.
        if not db.scalar(select(func.count()).select_from(models.License)):
            db.add(models.License(version=1, body=_CORR_LICENSE_V1, active=True))

        existing_sources = set(db.scalars(select(models.Source.key)))
        for s in data.get("sources") or []:
            if s["key"] in existing_sources:
                continue
            db.add(
                models.Source(
                    key=s["key"],
                    nicename=s.get("nicename"),
                    # snapshot of the types discovered on disk at boot; the live truth is
                    # always the schema folder (see /sources).
                    supported_types=registry.supported_types(s["key"]),
                    config=s.get("config") or {},
                )
            )

        existing_taxonomies = set(db.scalars(select(models.Taxonomy.key)))
        for t in data.get("taxonomies") or []:
            if t["key"] in existing_taxonomies:
                continue
            db.add(models.Taxonomy(key=t["key"], name=t.get("name"), version=t.get("version")))
        db.flush()  # taxonomies need ids before concepts can link to them

        # Concepts are identity-only; each carries a name within a taxonomy
        # (default settings.default_taxonomy). Insert only when that (taxonomy, name)
        # pair is absent.
        tax_by_key = {t.key: t for t in db.scalars(select(models.Taxonomy))}
        for c in data.get("concepts") or []:
            tax_key = c.get("taxonomy") or settings.default_taxonomy
            tax = tax_by_key.get(tax_key)
            if tax is None:
                log.warning(
                    "seed concept '%s' references unknown taxonomy '%s'; skipping",
                    c["name"], tax_key,
                )
                continue
            if services.resolve_pointers(db, tax.key, c["name"]):
                continue
            concept = models.Concept(description=c.get("description"))
            db.add(concept)
            db.flush()  # assign concept.id before linking
            db.add(
                models.ConceptTaxonomy(
                    concept_id=concept.id,
                    taxonomy_id=tax.id,
                    identifier=c["name"],
                    display_name=c.get("display_name"),
                )
            )

        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_sqlite_dir()
    registry.load()  # index the JSON-Schema folder before seeding/serving
    # be patient if the DB isn't reachable yet (e.g. volume just mounted)
    for _ in range(30):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            break
        except Exception:
            time.sleep(2)
    Base.metadata.create_all(engine)
    _migrate()
    _seed()
    import_reference()  # first-run only: load reference/ variables + python snippets
    # Fold whatever the audit log gained while we were down into the usage rollup. Incremental
    # and idempotent (see api/usage.py), so this is a no-op on a boot that missed nothing — and
    # it is what backfills the rollup the first time, on a database full of existing log rows.
    usage.refresh_quietly()
    yield


app = FastAPI(
    title="Concepts API",
    version="0.1.0",
    lifespan=lifespan,
    root_path=settings.root_path,
    # No built-in Swagger/ReDoc/schema: the only docs are the curated, x-public-scoped
    # reference served at /public/docs (see below).
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One `audit_log` row per authenticated request (and per login attempt), written after the
# response status is known. Routes enrich their row via `audit.mark_*`; see api/audit.py.
app.middleware("http")(audit.audit_middleware)


@app.get("/health")
def health():
    return {"status": "ok"}


# --- Public API documentation ------------------------------------------------
# The full internal /docs (Swagger) covers every route. The public reference below
# is generated from the same code but scoped to routes marked `openapi_extra={"x-public":
# True}` — the read-only endpoints external clients use — so it never leaks admin/write
# internals. (A marker, not a tag, so these endpoints aren't double-listed under a "public"
# section in the internal docs; `concepts`/`reference` stay the only grouping tags.)

_PUBLIC_DESCRIPTION = """\
Read-only access to CORR clinical concept definitions.

All endpoints require an authenticated bearer token, and external clients must name an
existing `project` on each concept read (the query is attributed to it). Concepts are
namespaced by **taxonomy**; each concept carries per-**source** definitions and a published
**version** history.
"""

_public_schema_cache: dict | None = None


def public_openapi() -> dict:
    global _public_schema_cache
    if _public_schema_cache is None:
        routes = [
            r
            for r in app.routes
            if isinstance(r, APIRoute) and (r.openapi_extra or {}).get("x-public")
        ]
        _public_schema_cache = get_openapi(
            title="CORR Concepts API",
            version=app.version,
            description=_PUBLIC_DESCRIPTION,
            routes=routes,
        )
    return _public_schema_cache


@app.get("/public/openapi.json", include_in_schema=False)
def public_openapi_json(request: Request):
    schema = dict(public_openapi())
    # Mirror FastAPI's built-in /openapi.json: advertise the proxy prefix (root_path) as the
    # server so ReDoc's example URLs and "Try it" calls hit /api/... not the bare domain.
    if root_path := request.scope.get("root_path"):
        schema["servers"] = [{"url": root_path}]
    return JSONResponse(schema)


@app.get("/public/docs", include_in_schema=False)
def public_docs():
    return get_redoc_html(
        openapi_url="openapi.json", title="CORR Concepts API — Reference"
    )


app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(audit_log.router)
app.include_router(api_keys.router)
app.include_router(projects.router)
app.include_router(reference.router)
app.include_router(concepts.router)
app.include_router(writes.router)
app.include_router(pointers.router)  # taxonomy pointers (add a name, retire a name)
app.include_router(deprecation.router)  # retiring a duplicate concept: request -> review
app.include_router(files.router)  # downloading a concept version's data files, at its pins
app.include_router(source_files.router)  # a source's file library: list, upload a version, retire
app.include_router(usage_routes.router)  # per-user / per-concept usage, folded from the log
app.include_router(internal.router)  # temporary: vars-sync sidecar only (token-guarded)
