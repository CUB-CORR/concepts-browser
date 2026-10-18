"""The reference import never publishes over a version somebody published in the app.

The import runs on every boot. It used to compare upstream with the *latest* published version,
so a definition edited in the app read as an upstream change and was reverted to upstream on
the next restart. Covers: an edited variable survives a re-import, upstream moving under it is
reported rather than applied, an unedited variable still follows upstream, and the one-time
`config.origin` backfill classifies an existing history the same way.
Run: uv run python tests/authored_version_smoke.py
"""
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_dir = tempfile.mkdtemp()
vars_path = os.path.join(_dir, "vars.json")
shutil.copy("reference/vars.json", vars_path)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_dir, 'authored.db')}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["LDAP_ENABLED"] = "false"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "true"
os.environ["REFERENCE_VARS_FILE"] = vars_path

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from api.db import SessionLocal, engine  # noqa: E402
from api.importer import import_reference  # noqa: E402
from api.main import _backfill_config_origin, app  # noqa: E402
from api.models import (  # noqa: E402
    ORIGIN_IMPORT,
    ORIGIN_USER,
    ConceptTaxonomy,
    Config,
    Source,
)


def concept_id(name: str) -> int:
    with SessionLocal() as db:
        return db.scalar(select(ConceptTaxonomy.concept_id).where(ConceptTaxonomy.identifier == name))


def history(concept_id: int) -> list[tuple[int, str, str, str]]:
    """The cub_hdp versions; reprodICU defines the same concepts under its own source."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(Config)
            .join(Source, Source.id == Config.source_id)
            .where(
                Config.concept_id == concept_id,
                Config.status == "published",
                Source.key == "cub_hdp",
            )
            .order_by(Config.version_no)
        )
        return [(c.version_no, c.change_type, c.origin, c.json_def.get("filter")) for c in rows]


def move_upstream(name: str, **changes) -> None:
    with open(vars_path) as f:
        data = json.load(f)
    data["variables"][name].update(changes)
    with open(vars_path, "w") as f:
        json.dump(data, f)


with TestClient(app) as client:  # lifespan imports the reference dataset
    r = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    hr_id, map_id = concept_id("heart_rate"), concept_id("mean_arterial_pressure")
    assert [o for _, _, o, _ in history(hr_id)] == [ORIGIN_IMPORT], history(hr_id)

    # --- somebody edits heart_rate in the app ---------------------------------------------------
    edited = {
        "type": "native_dynamic",
        "table_name": "vitals",
        "where_clause": "signal_name = 'heart_rate'",
        "filter": "value >= 20 AND value <= 250",
    }
    r = client.post("/concept/corr_v1/heart_rate/drafts", headers=h, json={
        "source": "cub_hdp", "json": edited, "message": "tighter range"})
    assert r.status_code == 201, r.text
    r = client.post(
        f"/concept/corr_v1/heart_rate/drafts/{r.json()['id']}/publish", headers=h, json={}
    )
    assert r.status_code == 200, r.text
    assert history(hr_id)[-1][2:] == (ORIGIN_USER, edited["filter"]), history(hr_id)

    # --- a restart re-imports an unchanged upstream: the edit stands -----------------------------
    stats = import_reference()
    assert stats.kept_authored == 1 and stats.updated == 0 and not stats.conflicts, stats
    assert len(history(hr_id)) == 2 and history(hr_id)[-1][3] == edited["filter"], history(hr_id)

    # --- upstream moves under the edit: reported, not applied ------------------------------------
    move_upstream("heart_rate", filter="value >= 0 AND value <= 350")
    stats = import_reference()
    assert stats.conflicts == ["heart_rate"] and stats.updated == 0, stats
    assert len(history(hr_id)) == 2 and history(hr_id)[-1][3] == edited["filter"], history(hr_id)

    # --- an unedited variable still follows upstream ---------------------------------------------
    move_upstream("mean_arterial_pressure", filter="value > 0")
    stats = import_reference()
    assert stats.updated == 1 and stats.conflicts == ["heart_rate"], stats
    assert history(map_id)[-1] == (2, "sync", ORIGIN_IMPORT, "value > 0"), history(map_id)

    # --- the backfill reads the same answer off a history that predates the column --------------
    # A file cascade (a `sync` repeating its predecessor) after the edit, then the overwrite the
    # old import made: a `sync` that differs from the person's version.
    with SessionLocal() as db:
        human = db.scalar(
            select(Config).where(Config.concept_id == hr_id, Config.origin == ORIGIN_USER)
        )
        top = db.scalar(select(func.max(Config.version_no)).where(Config.concept_id == hr_id))
        for no, definition in ((top + 1, human.json_def), (top + 2, {**human.json_def, "filter": "x"})):
            db.add(Config(
                concept_id=hr_id, source_id=human.source_id, type=human.type,
                json_def=definition, python_code=human.python_code, version_no=no,
                change_type="sync", status="published",
            ))
        db.commit()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE config DROP COLUMN origin"))
    engine.dispose()  # pooled connections still hold the old table shape
    _backfill_config_origin()
    assert [o for _, _, o, _ in history(hr_id)] == [
        ORIGIN_IMPORT, ORIGIN_USER, ORIGIN_USER, ORIGIN_IMPORT
    ], history(hr_id)
    _backfill_config_origin()  # idempotent: the column is there, nothing is reclassified

print("authored_version_smoke OK")
