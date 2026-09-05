"""`can_read` vs `can_read_detail`: reading a concept vs reading what it computes.

Run: uv run python tests/read_detail_smoke.py

`can_read` — the default, and the only thing the LDAP auto-grant hands out — gets the concept
and its JSON definition. The `py` snippet and the bytes of the data files that snippet reads
need `can_read_detail` on top. The split has to hold in a very specific way, because the API's
other consumer is a machine (corr-vars, which fetches snippets to build variables):

1. the concept read **still works** on `can_read` — browsing is what the capability is for;
2. but the withheld snippet is **marked**, not silently nulled (`py_locked`, plus the
   `X-Concepts-Locked` response header). A null `py` alone is indistinguishable from "this
   definition has no Python", and resolving a concept to no-code is the fallback this project
   refuses to make silently;
3. every route serving actual **content** — both file-download routes — is a flat **403**;
4. a draft's snippet is a snippet: the same treatment on the draft routes;
5. the boot migration carries the `can_read`-only users *and their API keys* across once, and
   is a no-op on every boot after that — so a deployment upgrading into this feature doesn't
   lose access, while accounts created afterwards (LDAP auto-grant) really do start without
   detail. Anything above `can_read` needs no carrying: the capability chain entails detail
   (see tests/capability_chain_smoke.py).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "readdetail.db")
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
from sqlalchemy import select  # noqa: E402

from api import security  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import _grant_read_detail_to_existing_readers, app  # noqa: E402
from api.models import ApiKey, User  # noqa: E402

ND = {"type": "native_dynamic", "table_name": "d", "where_clause": "x = 1"}
PATH = "lookup/table.csv"
BYTES = b"code,label\n1,one\n"


def make_user(username: str, caps: list[str]) -> int:
    with SessionLocal() as db:
        u = User(
            username=username,
            password_hash=security.hash_password("pw"),
            capabilities=caps,
            is_active=True,
        )
        db.add(u)
        db.commit()
        return u.id


with TestClient(app) as c:
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    c.headers["authorization"] = f"Bearer {tok['access_token']}"
    # Every concept read takes a `project` param; the app-secret is empty here, so the value
    # is not validated but must be present.
    _raw_get = c.get
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    def login(username: str) -> dict:
        r = c.post("/auth/login", json={"username": username, "password": "pw"})
        assert r.status_code == 200, r.text
        return {"authorization": f"Bearer {r.json()['access_token']}"}

    def get(url: str, headers: dict):
        return _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", headers=headers)

    # --- a concept with a snippet and a pinned data file ------------------------------------------
    up = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH},
        files={"file": ("table.csv", BYTES, "text/csv")},
    )
    assert up.status_code == 201, up.text
    file_uuid = up.json()["uuid"]

    CODE = f'def v(var, cohort):\n    return read_csv(getfile("{file_uuid}"))\n'
    assert c.post("/concepts", json={"name": "lookup_var"}).status_code == 201
    draft = c.post(
        "/concept/corr_v1/lookup_var/drafts",
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
              "json": ND, "py": CODE},
    ).json()
    pub = c.post(f"/concept/corr_v1/lookup_var/drafts/{draft['id']}/publish", json={})
    assert pub.status_code == 200, pub.text

    # A second, still-open draft, so the draft routes have something to withhold.
    open_draft = c.post(
        "/concept/corr_v1/lookup_var/drafts",
        json={"source": "cub_hdp", "py": CODE + "# revised\n"},
    )
    assert open_draft.status_code == 201, open_draft.text

    make_user("reader", ["can_read"])
    make_user("deep", ["can_read", "can_read_detail"])
    # An editor holds `can_read_detail` by entailment — `can_edit` sits above it in the chain
    # (api/security.CAPABILITY_CHAIN) — so the mask never applies to somebody who may write.
    make_user("editor", ["can_edit"])
    reader_h, deep_h, editor_h = login("reader"), login("deep"), login("editor")

    # --- (1) the concept read still works on can_read, JSON and all -------------------------------
    r = get("/concept/corr_v1/lookup_var", reader_h)
    assert r.status_code == 200, r.text
    block = r.json()[0]["sources"]["cub_hdp"]
    assert block["json"] == ND, block["json"]
    assert block["version_info"]["source_version"] == 1, block["version_info"]
    # The file *manifest* is metadata and comes through — it is how a client learns a download
    # exists at all, and the refusal belongs on the bytes, not on the knowledge of them.
    assert [f["uuid"] for f in block["files"]] == [file_uuid], block["files"]

    # --- (2) ...but the snippet is withheld, and says so ------------------------------------------
    assert block["py"] is None, block["py"]
    assert block["py_locked"] is True, block
    assert r.headers.get("X-Concepts-Locked") == "can_read_detail", dict(r.headers)

    # The id form is the same route body; it must not drift.
    concept_id = r.json()[0]["id"]
    by_id = get(f"/concept/id/{concept_id}", reader_h)
    assert by_id.json()["sources"]["cub_hdp"]["py_locked"] is True, by_id.text
    assert by_id.headers.get("X-Concepts-Locked") == "can_read_detail", dict(by_id.headers)

    # --- (3) file content is a flat 403, never empty bytes ----------------------------------------
    url = block["files"][0]["url"]  # the concept-scoped download the manifest hands out
    assert get(url, reader_h).status_code == 403, get(url, reader_h).text
    assert get(f"/concept/id/{concept_id}/files/{file_uuid}", reader_h).status_code == 403
    lib = f"/sources/cub_hdp/files/{file_uuid}/download"
    assert _raw_get(lib, headers=reader_h).status_code == 403, _raw_get(lib, headers=reader_h).text
    # The library *metadata* stays readable on can_read — the editor's completions need it.
    assert _raw_get("/sources/cub_hdp/files", headers=reader_h).status_code == 200
    assert _raw_get(f"/sources/cub_hdp/files/{file_uuid}", headers=reader_h).status_code == 200

    # --- (4) drafts get the same treatment --------------------------------------------------------
    drafts = _raw_get("/concept/corr_v1/lookup_var/drafts", headers=reader_h)
    assert drafts.status_code == 200, drafts.text
    assert len(drafts.json()) == 1, drafts.json()
    assert drafts.json()[0]["py"] is None and drafts.json()[0]["py_locked"] is True, drafts.json()
    # An editor writes a draft and is shown the code back: `can_edit` entails
    # `can_read_detail`, so no editor is ever handed a locked snippet to overwrite.
    edited = c.put(
        f"/concept/corr_v1/lookup_var/drafts/{drafts.json()[0]['id']}",
        json={"py": CODE + "# again\n"},
        headers=editor_h,
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["py"] and edited.json()["py_locked"] is False, edited.json()
    # ...and the same on the published read the draft editor opens beside it.
    editor_block = get("/concept/corr_v1/lookup_var", editor_h).json()[0]["sources"]["cub_hdp"]
    assert editor_block["py"] == CODE and editor_block["py_locked"] is False, editor_block

    # --- the same reads, with the capability ------------------------------------------------------
    r = get("/concept/corr_v1/lookup_var", deep_h)
    assert r.status_code == 200, r.text
    deep_block = r.json()[0]["sources"]["cub_hdp"]
    assert deep_block["py"] == CODE, deep_block["py"]
    assert deep_block["py_locked"] is False, deep_block
    assert "X-Concepts-Locked" not in r.headers, dict(r.headers)
    assert get(url, deep_h).content == BYTES
    assert _raw_get(lib, headers=deep_h).content == BYTES
    assert _raw_get("/concept/corr_v1/lookup_var/drafts", headers=deep_h).json()[0]["py"], "draft py"

    # A concept genuinely without Python is *not* flagged: py_locked distinguishes "withheld"
    # from "there is none", which is the whole reason it exists.
    assert c.post("/concepts", json={"name": "plain_var"}).status_code == 201
    plain = c.post(
        "/concept/corr_v1/plain_var/drafts",
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic", "json": ND},
    ).json()
    assert c.post(
        f"/concept/corr_v1/plain_var/drafts/{plain['id']}/publish", json={}
    ).status_code == 200
    plain_read = get("/concept/corr_v1/plain_var", reader_h)
    plain_block = plain_read.json()[0]["sources"]["cub_hdp"]
    assert plain_block["py"] is None and plain_block["py_locked"] is False, plain_block
    assert "X-Concepts-Locked" not in plain_read.headers, dict(plain_read.headers)

    # --- (5) the boot migration -------------------------------------------------------------------
    # Rewind the database to what one written before this feature looks like: nobody holds the
    # capability, and there is a live API key scoped `can_read` (a deployed corr-vars key).
    with SessionLocal() as db:
        for u in db.scalars(select(User)):
            u.capabilities = [c_ for c_ in (u.capabilities or []) if c_ != "can_read_detail"]
        db.add(
            ApiKey(
                user_id=1,
                name="corr-vars",
                key_hash="deadbeef" * 8,
                key_prefix="cak_test",
                scopes=["can_read"],
            )
        )
        db.commit()

    _grant_read_detail_to_existing_readers()

    with SessionLocal() as db:
        caps = {u.username: set(u.capabilities or []) for u in db.scalars(select(User))}
        # Everyone who could read can still read code.
        assert "can_read_detail" in caps["reader"], caps
        assert "can_read_detail" in caps["deep"], caps
        # The editor is left alone: `can_edit` entails detail, so there was nothing to carry
        # across — the migration only touches grants that genuinely sit *below* it.
        assert caps["editor"] == {"can_edit"}, caps
        # ...and the key, because effective scope is `scopes ∩ owner caps`: widening only the
        # owner would still have cut the deployed key off.
        key = db.scalar(select(ApiKey).where(ApiKey.name == "corr-vars"))
        assert set(key.scopes) == {"can_read", "can_read_detail"}, key.scopes

    # Idempotent: a second run changes nothing, and — the point of the feature — an account
    # created *after* the migration (as the LDAP auto-grant creates them) is left alone.
    make_user("newcomer", ["can_read"])
    _grant_read_detail_to_existing_readers()
    _grant_read_detail_to_existing_readers()
    with SessionLocal() as db:
        after = {u.username: list(u.capabilities or []) for u in db.scalars(select(User))}
        assert after["newcomer"] == ["can_read"], after["newcomer"]
        # No duplicates from re-running over an already-granted account.
        assert after["reader"].count("can_read_detail") == 1, after["reader"]

print("READ DETAIL SMOKE OK")
