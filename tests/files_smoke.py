"""Downloading a concept version's data files, by uuid, at the version it pinned.

Run: uv run python tests/files_smoke.py

Covers the invariant the whole design exists for — a config pins a *file version*, so v1 keeps
serving v1's mapping table after v2 replaces it — from the concept side: the manifest a read
hands out, the `?v=` / `?draft=` selectors on the download, and the input the blob store
refuses. The library side (upload, cascade, retire) is `tests/source_files_smoke.py`.
"""
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "files.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["APP_SHARED_SECRET"] = ""  # app mode: the project gate is off for this test
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
FILE_DIR = tempfile.mkdtemp()
os.environ["FILE_DIR"] = FILE_DIR
os.environ["MAX_UPLOAD_BYTES"] = "2048"  # small, so the oversize path is cheap to exercise

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

ND = {"type": "native_dynamic", "table_name": "diagnoses", "where_clause": "code LIKE 'Z49%'"}
PATH = "postcode/postcode_mapping.csv"
V1_BYTES = b"plz,region\n10117,Mitte\n"
V2_BYTES = b"plz,region\n10117,Mitte\n10557,Tiergarten\n"


def snippet(uuid: str) -> str:
    return f'def postcodes(var, cohort):\n    return read_csv(getfile("{uuid}"))\n'


with TestClient(app) as c:
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    c.headers["authorization"] = f"Bearer {tok['access_token']}"
    # Concept reads take a required `project`; app mode ignores its value but it must be there.
    _raw_get = c.get
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    def one(url: str) -> dict:
        body = c.get(url).json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    # --- put a file in the source's library ---------------------------------------------------
    r = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH},
        files={"file": ("postcode_mapping.csv", V1_BYTES, "text/csv")},
    )
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["path"] == PATH and up["version_no"] == 1 and up["bumped"] == [], up
    uuid = up["uuid"]
    sha1 = hashlib.sha256(V1_BYTES).hexdigest()
    # Bytes are on disk, content-addressed and sharded — never in the DB.
    assert os.path.isfile(os.path.join(FILE_DIR, sha1[:2], sha1)), FILE_DIR

    # --- a definition that reads it -----------------------------------------------------------
    assert c.post("/concepts", json={"name": "postcodes"}).status_code == 201
    d1 = c.post(
        "/concept/corr_v1/postcodes/drafts",
        json={
            "source": "cub_hdp", "empty": True, "type": "native_dynamic",
            "json": ND, "code": snippet(uuid),
        },
    ).json()
    # The pin is read out of the snippet, not declared beside it.
    assert d1["unresolved_files"] == [] and d1["files_changed_since_draft"] == [], d1
    draft_files = one(f"/concept/corr_v1/postcodes?draft={d1['id']}")["sources"]["cub_hdp"]["files"]
    assert [f["uuid"] for f in draft_files] == [uuid], draft_files

    assert c.post(
        f"/concept/corr_v1/postcodes/drafts/{d1['id']}/publish", json={}
    ).json()["version_no"] == 1

    # --- the manifest a read hands out ---------------------------------------------------------
    listed = one("/concept/corr_v1/postcodes")["sources"]["cub_hdp"]["files"]
    assert len(listed) == 1, listed
    f1 = listed[0]
    # Everything a client needs to pre-download before running the snippet: the uuid the
    # snippet will ask for, the version this definition means, the digest, and where to put it.
    assert f1["uuid"] == uuid and f1["version_no"] == 1 and f1["path"] == PATH, f1
    assert f1["sha256"] == sha1 and f1["size"] == len(V1_BYTES), f1
    # The url addresses the concept by id — a name may point at several concepts, the bytes
    # belong to exactly one — and the file by uuid, which is what the snippet says.
    assert f1["url"] == f"/concept/id/{one('/concept/corr_v1/postcodes')['id']}/files/{uuid}?v=1", f1
    r = c.get(f1["url"])
    assert r.status_code == 200 and r.content == V1_BYTES, r.status_code
    assert r.headers["content-type"].startswith("text/csv"), r.headers
    assert 'filename="postcode_mapping.csv"' in r.headers["content-disposition"], r.headers
    assert r.headers["etag"] == f'"{sha1}"', r.headers
    # A uuid this version doesn't pin is a 404, not somebody else's file.
    assert c.get("/concept/corr_v1/postcodes/files/not-a-uuid").status_code == 404
    # ...and so is the old path-addressed form. This route is uuid-only now.
    assert c.get(f"/concept/corr_v1/postcodes/files/{PATH}").status_code == 404

    # --- replacing the file publishes a new version ---------------------------------------------
    # v2 gets the new bytes, v1 keeps the old ones. This pinning is the whole reason a config
    # references a file *version* rather than a file.
    r = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH},
        files={"file": ("postcode_mapping.csv", V2_BYTES, "text/csv")},
    )
    assert r.status_code == 201 and r.json()["version_no"] == 2, r.text
    assert [b["concept_id"] for b in r.json()["bumped"]] and r.json()["unchanged"] is False, r.json()

    current = one("/concept/corr_v1/postcodes")["sources"]["cub_hdp"]["files"][0]
    assert current["version_no"] == 2, current
    assert c.get(current["url"]).content == V2_BYTES
    v1_file = one("/concept/corr_v1/postcodes?v=1")["sources"]["cub_hdp"]["files"][0]
    assert v1_file["version_no"] == 1 and v1_file["sha256"] == sha1, v1_file
    assert c.get(v1_file["url"]).content == V1_BYTES

    # --- an empty draft starts with no files ----------------------------------------------------
    d_empty = c.post(
        "/concept/corr_v1/postcodes/drafts",
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic", "json": ND},
    ).json()["id"]
    assert one(f"/concept/corr_v1/postcodes?draft={d_empty}")["sources"]["cub_hdp"]["files"] == []
    assert c.delete(f"/concept/corr_v1/postcodes/drafts/{d_empty}").status_code == 204

    # --- what the store refuses -----------------------------------------------------------------
    def _upload(path: str, data: bytes = b"x,y\n1,2\n"):
        return c.post(
            "/sources/cub_hdp/files",
            data={"path": path},
            files={"file": ("f.csv", data, "text/csv")},
        )

    for bad in ("../secrets.csv", "a/../../b.csv", "/etc/passwd.csv", "dir\\file.csv", ""):
        assert _upload(bad).status_code in (400, 422), (bad, _upload(bad).status_code)
    assert _upload("payload.exe").status_code == 400          # suffix allowlist
    assert _upload("big.csv", b"z" * 4096).status_code == 413  # over MAX_UPLOAD_BYTES
    # ...and a traversal attempt on the way *out* is refused the same way.
    assert c.get("/concept/corr_v1/postcodes/files/../../etc/passwd").status_code in (400, 404)

print("FILES SMOKE OK")
