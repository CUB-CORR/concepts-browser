"""Booting onto a database written by the previous schema. Run: uv run python tests/migration_smoke.py

There is no Alembic here (see CONTRIBUTING.md), so every shape change is a hand-rolled step in
``_migrate()`` that has to be safe to re-run and safe on a database that already holds data.
Two of them cannot be an ``ALTER TABLE ADD COLUMN``:

* `concept_taxonomy` had a unique `(taxonomy_id, identifier)`, which SQLite can only drop by
  rebuilding the table — and the rows, the foreign keys and the index names all have to survive
  that;
* `concept.merged_into_id` becomes `successor_id`, carrying its values across;
* `config` gains the partial unique index on `(concept_id, version_no)` that only ever
  existed for databases `create_all()` built the table for;
* `config_file` — a file attached to one config under a relative path — becomes the source-level
  library (`source_file` / `source_file_version` / `config_file_ref`), which means
  reconstructing a version history for each file out of the attachment rows and then dropping
  the table;
* `source_file_version` gains the `path` a version was uploaded under, so that a file renamed by
  a new version does not retroactively relabel its older ones.

This builds a database in the old shape by hand, boots the app onto it, and checks that the
data came through and that the constraint is really gone. Then it does it again, to prove the
migration is idempotent, and boots a fresh database to prove `create_all()` produces the same
shape from scratch.
"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_dir = tempfile.mkdtemp()
db_path = os.path.join(_dir, "legacy.db")

# --- a database in the previous shape ---------------------------------------------------------
# Only the tables the migration touches; `create_all()` adds the rest on boot.
legacy = sqlite3.connect(db_path)
legacy.executescript(
    """
    CREATE TABLE concept (
        id INTEGER NOT NULL PRIMARY KEY,
        description TEXT,
        doc_clinical TEXT,
        doc_implementation TEXT,
        doc_caveats TEXT,
        doc_status VARCHAR(64),
        notion_url VARCHAR(512),
        merged_into_id INTEGER,
        -- The study context, as the feature branch briefly put it on the concept. It belongs
        -- to the project, so the migration drops these five again.
        pico_population TEXT,
        pico_intervention TEXT,
        pico_comparison TEXT,
        pico_outcome TEXT,
        study_team TEXT,
        created_at DATETIME NOT NULL
    );
    CREATE INDEX ix_concept_merged_into_id ON concept (merged_into_id);

    CREATE TABLE taxonomy (
        id INTEGER NOT NULL PRIMARY KEY,
        "key" VARCHAR(64),
        name VARCHAR(128),
        version VARCHAR(64)
    );
    CREATE UNIQUE INDEX ix_taxonomy_key ON taxonomy ("key");

    CREATE TABLE concept_taxonomy (
        id INTEGER NOT NULL PRIMARY KEY,
        concept_id INTEGER NOT NULL,
        taxonomy_id INTEGER NOT NULL,
        identifier VARCHAR(128) NOT NULL,
        display_name VARCHAR(256),
        relationship VARCHAR(32),
        CONSTRAINT uq_taxonomy_identifier UNIQUE (taxonomy_id, identifier),
        FOREIGN KEY(concept_id) REFERENCES concept (id),
        FOREIGN KEY(taxonomy_id) REFERENCES taxonomy (id)
    );
    CREATE INDEX ix_concept_taxonomy_concept_id ON concept_taxonomy (concept_id);
    CREATE INDEX ix_concept_taxonomy_taxonomy_id ON concept_taxonomy (taxonomy_id);
    CREATE INDEX ix_concept_taxonomy_identifier ON concept_taxonomy (identifier);

    CREATE TABLE config (
        id INTEGER NOT NULL PRIMARY KEY,
        concept_id INTEGER NOT NULL,
        source_id INTEGER NOT NULL,
        type VARCHAR(32) NOT NULL,
        "json" JSON NOT NULL,
        py TEXT,
        version_no INTEGER,
        change_type VARCHAR(16) NOT NULL,
        message TEXT,
        status VARCHAR(16) NOT NULL,
        created_by INTEGER,
        created_at DATETIME NOT NULL,
        approved_by INTEGER,
        approved_at DATETIME,
        corrects_since_version_no INTEGER,
        validation_status VARCHAR(16),
        validation_report JSON,
        FOREIGN KEY(concept_id) REFERENCES concept (id),
        FOREIGN KEY(source_id) REFERENCES source (id)  -- create_all() makes `source` on boot
    );
    CREATE INDEX ix_config_concept_id ON config (concept_id);
    CREATE INDEX ix_config_source_id ON config (source_id);
    CREATE INDEX ix_config_status ON config (status);

    -- The attachment migration inserts through SQLAlchemy, which enforces foreign keys, so
    -- the source those configs claim has to actually exist — as it does in any real database.
    CREATE TABLE source (
        id INTEGER NOT NULL PRIMARY KEY,
        "key" VARCHAR(64),
        nicename VARCHAR(128),
        supported_types JSON,
        config JSON,
        created_at DATETIME NOT NULL
    );
    CREATE UNIQUE INDEX ix_source_key ON source ("key");

    CREATE TABLE blob (
        id INTEGER NOT NULL PRIMARY KEY,
        sha256 VARCHAR(64) NOT NULL,
        size INTEGER NOT NULL,
        media_type VARCHAR(128) NOT NULL,
        created_at DATETIME NOT NULL
    );
    CREATE UNIQUE INDEX ix_blob_sha256 ON blob (sha256);

    CREATE TABLE config_file (
        id INTEGER NOT NULL PRIMARY KEY,
        config_id INTEGER NOT NULL,
        path VARCHAR(512) NOT NULL,
        blob_id INTEGER NOT NULL,
        created_at DATETIME NOT NULL,
        CONSTRAINT uq_config_file_path UNIQUE (config_id, path),
        FOREIGN KEY(config_id) REFERENCES config (id),
        FOREIGN KEY(blob_id) REFERENCES blob (id)
    );

    CREATE TABLE concept_merge (
        id INTEGER NOT NULL PRIMARY KEY,
        duplicate_concept_id INTEGER,
        keep_concept_id INTEGER
    );

    INSERT INTO taxonomy (id, "key", name) VALUES (1, 'corr_v1', 'CORR (v1)');
    INSERT INTO source (id, "key", nicename, supported_types, config, created_at)
        VALUES (1, 'cub_hdp', 'CUB HDP', '[]', '{}', '2026-01-01 00:00:00');
    INSERT INTO concept (id, description, merged_into_id, created_at)
        VALUES (1, 'kept', NULL, '2026-01-02 03:04:05'),
               (2, 'folded away', 1, '2026-01-03 03:04:05');
    INSERT INTO concept_taxonomy (id, concept_id, taxonomy_id, identifier, display_name, relationship)
        VALUES (1, 1, 1, 'aki', 'Acute Kidney Injury', NULL),
               (2, 1, 1, 'akin', NULL, 'alias');
    INSERT INTO concept_merge (id, duplicate_concept_id, keep_concept_id) VALUES (1, 2, 1);
    INSERT INTO config (id, concept_id, source_id, type, "json", version_no, change_type,
                        status, created_at)
        VALUES (1, 1, 1, 'native_dynamic', '{"table_name": "x"}', 1, 'initial', 'published',
                '2026-01-02 03:04:05'),
               -- a draft: no number, and two of them may coexist
               (2, 1, 1, 'native_dynamic', '{"table_name": "x"}', NULL, 'improvement', 'draft',
                '2026-01-04 03:04:05'),
               (3, 1, 1, 'native_dynamic', '{"table_name": "y"}', NULL, 'improvement', 'draft',
                '2026-01-05 03:04:05'),
               -- three published versions of one (concept, source), each with the mapping table
               -- as it stood then: A, then B, then A again (a revert).
               (4, 1, 1, 'native_dynamic', '{"table_name": "x"}', 2, 'sync', 'published',
                '2026-01-06 03:04:05'),
               (5, 1, 1, 'native_dynamic', '{"table_name": "x"}', 3, 'sync', 'published',
                '2026-01-07 03:04:05');
    INSERT INTO blob (id, sha256, size, media_type, created_at)
        VALUES (1, 'aaa', 3, 'text/csv', '2026-01-02 03:04:05'),
               (2, 'bbb', 3, 'text/csv', '2026-01-06 03:04:05');
    INSERT INTO config_file (id, config_id, path, blob_id, created_at)
        VALUES (1, 1, 'pc/map.csv', 1, '2026-01-02 03:04:05'),
               (2, 4, 'pc/map.csv', 2, '2026-01-06 03:04:05'),
               (3, 5, 'pc/map.csv', 1, '2026-01-07 03:04:05'),
               -- a second file, never replaced: one version, one pin
               (4, 5, 'lab/units.csv', 2, '2026-01-07 03:04:05');
    """
)
legacy.commit()
legacy.close()

os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["FILE_DIR"] = tempfile.mkdtemp()

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, inspect, select, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from api import services  # noqa: E402
from api.db import SessionLocal, engine  # noqa: E402
from api.main import _migrate, app  # noqa: E402
from api.models import (  # noqa: E402
    Concept,
    ConceptTaxonomy,
    Config,
    ConfigFileRef,
    Project,
    SourceFile,
    SourceFileVersion,
)


# The study-context columns, in one place: they are dropped from `concept` and added to
# `projects` by the same migration pass.
STUDY_CONTEXT = {
    "pico_population", "pico_intervention", "pico_comparison", "pico_outcome", "study_team",
}


def table_sql(name: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
        ).scalar() or ""


def check_migrated() -> None:
    # The usage rollup is two *new* tables, so `create_all()` is the whole migration for it —
    # including its per-concept index, which only exists because the table is new. Booting an
    # old database has to produce them, and the fold's own idempotence (a watermark over
    # audit_log.id) is what tests/usage_smoke.py checks across a second boot.
    tables = set(inspect(engine).get_table_names())
    assert {"concept_usage", "usage_rollup_state"} <= tables, tables
    assert "ix_concept_usage_concept_id" in {
        i["name"] for i in inspect(engine).get_indexes("concept_usage")
    }

    columns = {c["name"] for c in inspect(engine).get_columns("concept_taxonomy")}
    assert {"created_at", "deprecated_at", "deprecated_by", "origin"} <= columns, columns
    assert "uq_taxonomy_identifier" not in table_sql("concept_taxonomy"), table_sql("concept_taxonomy")
    assert "concept_merge" not in inspect(engine).get_table_names()
    concept_columns = {c["name"] for c in inspect(engine).get_columns("concept")}
    assert "successor_id" in concept_columns and "merged_into_id" not in concept_columns
    # The study context moved to the project. A database booted on the feature branch that put
    # it on the concept has those columns dropped again — nothing is carried across, they never
    # reached a release — and `projects` has them instead.
    assert not (STUDY_CONTEXT & concept_columns), concept_columns
    assert STUDY_CONTEXT <= {c["name"] for c in inspect(engine).get_columns("projects")}

    with SessionLocal() as db:
        # Both pointers came across, dated from their concept and owned by the user, so the
        # next upsert can decide which of them it maintains.
        rows = list(db.scalars(select(ConceptTaxonomy).order_by(ConceptTaxonomy.id)))
        assert [r.identifier for r in rows] == ["aki", "akin"], rows
        assert all(r.origin == "user" and r.deprecated_at is None for r in rows), rows
        assert all(r.created_at.year == 2026 for r in rows), [r.created_at for r in rows]
        assert rows[1].relationship == "alias", rows[1]
        # The merge tombstone reads as a successor now.
        assert db.get(Concept, 2).successor_id == 1
        assert db.get(Concept, 1).successor_id is None
        assert services.final_successor(db, db.get(Concept, 2)) == 1
        # …and the constraint is really gone: one identifier may name two concepts.
        db.add(ConceptTaxonomy(concept_id=2, taxonomy_id=1, identifier="aki"))
        db.commit()
        assert len(services.resolve_pointers(db, "corr_v1", "aki")) == 2
        db.execute(
            ConceptTaxonomy.__table__.delete().where(ConceptTaxonomy.concept_id == 2)
        )
        db.commit()

    # --- the attachments became a source-level file library -----------------------------------
    assert "config_file" not in inspect(engine).get_table_names()
    with SessionLocal() as db:
        files = {f.path: f for f in db.scalars(select(SourceFile).order_by(SourceFile.path))}
        assert sorted(files) == ["lab/units.csv", "pc/map.csv"], sorted(files)
        assert all(f.source_id == 1 and f.deleted_at is None for f in files.values()), files
        assert all(len(f.uuid) == 36 for f in files.values()), files

        def versions(path: str) -> list[tuple[int, int]]:
            return [
                (v.version_no, v.blob_id)
                for v in db.scalars(
                    select(SourceFileVersion)
                    .where(SourceFileVersion.file_id == files[path].id)
                    .order_by(SourceFileVersion.version_no)
                )
            ]

        # Walking the attachments in (config.created_at, config.id) order recovers the sequence
        # the contents went through: A (v1), B (v2), A again (v3). The revert is a third
        # version rather than a re-pin of the first, which is what an upload of those bytes
        # does today — only bytes identical to the *current* version are a no-op.
        assert versions("pc/map.csv") == [(1, 1), (2, 2), (3, 1)], versions("pc/map.csv")
        assert versions("lab/units.csv") == [(1, 2)], versions("lab/units.csv")

        # Every original row became a pin, at the version current when it was written.
        pins = {
            (r.config_id, r.path): r
            for r in db.scalars(select(ConfigFileRef).order_by(ConfigFileRef.id))
        }
        assert sorted(pins) == [
            (1, "pc/map.csv"), (4, "pc/map.csv"), (5, "lab/units.csv"), (5, "pc/map.csv"),
        ], sorted(pins)
        assert all(r.origin == "legacy" for r in pins.values()), pins
        by_id = {v.id: v for v in db.scalars(select(SourceFileVersion))}
        # v1 of the concept kept the bytes it was published with; v2 moved to B; v3 reverted.
        assert by_id[pins[(1, "pc/map.csv")].file_version_id].version_no == 1
        assert by_id[pins[(4, "pc/map.csv")].file_version_id].version_no == 2
        assert by_id[pins[(5, "pc/map.csv")].file_version_id].version_no == 3

    # …and the version numbering is now enforced by the database, not just by the importer:
    # one published (concept, version) pair, however many drafts alongside it.
    assert "uq_config_published_version" in {
        i["name"] for i in inspect(engine).get_indexes("config")
    }
    with SessionLocal() as db:
        published = {"type": "native_dynamic", "json_def": {}, "status": "published"}
        db.add(Config(concept_id=1, source_id=1, version_no=1, **published))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("a second published v1 was accepted")
        # A draft is not a version, so it is not covered by the index.
        db.add(Config(concept_id=1, source_id=1, version_no=None, type="native_dynamic",
                      json_def={}, status="draft"))
        db.commit()


with TestClient(app):  # the lifespan runs create_all() + _migrate()
    check_migrated()
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Concept)) == 2

    # Re-running the migration on an already-migrated database changes nothing.
    _migrate()
    check_migrated()

    # ...and specifically, a second `_add_column` pass neither drops nor blanks what a lead has
    # since typed into a project's study context. (The drop half is idempotent by observable
    # state: with the columns gone from `concept` there is nothing left to drop.)
    with SessionLocal() as db:
        db.add(Project(name="study-x", pico_population="Adults on the ICU",
                       study_team="A. Beispiel"))
        db.commit()
    _migrate()
    check_migrated()
    with SessionLocal() as db:
        p = db.scalar(select(Project))
        assert p.pico_population == "Adults on the ICU" and p.study_team == "A. Beispiel", p

# --- a database from before a version recorded its filename ---------------------------------------
# `source_file_version.path` is a plain `_add_column` step, and the database that needs it is one
# whose table predates the column — which the legacy fixture above cannot be, because the
# migration that builds that table writes the current shape. So drop the column and re-migrate.
# It comes back, and the rows that never carried a name keep NULL: backfilling them from the
# file's current path would invent a history nothing recorded.
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE source_file_version DROP COLUMN path"))
# Pooled connections carry SQLite's idea of the schema with them, and this process has been
# talking to this database all along — a real boot gets fresh ones, so drop them here too.
engine.dispose()
assert "path" not in {c["name"] for c in inspect(engine).get_columns("source_file_version")}

_migrate()
assert "path" in {c["name"] for c in inspect(engine).get_columns("source_file_version")}
with engine.connect() as conn:
    assert conn.execute(
        text("SELECT count(*) FROM source_file_version WHERE path IS NULL")
    ).scalar_one() == 4
_migrate()  # ...and re-running it is a no-op, like every other step
check_migrated()

# --- and the same shape from scratch ------------------------------------------------------------
legacy_sql = table_sql("concept_taxonomy")

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_dir, 'fresh.db')}"
for module in [m for m in list(sys.modules) if m.startswith("api")]:
    del sys.modules[module]

from api.db import engine as fresh_engine  # noqa: E402
from api.main import app as fresh_app  # noqa: E402

with TestClient(fresh_app):
    with fresh_engine.connect() as conn:
        fresh_sql = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='concept_taxonomy'")
        ).scalar()
        indexes = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='concept_taxonomy' AND sql IS NOT NULL"
                )
            )
        }
    assert "uq_taxonomy_identifier" not in fresh_sql, fresh_sql
    assert "ix_concept_taxonomy_tax_ident" in indexes, indexes
    # The rebuilt table and the one create_all() writes are the same table.
    assert " ".join(fresh_sql.split()) == " ".join(legacy_sql.split()), (fresh_sql, legacy_sql)

# --- a database that already breaks the rule boots anyway ----------------------------------------
# Two published rows sharing a version number cannot be told apart by `?v=`, but which of them
# to renumber is a decision, not a migration step — so the index stays uncreated and the boot
# succeeds with a warning naming the pairs.
dupe_path = os.path.join(_dir, "duplicates.db")
dupe = sqlite3.connect(dupe_path)
dupe.executescript(
    """
    CREATE TABLE concept (
        id INTEGER NOT NULL PRIMARY KEY,
        description TEXT,
        created_at DATETIME NOT NULL
    );
    CREATE TABLE config (
        id INTEGER NOT NULL PRIMARY KEY,
        concept_id INTEGER NOT NULL,
        source_id INTEGER NOT NULL,
        type VARCHAR(32) NOT NULL,
        "json" JSON NOT NULL,
        py TEXT,
        version_no INTEGER,
        change_type VARCHAR(16) NOT NULL,
        message TEXT,
        status VARCHAR(16) NOT NULL,
        created_by INTEGER,
        created_at DATETIME NOT NULL,
        approved_by INTEGER,
        approved_at DATETIME,
        corrects_since_version_no INTEGER,
        validation_status VARCHAR(16),
        validation_report JSON
    );
    INSERT INTO concept (id, description, created_at) VALUES (1, 'kept', '2026-01-02 03:04:05');
    INSERT INTO config (id, concept_id, source_id, type, "json", version_no, change_type,
                        status, created_at)
        VALUES (1, 1, 1, 'native_dynamic', '{}', 1, 'initial', 'published', '2026-01-02 03:04:05'),
               (2, 1, 1, 'native_dynamic', '{}', 1, 'sync', 'published', '2026-01-03 03:04:05');
    """
)
dupe.commit()
dupe.close()

os.environ["DATABASE_URL"] = f"sqlite:///{dupe_path}"
for module in [m for m in list(sys.modules) if m.startswith("api")]:
    del sys.modules[module]

from api.db import engine as dupe_engine  # noqa: E402
from api.main import app as dupe_app  # noqa: E402

with TestClient(dupe_app):
    with dupe_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM config")).scalar_one() == 2
    assert "uq_config_published_version" not in {
        i["name"] for i in inspect(dupe_engine).get_indexes("config")
    }

print("MIGRATION SMOKE OK")
