"""A source's file library: upload, cascade, pinning, idempotence, retire.

Run: uv run python tests/source_files_smoke.py

The library side of the file model — `tests/files_smoke.py` covers the concept side. The five
things that make it worth having, in order:

1. an upload **cascades**: every concept whose current published config reads the file gets a
   new published version, because a replaced mapping table changes what the definition computes
   just as surely as rewriting its code would;
2. an older published version still serves the **old bytes** — that is what the pin is for;
3. re-uploading identical bytes is a **no-op**: nothing minted, nothing cascaded;
4. retiring a file is refused with **409** while anything published still reads it, and the
   referencing concepts come back in the body;
5. the permissions: reading the library is `can_read`, writing it is `can_publish`.

Plus the two properties the identity rests on: the uuid is **derived** (uuid5 of the source key
and the path the file was created under, so a fresh database mints the same one — a snippet may
hardcode it), and a new version may **rename** the file without moving that identity.
"""
import os
import subprocess
import sys
import tempfile
import uuid as uuidlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "sourcefiles.db")
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

from api import security  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import User  # noqa: E402

ND = {"type": "native_dynamic", "table_name": "d", "where_clause": "x = 1"}
PATH = "postcode/mapping.csv"
NEWPATH = "postcode/postcodes.csv"  # the same file, renamed by a new version
PATH2 = "postcode/plz.csv"  # ...and renamed again, without new bytes
OTHER = "postcode/taken.csv"
V1 = b"plz,state\n10117,BE\n"
V2 = b"plz,state\n10117,BE\n10557,BE\n"
V4 = b"plz,state\n10117,BE\n10557,BE\n13347,BE\n12043,BE\n"


def snippet(uuid: str) -> str:
    return f'def v(var, cohort):\n    return read_csv(getfile("{uuid}"))\n'


