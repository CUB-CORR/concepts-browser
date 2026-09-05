"""Variables posted as rows instead of files. Run: uv run python tests/bulk_upsert_smoke.py

``POST /internal/variables/upsert`` is the second way into the same upsert: a generator that
derives variables from a mapping table posts them, and they are created, versioned or left
alone by exactly the rules the file import follows (see tests/upsert_smoke.py for those). What
is specific to this path, and checked here:

* the payload never speaks for what it doesn't carry — `partial` (the default) computes no
  missing-upstream report at all, `complete` computes one for the types it names, and **neither
  deprecates anything**;
* a row the schema turns away is skipped and *itemised* — the file path leaves that in a
  container log, which a sidecar posting rows cannot read;
* the batch is refused whole for anything that would make its own report unreadable: a
  duplicate name, a type it did not claim, an invalid row under `on_invalid=reject`;
* `dry_run` runs the lot and writes nothing.

Drives the endpoint through TestClient, against a temp reference dir holding the *file* side of
the same source — because the two have to coexist: the file import must not report the posted
variables as missing.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ref = tempfile.mkdtemp()
VARS = os.path.join(_ref, "vars.json")

db_path = os.path.join(tempfile.mkdtemp(), "bulk.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["REFERENCE_VARS_FILE"] = VARS
os.environ["REFERENCE_PYTHON_FILE"] = os.path.join(_ref, "variables.py")
os.environ["REFERENCE_DATASETS"] = "[]"          # the primary dataset alone
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["FILE_DIR"] = tempfile.mkdtemp()
os.environ["INTERNAL_TOKEN"] = "sidecar-token"
# What the sidecar generates rather than the files: excluded from the file import's report.
os.environ["EXTERNALLY_MANAGED_TYPES"] = '["medication"]'

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from api import importer  # noqa: E402
from api.config import settings  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Concept, Config  # noqa: E402

HEADERS = {"x-internal-token": "sidecar-token"}


def med(drug: str) -> dict:
    return {"type": "medication", "drug": drug}


def row(name: str, drug: str, **extra) -> dict:
    return {"name": name, "definition": med(drug), **extra}


def post(**body) -> tuple[int, dict]:
    r = client.post("/internal/variables/upsert", headers=HEADERS, json=body)
    return r.status_code, r.json()


with open(VARS, "w") as f:
    json.dump(
        {"variables": {"heart_rate": {"type": "native_dynamic", "table_name": "obs"}}}, f
    )

ROWS = [
    row("med_ipratropium", "ipratropium", pointers={"ATC": ["R03BB01"]}),
    row("med_fenoterol", "fenoterol"),
    row("med_salbutamol", "salbutamol"),
]

with TestClient(app) as client:
    tok = client.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    _raw_get = client.get
    def get(url: str, **kw):
        return _raw_get(
            f"{url}{'&' if '?' in url else '?'}project=internal",
            headers={"authorization": f"Bearer {tok['access_token']}"},
            **kw,
        )

    def one(url: str) -> dict:
        body = get(url).json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    def config_count() -> int:
        with SessionLocal() as db:
            return db.scalar(select(func.count()).select_from(Config))

    # --- the guard is the same one the reimport route uses ------------------------------------
    assert client.post("/internal/variables/upsert", json={"rows": ROWS}).status_code == 403
    assert client.post(
        "/internal/variables/upsert", headers={"x-internal-token": "wrong"}, json={"rows": ROWS}
    ).status_code == 403

    # --- first batch: everything is new -------------------------------------------------------
    code, body = post(rows=ROWS)
    assert code == 200, body
    assert (body["imported"], body["updated"], body["unchanged"]) == (3, 0, 0), body
    assert body["mode"] == "partial" and body["errors"] == [], body
    assert body["pointers_added"] == 1, body
    # partial says nothing about what it doesn't carry, so there is nothing to report.
    assert body["missing_upstream"] == [], body
    listed = {x["name"] for x in get("/concepts").json()}
    assert {"med_ipratropium", "med_fenoterol", "med_salbutamol"} <= listed, listed
    assert one("/concept/corr_v1/med_ipratropium")["version"] == 1
    # …and the pointers a row carries are maintained the same way the file import maintains its.
    assert one("/concept/ATC/R03BB01")["id"] == one("/concept/corr_v1/med_ipratropium")["id"]

    # --- posting the same batch again writes nothing ------------------------------------------
    before = config_count()
    code, body = post(rows=ROWS)
    assert code == 200, body
    assert (body["imported"], body["updated"], body["unchanged"]) == (0, 0, 3), body
    assert config_count() == before, "an identical repost minted a version"

    # --- one changed row mints exactly one new version ----------------------------------------
    changed = [row("med_ipratropium", "ipratropium bromide", pointers={"ATC": ["R03BB01"]})] \
        + ROWS[1:]
    code, body = post(rows=changed)
    assert code == 200, body
    assert (body["imported"], body["updated"], body["unchanged"]) == (0, 1, 2), body
    assert config_count() == before + 1, config_count()
    ipra = one("/concept/corr_v1/med_ipratropium")
    assert ipra["version"] == 2, ipra
    info = ipra["sources"]["cub_hdp"]["version_info"]
    assert info["change_type"] == "sync" and info["source_version"] == 2, info
    assert ipra["sources"]["cub_hdp"]["json"]["drug"] == "ipratropium bromide", ipra
    # …and the first version is still served.
    assert one("/concept/corr_v1/med_ipratropium?v=1")["sources"]["cub_hdp"]["json"]["drug"] \
        == "ipratropium"

    # --- complete mode: the same rows, minus one, and it says so -------------------------------
    code, body = post(
        rows=changed[:2], mode="complete", complete_for_types=["medication"]
    )
    assert code == 200, body
    assert body["missing_upstream"] == ["med_salbutamol"], body
    # Reported, not acted on: the concept, its pointer and its config are all untouched.
    assert one("/concept/corr_v1/med_salbutamol")["version"] == 1
    with SessionLocal() as db:
        gone = [c for c in db.scalars(select(Concept)) if c.deprecated_at is not None]
        assert gone == [], gone
    dropped = get("/concepts?include_deprecated=true").json()
    assert [x for x in dropped if x["deprecated_at"]] == [], dropped

    # --- complete mode has to name its types, and carry only those -----------------------------
    code, body = post(rows=changed, mode="complete")
    assert code == 422, (code, body)
    code, body = post(
        rows=changed + [{"name": "heart_rate", "definition": {"type": "native_dynamic",
                                                              "table_name": "obs"}}],
        mode="complete",
        complete_for_types=["medication"],
    )
    assert code == 422, (code, body)

    # --- a duplicate name is a 422, not a last-one-wins ----------------------------------------
    code, body = post(rows=ROWS + [row("med_fenoterol", "fenoterol (again)")])
    assert code == 422, (code, body)
    assert "med_fenoterol" in json.dumps(body), body
    assert one("/concept/corr_v1/med_fenoterol")["sources"]["cub_hdp"]["json"]["drug"] \
        == "fenoterol"

    # --- an invalid row: skipped and itemised by default, refused under reject ------------------
    bad = changed + [{"name": "med_broken", "definition": {"type": "medication"}}]  # no `drug`
    before = config_count()
    code, body = post(rows=bad)
    assert code == 200, body
    assert body["skipped_invalid"] == 1, body
    assert [e["name"] for e in body["errors"]] == ["med_broken"], body["errors"]
    assert body["errors"][0]["reason"] == "schema" and "drug" in body["errors"][0]["detail"]
    assert get("/concepts").json() and not [
        x for x in get("/concepts").json() if x["name"] == "med_broken"
    ]

    code, body = post(rows=bad, on_invalid="reject")
    assert code == 422, (code, body)
    assert [e["name"] for e in body["detail"]["errors"]] == ["med_broken"], body
    # …and reject is what complete mode defaults to, since a skipped row would otherwise read
    # exactly like a retired one in the report.
    code, body = post(rows=bad, mode="complete", complete_for_types=["medication"])
    assert code == 422, (code, body)
    assert config_count() == before, "a rejected batch wrote something"

    # --- dry_run: full report, nothing written --------------------------------------------------
    before = config_count()
    fresh = changed + [row("med_theophylline", "theophylline")]
    code, body = post(rows=fresh, dry_run=True)
    assert code == 200, body
    assert (body["imported"], body["unchanged"]) == (1, 3), body
    assert body["dry_run"] is True, body
    assert config_count() == before, "a dry run wrote configs"
    assert get("/concept/corr_v1/med_theophylline").status_code == 404
    # …and running it for real then does exactly what it said.
    code, body = post(rows=fresh)
    assert (body["imported"], body["unchanged"]) == (1, 3), body
    assert one("/concept/corr_v1/med_theophylline")["version"] == 1

    # --- the file import keeps its own counsel about the posted variables ------------------------
    # EXTERNALLY_MANAGED_TYPES says medications are somebody else's; a vars.json that never
    # carried them is not evidence that they are gone.
    settings.import_reference_on_first_run = True
    stats = importer.import_reference()
    assert stats is not None
    assert stats.missing_upstream == [], stats.missing_upstream
    assert stats.imported == 1 and stats.unchanged == 0, stats  # heart_rate, from the file
    with SessionLocal() as db:
        medications = db.scalar(
            select(func.count()).select_from(Config).where(Config.type == "medication")
        )

    # Without the setting, the same import reports every posted variable as missing — which is
    # the regression `externally_managed_types` exists to prevent.
    settings.externally_managed_types = []
    stats = importer.import_reference()
    assert len(stats.missing_upstream) == 4, stats.missing_upstream
    with SessionLocal() as db:
        assert db.scalar(
            select(func.count()).select_from(Config).where(Config.type == "medication")
        ) == medications, "the file import wrote to the posted variables"

print("BULK UPSERT SMOKE OK")
