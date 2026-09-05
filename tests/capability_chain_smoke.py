"""Capabilities are a chain: holding one entails every lesser one.

Run: uv run python tests/capability_chain_smoke.py

    can_read < can_read_detail < can_edit < can_publish

A publisher does not need `can_read` granted separately to browse, an editor does not need
`can_read_detail` to be shown the snippet they are about to overwrite. Entailment is
evaluation-time only (`security.expand_capabilities`, reached through `deps.has_capability`):
stored grants are never rewritten, and a row holding `can_publish` alone stays that way.

What this pins down:

1. the matrix itself — every capability in the chain is covered by every capability above it,
   and by nothing below it;
2. the two dimensions that stay *outside* the chain: `create_api_key` and `add_project` are
   independent (publishing does not let you mint keys), and `can_admin` implies everything;
3. the routes agree with the matrix — a `can_publish`-only user reads concepts and opens the
   review queue, a `can_edit`-only user gets an unlocked snippet (`py_locked` false) and
   reaches the draft editor but not the queue, and nobody gained a route they used to be
   refused;
4. API keys narrow along the chain rather than escaping it: effective scope is
   `expand(key.scopes) ∩ expand(owner.capabilities)`, so a key scoped `can_publish` on a
   publisher reads code, while a key scoped `can_read` on the same owner still does not;
5. `can_review` is gone — reviewing is publishing — and the boot migration clears the retired
   string out of the grants and key scopes an older database still carries.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "capchain.db")
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
from sqlalchemy import select  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.main import _drop_can_review, app  # noqa: E402
from api.models import ApiKey, User  # noqa: E402

CHAIN = security.CAPABILITY_CHAIN
ND = {"type": "native_dynamic", "table_name": "d", "where_clause": "x = 1"}
PATH = "lookup/table.csv"
BYTES = b"code,label\n1,one\n"

# --- (1) the matrix, on the expansion itself --------------------------------------------------
for i, held in enumerate(CHAIN):
    expanded = security.expand_capabilities([held])
    for j, wanted in enumerate(CHAIN):
        covered = wanted in expanded
        assert covered == (j <= i), (held, wanted, expanded)

# --- (2) what is *not* in the chain ------------------------------------------------------------
# The chain covers exactly five capabilities; the rest are independent dimensions.
assert set(security.ALL_CAPABILITIES) - set(CHAIN) == {
    security.CREATE_API_KEY,
    security.ADD_PROJECT,
    security.CAN_ADMIN,
}, security.ALL_CAPABILITIES
publisher_caps = security.expand_capabilities([security.CAN_PUBLISH])
assert security.CREATE_API_KEY not in publisher_caps, publisher_caps
assert security.ADD_PROJECT not in publisher_caps, publisher_caps
assert security.CAN_ADMIN not in publisher_caps, publisher_caps
# ...and they imply nothing in the chain either: minting keys is not reading.
assert security.expand_capabilities([security.CREATE_API_KEY]) == {security.CREATE_API_KEY}
# can_admin remains the one blanket grant.
assert security.expand_capabilities([security.CAN_ADMIN]) == set(security.ALL_CAPABILITIES)
# Grants are not rewritten: expansion returns a view, the caller's list is untouched.
stored = [security.CAN_PUBLISH]
security.expand_capabilities(stored)
assert stored == [security.CAN_PUBLISH], stored


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


def make_key(user_id: int, name: str, scopes: list[str]) -> dict:
    """A key minted straight into the DB, so its scopes are exactly what the test says."""
    plaintext, key_hash, prefix = security.generate_api_key()
    with SessionLocal() as db:
        db.add(
            ApiKey(
                user_id=user_id,
                name=name,
                key_hash=key_hash,
                key_prefix=prefix,
                scopes=scopes,
            )
        )
        db.commit()
    return {"authorization": f"Bearer {plaintext}"}


with TestClient(app) as c:
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    c.headers["authorization"] = f"Bearer {tok['access_token']}"
    _raw_get = c.get
    # Every concept read takes a `project` param; the app-secret is empty here, so the value
    # is not validated but must be present.
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    def login(username: str) -> dict:
        r = c.post("/auth/login", json={"username": username, "password": "pw"})
        assert r.status_code == 200, r.text
        return {"authorization": f"Bearer {r.json()['access_token']}"}

    def get(url: str, headers: dict):
        return _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", headers=headers)

    # --- a concept with a snippet and a pinned data file ---------------------------------------
    up = c.post(
        "/sources/cub_hdp/files",
        data={"path": PATH},
        files={"file": ("table.csv", BYTES, "text/csv")},
    )
    assert up.status_code == 201, up.text
    file_uuid = up.json()["uuid"]
    CODE = f'def v(var, cohort):\n    return read_csv(getfile("{file_uuid}"))\n'
    assert c.post("/concepts", json={"name": "chain_var"}).status_code == 201
    draft = c.post(
        "/concept/corr_v1/chain_var/drafts",
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
              "json": ND, "py": CODE},
    ).json()
    assert c.post(
        f"/concept/corr_v1/chain_var/drafts/{draft['id']}/publish", json={}
    ).status_code == 200

    # One user per rung, each holding exactly one capability — nothing else is granted, so
    # every pass below is entailment doing the work.
    ids = {cap: make_user(cap, [cap]) for cap in CHAIN}
    h = {cap: login(cap) for cap in CHAIN}
    ids["create_api_key"] = make_user("keyminter", [security.CREATE_API_KEY])
    h["create_api_key"] = login("keyminter")

    # --- (3) the routes agree with the matrix --------------------------------------------------
    # can_read: everybody on the chain browses, including the publisher who was never granted it.
    for cap in CHAIN:
        assert get("/concept/corr_v1/chain_var", h[cap]).status_code == 200, cap
    # ...and the capability that is not on the chain does not get in.
    assert get("/concept/corr_v1/chain_var", h["create_api_key"]).status_code == 403

    # can_read_detail: withheld from the plain reader, entailed from can_edit up. `py_locked`
    # false for a can_edit-only user is the E1 gate that entailment simplified.
    for cap in CHAIN:
        block = get("/concept/corr_v1/chain_var", h[cap]).json()[0]["sources"]["cub_hdp"]
        locked = cap == security.CAN_READ
        assert block["py_locked"] is locked, (cap, block)
        assert (block["py"] is None) is locked, (cap, block)
    url = get("/concept/corr_v1/chain_var", h[security.CAN_EDIT]).json()[0]["sources"]["cub_hdp"][
        "files"
    ][0]["url"]
    assert get(url, h[security.CAN_READ]).status_code == 403
    assert get(url, h[security.CAN_EDIT]).content == BYTES

    # can_edit: the draft editor is reachable for a can_edit-only user, and for everyone above.
    drafts = {}
    for cap in (security.CAN_EDIT, security.CAN_PUBLISH):
        r = c.post(
            "/concept/corr_v1/chain_var/drafts",
            json={"source": "cub_hdp", "py": CODE + f"# {cap}\n"},
            headers=h[cap],
        )
        assert r.status_code == 201, (cap, r.text)
        # The draft comes back unlocked: an editor is never handed a snippet they may not read.
        assert r.json()["py"] and r.json()["py_locked"] is False, (cap, r.json())
        drafts[cap] = r.json()["id"]
    for cap in (security.CAN_READ, security.CAN_READ_DETAIL):
        assert c.post(
            "/concept/corr_v1/chain_var/drafts",
            json={"source": "cub_hdp", "py": CODE},
            headers=h[cap],
        ).status_code == 403, cap

    # can_publish: the top of the chain, entailed by nothing below it. Reviewing is this
    # capability — there is no separate watcher — so the queue opens here and nowhere lower.
    assert _raw_get("/drafts", headers=h[security.CAN_PUBLISH]).status_code == 200
    assert _raw_get(
        "/deprecation-requests", headers=h[security.CAN_PUBLISH]
    ).status_code == 200
    for cap in (security.CAN_READ, security.CAN_READ_DETAIL, security.CAN_EDIT):
        assert _raw_get("/drafts", headers=h[cap]).status_code == 403, cap
        assert _raw_get("/deprecation-requests", headers=h[cap]).status_code == 403, cap
    assert c.post(
        f"/concept/corr_v1/chain_var/drafts/{drafts[security.CAN_EDIT]}/publish",
        json={},
        headers=h[security.CAN_EDIT],
    ).status_code == 403
    assert c.post(
        f"/concept/corr_v1/chain_var/drafts/{drafts[security.CAN_PUBLISH]}/publish",
        json={},
        headers=h[security.CAN_PUBLISH],
    ).status_code == 200

    # The separate dimensions, over HTTP: a publisher mints no keys and creates no projects,
    # and the key-minter reads nothing.
    assert c.post(
        "/api-keys", json={"name": "nope"}, headers=h[security.CAN_PUBLISH]
    ).status_code == 403
    assert c.post(
        "/projects", json={"name": "nope"}, headers=h[security.CAN_PUBLISH]
    ).status_code == 403
    assert c.post(
        "/api-keys", json={"name": "fine"}, headers=h["create_api_key"]
    ).status_code == 201

    # --- (4) API keys: entailment on both sides, and scopes still narrow -----------------------
    pub_id = ids[security.CAN_PUBLISH]
    # scoped to the owner's own capability: reads code it was never explicitly scoped for
    key_pub = make_key(pub_id, "publisher-key", [security.CAN_PUBLISH])
    assert get(url, key_pub).content == BYTES
    assert get("/concept/corr_v1/chain_var", key_pub).json()[0]["sources"]["cub_hdp"][
        "py_locked"
    ] is False
    # scoped down to plain reading: still a reader, however much its owner holds
    key_read = make_key(pub_id, "reader-key", [security.CAN_READ])
    assert get(url, key_read).status_code == 403
    assert get("/concept/corr_v1/chain_var", key_read).json()[0]["sources"]["cub_hdp"][
        "py_locked"
    ] is True
    assert _raw_get("/drafts", headers=key_read).status_code == 403
    # a key scoped *above* its owner is bounded by the owner, not widened by the scope
    key_over = make_key(ids[security.CAN_READ], "over-scoped", [security.CAN_PUBLISH])
    assert get("/concept/corr_v1/chain_var", key_over).status_code == 200
    assert get(url, key_over).status_code == 403
    assert c.post(
        "/concept/corr_v1/chain_var/drafts", json={"source": "cub_hdp"}, headers=key_over
    ).status_code == 403

    # --- the default scopes a non-admin gets when minting a key --------------------------------
    # One scope says it all now: `can_read_detail` entails `can_read`, so a key for an owner
    # who may read code is minted at detail and nothing wider.
    minter_detail = make_user("minter_detail", [security.CREATE_API_KEY, security.CAN_EDIT])
    assert minter_detail
    r = c.post("/api-keys", json={"name": "auto"}, headers=login("minter_detail"))
    assert r.status_code == 201 and r.json()["scopes"] == [security.CAN_READ_DETAIL], r.text
    make_user("minter_read", [security.CREATE_API_KEY, security.CAN_READ])
    r = c.post("/api-keys", json={"name": "auto"}, headers=login("minter_read"))
    assert r.status_code == 201 and r.json()["scopes"] == [security.CAN_READ], r.text

    # --- (5) the retired `can_review`, cleared out of an older database ------------------------
    assert "can_review" not in security.ALL_CAPABILITIES, security.ALL_CAPABILITIES
    # A row and a key written while the capability existed. The key is on the reader, so the
    # stripping is visible on the scope list rather than masked by the owner's caps.
    stale_id = make_user("stale", ["can_read", "can_review"])
    stale_key = make_key(ids[security.CAN_READ], "stale-key", ["can_read", "can_review"])
    assert get("/concept/corr_v1/chain_var", stale_key).status_code == 200

    _drop_can_review()

    with SessionLocal() as db:
        assert db.get(User, stale_id).capabilities == ["can_read"], "user scrubbed"
        rows = {k.name: list(k.scopes or []) for k in db.scalars(select(ApiKey))}
        assert rows["stale-key"] == ["can_read"], rows
    # Nothing was granted in exchange: the queue is closed to them, as decided.
    assert _raw_get("/drafts", headers=login("stale")).status_code == 403
    # The key still authenticates on what it legitimately held.
    assert get("/concept/corr_v1/chain_var", stale_key).status_code == 200

    # Idempotent: with the string gone there is nothing left to match.
    _drop_can_review()
    _drop_can_review()
    with SessionLocal() as db:
        assert db.get(User, stale_id).capabilities == ["can_read"], "still scrubbed"

print("CAPABILITY CHAIN SMOKE OK")