with TestClient(app) as c:
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    admin = f"Bearer {tok['access_token']}"
    c.headers["authorization"] = admin
    _raw_get = c.get
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    def one(url: str) -> dict:
        body = c.get(url).json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    def publish(name: str, code: str | None) -> int:
        assert c.post("/concepts", json={"name": name}).status_code == 201
        body = {"source": "cub_hdp", "empty": True, "type": "native_dynamic", "json": ND}
        if code is not None:
            body["code"] = code
        d = c.post(f"/concept/corr_v1/{name}/drafts", json=body).json()
        r = c.post(f"/concept/corr_v1/{name}/drafts/{d['id']}/publish", json={})
        assert r.status_code == 200, r.text
        return r.json()["version_no"]

    # --- upload ---------------------------------------------------------------------------------
    up = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH, "message": "initial table"},
        files={"file": ("mapping.csv", V1, "text/csv")},
    )
    assert up.status_code == 201, up.text
    uuid = up.json()["uuid"]
    assert up.json()["version_no"] == 1 and up.json()["bumped"] == [], up.json()

    # --- (a) the uuid is derived, not random -----------------------------------------------------
    # Computed here from the published recipe rather than imported from the app, because that
    # recipe is a contract: corr-vars derives the same uuids offline to write `getfile("…")`
    # into snippets, so a changed namespace or seed format has to fail *here*.
    ns = uuidlib.uuid5(uuidlib.NAMESPACE_URL, "concepts-browser/source-file")
    assert uuid == str(uuidlib.uuid5(ns, f"cub_hdp/{PATH}")), uuid

    # --- (b) a fresh database mints the same uuid --------------------------------------------------
    # The property the whole derivation exists for: another deployment, or this one after a
    # wipe-and-reimport, has to name the file identically. Booted in a subprocess because the
    # app binds its engine to DATABASE_URL at import.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    child = os.path.join(tempfile.mkdtemp(), "child.py")
    with open(child, "w") as fh:
        fh.write(
            "import os, sys, tempfile, warnings\n"
            f"sys.path.insert(0, {repo!r})\n"
            'os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "f.db")\n'
            'os.environ["FILE_DIR"] = tempfile.mkdtemp()\n'
            'os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"\n'
            'os.environ["APP_SHARED_SECRET"] = ""\n'
            'os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"\n'
            'os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"\n'
            'os.environ.setdefault("SCHEMA_DIR", "reference/schema")\n'
            'os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"\n'
            'warnings.filterwarnings("ignore")\n'
            "from fastapi.testclient import TestClient\n"
            "from api.main import app\n"
            "with TestClient(app) as c:\n"
            '    t = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()\n'
            '    c.headers["authorization"] = "Bearer " + t["access_token"]\n'
            '    r = c.post("/sources/cub_hdp/files", data={"path": %r},\n'
            '               files={"file": ("mapping.csv", %r, "text/csv")})\n'
            "    assert r.status_code == 201, r.text\n"
            '    print(r.json()["uuid"])\n' % (PATH, V1)
        )
    out = subprocess.run(
        [sys.executable, child], cwd=repo, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip().splitlines()[-1] == uuid, (out.stdout, out.stderr)

    # An unknown source is a 404, not an empty library.
    assert c.post(
        "/sources/nosuch/files", data={"path": PATH},
        files={"file": ("m.csv", V1, "text/csv")},
    ).status_code == 404

    # --- two concepts read it, one doesn't ------------------------------------------------------
    assert publish("reader_a", snippet(uuid)) == 1
    assert publish("reader_b", snippet(uuid)) == 1
    assert publish("bystander", None) == 1

    refs = c.get(f"/sources/cub_hdp/files/{uuid}/references").json()
    assert sorted(r["name"] for r in refs) == ["reader_a", "reader_b"], refs
    assert all(r["taxonomy"] == "corr_v1" for r in refs), refs
    listed = c.get("/sources/cub_hdp/files").json()
    assert len(listed) == 1 and listed[0]["referenced_by"] == 2, listed
    assert listed[0]["updated_by"] == "admin" and listed[0]["version_no"] == 1, listed

    # --- (1) uploading a new version cascades ----------------------------------------------------
    up2 = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH, "message": "added Moabit"},
        files={"file": ("mapping.csv", V2, "text/csv")},
    )
    assert up2.status_code == 201, up2.text
    result = up2.json()
    assert result["version_no"] == 2 and result["unchanged"] is False, result
    assert sorted(b["name"] for b in result["bumped"]) == ["reader_a", "reader_b"], result
    assert all(b["version_no"] == 2 for b in result["bumped"]), result

    for name in ("reader_a", "reader_b"):
        body = one(f"/concept/corr_v1/{name}")
        assert body["version"] == 2, (name, body)
        info = body["sources"]["cub_hdp"]["version_info"]
        assert info["change_type"] == "sync", (name, info)
        assert body["sources"]["cub_hdp"]["files"][0]["version_no"] == 2, body
    # A concept that reads nothing is untouched: the cascade follows the pins, not the source.
    assert one("/concept/corr_v1/bystander")["version"] == 1

    # --- (2) the old published version still serves the old bytes ---------------------------------
    old = one("/concept/corr_v1/reader_a?v=1")["sources"]["cub_hdp"]["files"][0]
    assert old["version_no"] == 1, old
    assert c.get(old["url"]).content == V1
    assert c.get(f"/sources/cub_hdp/files/{uuid}/download?version=1").content == V1
    assert c.get(f"/sources/cub_hdp/files/{uuid}/download?version=2").content == V2
    assert c.get(f"/sources/cub_hdp/files/{uuid}/download").content == V2  # current by default
    assert c.get(f"/sources/cub_hdp/files/{uuid}/download?version=9").status_code == 404

    detail = c.get(f"/sources/cub_hdp/files/{uuid}").json()
    assert [v["version_no"] for v in detail["versions"]] == [2, 1], detail
    assert [v["message"] for v in detail["versions"]] == ["added Moabit", "initial table"], detail

    # --- (3) re-uploading identical bytes is a no-op ------------------------------------------------
    same = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH},
        files={"file": ("mapping.csv", V2, "text/csv")},
    ).json()
    assert same["unchanged"] is True and same["version_no"] == 2 and same["bumped"] == [], same
    assert one("/concept/corr_v1/reader_a")["version"] == 2, "an identical upload published a version"
    assert len(c.get(f"/sources/cub_hdp/files/{uuid}").json()["versions"]) == 2

    # --- drafts are not cascaded into, they are warned ----------------------------------------------
    d = c.post("/concept/corr_v1/reader_a/drafts", json={"source": "cub_hdp"}).json()
    assert d["files_changed_since_draft"] == [], d  # a fresh draft pins what is current
    c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH},
        files={"file": ("mapping.csv", b"plz,state\n10117,BE\n13347,BE\n", "text/csv")},
    )
    open_drafts = c.get("/concept/corr_v1/reader_a/drafts").json()
    drift = open_drafts[0]["files_changed_since_draft"]
    assert drift == [
        {"uuid": uuid, "path": PATH, "pinned_version": 2, "current_version": 3}
    ], drift
    # Publishing re-pins to what is current, which is how the drift is resolved.
    assert c.post(f"/concept/corr_v1/reader_a/drafts/{d['id']}/publish", json={}).status_code == 200
    assert one("/concept/corr_v1/reader_a")["sources"]["cub_hdp"]["files"][0]["version_no"] == 3

    # --- an unknown uuid warns on a draft and blocks a publish ---------------------------------------
    bad = c.post(
        "/concept/corr_v1/bystander/drafts",
        json={
            "source": "cub_hdp", "empty": True, "type": "native_dynamic", "json": ND,
            "code": snippet("11111111-2222-3333-4444-555555555555"),
        },
    ).json()
    assert bad["unresolved_files"] == ["11111111-2222-3333-4444-555555555555"], bad
    r = c.post(f"/concept/corr_v1/bystander/drafts/{bad['id']}/publish", json={})
    assert r.status_code == 400, r.text
    assert r.json()["detail"]["error"] == "unresolved_file_references", r.json()
    assert c.delete(f"/concept/corr_v1/bystander/drafts/{bad['id']}").status_code == 204

    # --- (c) a new version may rename the file ------------------------------------------------------
    # The bug this covers: replacing a file with one that has a different name kept showing the
    # old name everywhere. The identity is the uuid, so the path is free to move — and what each
    # place shows follows from what it describes.
    pinned_before = {
        name: one(f"/concept/corr_v1/{name}")["sources"]["cub_hdp"]["files"][0]["version_no"]
        for name in ("reader_a", "reader_b")
    }
    ren = c.post(
        "/sources/cub_hdp/files",
        data={"path": NEWPATH, "uuid": uuid, "message": "renamed on replace"},
        files={"file": ("postcodes.csv", V4, "text/csv")},
    )
    assert ren.status_code == 201, ren.text
    renamed = ren.json()
    assert renamed["uuid"] == uuid, renamed  # identity survives the rename
    assert renamed["path"] == NEWPATH and renamed["version_no"] == 4, renamed
    assert sorted(b["name"] for b in renamed["bumped"]) == ["reader_a", "reader_b"], renamed

    # The library describes the file as it stands: the current name.
    listed = c.get("/sources/cub_hdp/files").json()
    assert [f["path"] for f in listed if f["uuid"] == uuid] == [NEWPATH], listed
    assert c.get(f"/sources/cub_hdp/files/{uuid}").json()["path"] == NEWPATH

    # A manifest describes what one config version pinned, so it keeps the name it was
    # published against — a client laying out an old version's files must not have them move.
    for name, was in pinned_before.items():
        old_manifest = one(f"/concept/corr_v1/{name}?v={was}")["sources"]["cub_hdp"]["files"][0]
        assert old_manifest["path"] == PATH, (name, old_manifest)
        assert old_manifest["uuid"] == uuid, (name, old_manifest)
        assert c.get(old_manifest["url"]).headers["content-disposition"].endswith('"mapping.csv"')
        # ...while the version the rename just published pins the new name.
        fresh = one(f"/concept/corr_v1/{name}")["sources"]["cub_hdp"]["files"][0]
        assert fresh["path"] == NEWPATH and fresh["version_no"] == 4, (name, fresh)

    # The version history carries both names, which is where a rename is visible.
    history = c.get(f"/sources/cub_hdp/files/{uuid}").json()["versions"]
    assert [(v["version_no"], v["path"]) for v in history] == [
        (4, NEWPATH), (3, PATH), (2, PATH), (1, PATH)
    ], history
    # ...and a version is downloaded under the name it was uploaded with.
    d1 = c.get(f"/sources/cub_hdp/files/{uuid}/download?version=1")
    assert d1.content == V1 and d1.headers["content-disposition"].endswith('"mapping.csv"'), d1.headers
    d4 = c.get(f"/sources/cub_hdp/files/{uuid}/download?version=4")
    assert d4.content == V4 and d4.headers["content-disposition"].endswith('"postcodes.csv"'), d4.headers

    # A rename with identical bytes is still a rename: no version, no cascade, new name.
    back = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH2, "uuid": uuid},
        files={"file": ("postcodes.csv", V4, "text/csv")},
    ).json()
    assert back["unchanged"] is True and back["version_no"] == 4 and back["bumped"] == [], back
    assert back["path"] == PATH2, back
    assert c.get(f"/sources/cub_hdp/files/{uuid}").json()["path"] == PATH2

    # --- (d) a rename onto a live path is a 409 -------------------------------------------------------
    other = c.post(
        "/sources/cub_hdp/files",
        data={"path": OTHER},
        files={"file": ("other.csv", b"a,b\n1,2\n", "text/csv")},
    ).json()
    assert other["uuid"] == str(uuidlib.uuid5(ns, f"cub_hdp/{OTHER}")), other
    clash = c.post(
        "/sources/cub_hdp/files",
        data={"path": OTHER, "uuid": uuid},
        files={"file": ("other.csv", b"a,b\n3,4\n", "text/csv")},
    )
    assert clash.status_code == 409, clash.text
    assert clash.json()["detail"]["error"] == "file_path_taken", clash.json()
    assert clash.json()["detail"]["uuid"] == other["uuid"], clash.json()
    # Nothing moved: the refusal is before anything is written.
    assert c.get(f"/sources/cub_hdp/files/{uuid}").json()["path"] == PATH2
    assert len(c.get(f"/sources/cub_hdp/files/{other['uuid']}").json()["versions"]) == 1

    # A uuid that names nothing in this source is a 404, not a new file under that uuid.
    assert c.post(
        "/sources/cub_hdp/files",
        data={"path": "nope.csv", "uuid": "11111111-2222-3333-4444-555555555555"},
        files={"file": ("nope.csv", b"x\n", "text/csv")},
    ).status_code == 404

    # The documented edge of a frozen identity: the seed of a path the renamed file vacated is
    # already taken, so a new file created there cannot have the derived uuid.
    revived = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH},
        files={"file": ("mapping.csv", b"plz,state\n99999,XX\n", "text/csv")},
    ).json()
    assert revived["uuid"] != uuid and revived["path"] == PATH, revived
    assert revived["uuid"] != str(uuidlib.uuid5(ns, f"cub_hdp/{PATH}")), revived
    assert c.delete(f"/sources/cub_hdp/files/{revived['uuid']}").status_code == 204

    # --- (4) retiring is refused while anything published reads it -------------------------------------
    r = c.delete(f"/sources/cub_hdp/files/{uuid}")
    assert r.status_code == 409, r.text
    detail = r.json()["detail"]
    assert sorted(x["name"] for x in detail["references"]) == ["reader_a", "reader_b"], detail
    assert all({"concept_id", "taxonomy", "name", "display_name"} <= set(x) for x in detail["references"])

    # Take the references out of circulation by deprecating the concepts, then it goes.
    for name in ("reader_a", "reader_b"):
        cid = one(f"/concept/corr_v1/{name}")["id"]
        req = c.post(f"/concept/id/{cid}/deprecation-request", json={"reason": "test"})
        assert req.status_code == 201, req.text
        assert c.post(
            f"/deprecation-requests/{req.json()['id']}/approve", json={}
        ).status_code == 200
    assert c.delete(f"/sources/cub_hdp/files/{uuid}").status_code == 204
    assert [f["uuid"] for f in c.get("/sources/cub_hdp/files").json()] == [other["uuid"]]
    assert c.get(f"/sources/cub_hdp/files/{uuid}").status_code == 404
    # ...but the bytes stay reachable, because a published version still pins them. A soft
    # delete is the only kind there can be here.
    assert c.get(f"/sources/cub_hdp/files/{uuid}/download?version=1").content == V1
    assert c.get(one("/concept/corr_v1/reader_a?v=1")["sources"]["cub_hdp"]["files"][0]["url"]).content == V1

    # --- (5) permissions ----------------------------------------------------------------------------
    # An editor may read the library — the code editor's completions need it — but may not
    # write it: an upload publishes.
    with SessionLocal() as db:
        db.add(
            User(
                username="ed",
                password_hash=security.hash_password("pw"),
                capabilities=["can_read", "can_edit"],
                is_active=True,
            )
        )
        db.commit()
    ed = c.post("/auth/login", json={"username": "ed", "password": "pw"})
    assert ed.status_code == 200, ed.text
    editor = {"authorization": f"Bearer {ed.json()['access_token']}"}
    assert _raw_get("/sources/cub_hdp/files", headers=editor).status_code == 200
    assert c.post(
        "/sources/cub_hdp/files", data={"path": "other.csv"},
        files={"file": ("o.csv", b"a,b\n", "text/csv")}, headers=editor,
    ).status_code == 403
    assert c.delete(f"/sources/cub_hdp/files/{uuid}", headers=editor).status_code == 403

print("SOURCE FILES SMOKE OK")
