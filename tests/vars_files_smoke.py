"""The import half of a source's file library: staged tree in, versioned files + pins out.

Run: uv run python tests/vars_files_smoke.py

The sidecar stages a plain tree of data files (``reference/files/<relpath>``) — there is no
manifest saying which variable needs which file any more, because a snippet says so itself with
``getfile("<uuid>")``. So the import walks the tree, versions every file whose bytes moved, and
pins each config to the versions its own snippet resolves to.

What is checked here is the whole chain and the two invariants that make it worth having:

* a replaced data file is a **changed definition** — it mints a new concept version, for the
  definitions the import owns *and* for the hand-authored ones reading the same file (the
  cascade runs on every door), exactly one per pass, and the old version keeps serving the
  bytes it was published with;
* a forced reimport **keeps the file library**. It wipes the concept graph, but the files
  belong to the source, and taking them with it would invalidate every uuid in every snippet
  it is about to rebuild.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

STAGED = {
    "postcode/postcode_mapping.csv": b"plz,state\n10117,BE\n",
    "mobilisation/svc.pkl": b"\x80\x04not-really-a-pickle",
    # Staged but read by nothing: a library holds what the source ships, not only what is
    # currently referenced.
    "diagnosis/apache3.csv": b"code,dx\nA,1\n",
}

staging = tempfile.mkdtemp()
for rel, data in STAGED.items():
    target = os.path.join(staging, "files", rel)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(data)

db_path = os.path.join(tempfile.mkdtemp(), "varsfiles.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "true"
os.environ["REFERENCE_FILES_DIR"] = os.path.join(staging, "files")
FILE_DIR = tempfile.mkdtemp()
os.environ["FILE_DIR"] = FILE_DIR

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.importer import import_reference  # noqa: E402
from api.main import app  # noqa: E402
from api.models import (  # noqa: E402
    Blob,
    Config,
    ConfigFileRef,
    SourceFile,
    SourceFileVersion,
    User,
)

with TestClient(app) as c:  # the lifespan seeds + imports the reference dataset
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    c.headers["authorization"] = f"Bearer {tok['access_token']}"
    _raw_get = c.get
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    def one(url: str) -> dict:
        body = c.get(url).json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    # --- the staged tree became the source's library ----------------------------------------
    library = c.get("/sources/cub_hdp/files").json()
    assert [f["path"] for f in library] == sorted(STAGED), library
    assert all(f["version_no"] == 1 for f in library), library
    by_path = {f["path"]: f for f in library}
    postcodes = by_path["postcode/postcode_mapping.csv"]
    # Nothing references anything yet: the reference snippets don't call getfile().
    assert all(f["referenced_by"] == 0 for f in library), library
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Blob)) == 3
        assert db.scalar(select(func.count()).select_from(SourceFile)) == 3
        assert db.scalar(select(func.count()).select_from(ConfigFileRef)) == 0

    # A second pass over the same tree writes nothing at all — the digest check is what makes
    # the sidecar's 60s poll free.
    stats = import_reference()
    assert stats is not None and stats.updated == 0, stats
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SourceFileVersion)) == 3

    # --- a definition that actually reads them ------------------------------------------------
    # Publish a snippet with getfile(), so there is a pin to reason about. It reads two of the
    # staged files, which is what makes "exactly one new version per pass" testable below.
    svc = by_path["mobilisation/svc.pkl"]
    ND = {"type": "native_dynamic", "table_name": "d", "where_clause": "x = 1"}
    assert c.post("/concepts", json={"name": "postcode_state"}).status_code == 201
    draft = c.post(
        "/concept/corr_v1/postcode_state/drafts",
        json={
            "source": "cub_hdp",
            "empty": True,
            "type": "native_dynamic",
            "json": ND,
            "code": (
                "def postcode_state(var, cohort):\n"
                f'    model = load(getfile("{svc["uuid"]}"))\n'
                f'    return model, read(getfile("{postcodes["uuid"]}"))\n'
            ),
        },
    ).json()
    assert draft["unresolved_files"] == [], draft
    assert c.post(
        f"/concept/corr_v1/postcode_state/drafts/{draft['id']}/publish", json={}
    ).json()["version_no"] == 1

    pinned = one("/concept/corr_v1/postcode_state")["sources"]["cub_hdp"]["files"]
    assert {f["uuid"] for f in pinned} == {postcodes["uuid"], svc["uuid"]}, pinned
    assert all(f["version_no"] == 1 for f in pinned), pinned
    by_uuid = {f["uuid"]: f for f in pinned}
    assert by_uuid[postcodes["uuid"]]["path"] == postcodes["path"], pinned
    assert c.get(by_uuid[postcodes["uuid"]]["url"]).content == STAGED[postcodes["path"]]
    # ...and the library now knows who reads it.
    assert c.get(f"/sources/cub_hdp/files/{postcodes['uuid']}").json()["referenced_by"] == 1

    # --- replacing the bytes upstream versions the file, and everything reading it ------------
    NEW_POSTCODES = b"plz,state\n10117,BE\n10557,BE\n"
    with open(os.path.join(staging, "files", postcodes["path"]), "wb") as f:
        f.write(NEW_POSTCODES)
    with open(os.path.join(staging, "files", svc["path"]), "wb") as f:
        f.write(b"\x80\x04still-not-a-pickle")
    stats = import_reference()
    assert stats is not None, stats
    library = {f["path"]: f for f in c.get("/sources/cub_hdp/files").json()}
    assert library[postcodes["path"]]["version_no"] == 2, library
    assert library[svc["path"]]["version_no"] == 2, library
    assert library["diagnosis/apache3.csv"]["version_no"] == 1, library  # untouched bytes

    # The file-update cascade runs on **every** door, the sidecar's included. The import ingests
    # with the cascade *deferred* — the variable upsert running straight after versions the
    # definitions the import owns, and cascading during the ingest as well would give one
    # replaced table two versions in a single pass — and then runs it over the files whose
    # version actually moved. So this hand-authored concept, a name from nobody's vars.json and
    # nothing the upsert would ever look at, is brought forward to the new bytes exactly as an
    # upload through POST /sources/{key}/files would bring it forward. Leaving it pinned would
    # mean a snippet quietly reading a mapping table the source has replaced.
    after = one("/concept/corr_v1/postcode_state")
    assert after["version"] == 2, after
    assert stats.files_synced == 1, stats
    fresh = after["sources"]["cub_hdp"]["files"]
    assert all(f["version_no"] == 2 for f in fresh), fresh
    fresh_by_uuid = {f["uuid"]: f for f in fresh}
    assert c.get(fresh_by_uuid[postcodes["uuid"]]["url"]).content == NEW_POSTCODES

    # Exactly once, and that is the guard doing the work: **two** of its files moved in this one
    # pass, and the second cascade found the config already pinning the newest version and
    # skipped it. The same guard is what stops an imported variable — versioned by the upsert
    # moments earlier — from being versioned a second time by the cascade behind it.
    history = c.get("/concept/corr_v1/postcode_state/history").json()
    assert [h["version"] for h in history] == [2, 1], history
    assert history[0]["change_type"] == "sync", history[0]
    assert "data file" in (history[0]["message"] or ""), history[0]
    # An import-minted version is authored like every other one: the bootstrap admin, not
    # whoever happened to write the snippet.
    with SessionLocal() as db:
        admin_id = db.scalar(select(User.id).where(User.username == "admin"))
        synced = db.scalar(
            select(Config).where(Config.concept_id == after["id"], Config.version_no == 2)
        )
        assert synced.created_by == admin_id and synced.approved_by == admin_id, synced
    # ...and nothing the import owns was versioned by any of this: no imported variable reads a
    # file, so the cascade had nothing of theirs to bring forward.
    assert stats.updated == 0, stats

    # v1 still serves the bytes it was published against.
    old = one("/concept/corr_v1/postcode_state?v=1")["sources"]["cub_hdp"]["files"]
    assert all(f["version_no"] == 1 for f in old), old
    assert c.get({f["uuid"]: f for f in old}[postcodes["uuid"]]["url"]).content == (
        STAGED[postcodes["path"]]
    )

    # An unchanged pass over the same files writes nothing — no new file version, no new
    # concept version, nothing cascaded. This is what makes the sidecar's 60s poll free.
    stats = import_reference()
    assert stats is not None and (stats.updated, stats.files_synced) == (0, 0), stats
    assert one("/concept/corr_v1/postcode_state")["version"] == 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SourceFileVersion)) == 5

    # --- a forced reimport keeps the library --------------------------------------------------
    # It wipes the concept graph and rebuilds it, but the files belong to the *source*: taking
    # them along would invalidate every uuid in every snippet the rebuild is about to write.
    stats = import_reference(force=True)
    assert stats is not None, stats
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(SourceFile)) == 3
        assert db.scalar(select(func.count()).select_from(SourceFileVersion)) == 5
        # The pins went with the configs they belonged to; the reference snippets call no
        # getfile(), so the rebuilt graph pins nothing.
        assert db.scalar(select(func.count()).select_from(ConfigFileRef)) == 0
        # Nothing was collected: every blob is still named by a file version, including the
        # bytes only the retired v1 pins ever pointed at.
        assert db.scalar(select(func.count()).select_from(Blob)) == 5
    stored = [f for _, _, names in os.walk(FILE_DIR) for f in names]
    assert len(stored) == 5, stored
    assert len(c.get("/sources/cub_hdp/files").json()) == 3

print("VARS FILES SMOKE OK")
