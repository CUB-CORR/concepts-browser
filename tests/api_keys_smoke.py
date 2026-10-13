"""API-key smoke test. Run: uv run python tests/api_keys_smoke.py

Exercises minting keys, using them as bearer tokens (scoped by capability), live scope
narrowing against the owner's caps, last-used stamping, revocation, expiry, and the
create-time scope guard — all for real against a temp SQLite DB.
"""
import os
import sys
import tempfile
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "keys.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import security  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import ApiKey, User, _utcnow  # noqa: E402


def _login(client, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"authorization": f"Bearer {r.json()['access_token']}"}


with TestClient(app) as client:
    # A limited local user: can read + mint keys, but cannot edit.
    with SessionLocal() as db:
        db.add(
            User(
                username="reader",
                password_hash=security.hash_password("pw"),
                display_name="Reader",
                capabilities=["can_read", "create_api_key"],
                is_active=True,
            )
        )
        db.commit()

    admin_h = _login(client, "admin", "admin")
    reader_h = _login(client, "reader", "pw")

    # --- mint a read-only key as the reader --------------------------------------------------
    r = client.post(
        "/api-keys", headers=reader_h,
        json={"name": "ci", "scopes": ["can_read"], "expires_in_days": 30},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["key"].startswith("cak_"), created
    assert created["key_prefix"] == created["key"][:12], created
    assert created["scopes"] == ["can_read"] and created["expires_at"] is not None, created
    assert created["last_used_at"] is None, created
    key = created["key"]
    key_h = {"authorization": f"Bearer {key}"}

    # the secret is never echoed again by the list endpoint
    listed = client.get("/api-keys", headers=reader_h).json()
    assert len(listed) == 1 and "key" not in listed[0], listed

    # --- use the key as a bearer token: read works, edit is out of scope --------------------
    assert client.get(
        "/concepts", headers=key_h, params={"project": "internal"}
    ).status_code == 200
    # reader has no can_edit anyway, but even an admin-owned read-scoped key must 403 here:
    assert client.post("/concepts", json={"name": "x"}, headers=key_h).status_code == 403

    # using the key stamped last_used_at
    listed = client.get("/api-keys", headers=reader_h).json()
    assert listed[0]["last_used_at"] is not None, listed

    # --- a write-scoped key can create (exercises the detached-owner path: created_by=id) ---
    r = client.post(
        "/api-keys", headers=admin_h,
        json={"name": "writer", "scopes": ["can_read", "can_edit"]},
    )
    assert r.status_code == 201, r.text
    writer_key_h = {"authorization": f"Bearer {r.json()['key']}"}
    r = client.post("/concepts", json={"name": "key_made_concept"}, headers=writer_key_h)
    assert r.status_code == 201, r.text  # would 500 if the owner were detached+expired

    # --- scope narrowing is live: an admin's key is still bounded by its scopes -------------
    r = client.post(
        "/api-keys", headers=admin_h, json={"name": "admin-read", "scopes": ["can_read"]}
    )
    assert r.status_code == 201, r.text
    admin_key_h = {"authorization": f"Bearer {r.json()['key']}"}
    assert client.get(
        "/concepts", headers=admin_key_h, params={"project": "internal"}
    ).status_code == 200
    # scoped to read only → cannot reach the admin API despite an admin owner
    assert client.get("/admin/users", headers=admin_key_h).status_code == 403

    # --- non-admins can't scope: keys are forced read-only, whatever they request -----------
    r = client.post(
        "/api-keys", headers=reader_h,
        json={"name": "forced", "scopes": ["can_edit", "create_api_key"]},
    )
    assert r.status_code == 201 and r.json()["scopes"] == ["can_read"], r.text
    # unknown capability is still a schema error
    assert client.post(
        "/api-keys", headers=reader_h, json={"name": "bad", "scopes": ["can_fly"]}
    ).status_code == 422

    # --- create_api_key is never a scope, even for admins -----------------------------------
    r = client.post(
        "/api-keys", headers=admin_h,
        json={"name": "no-keymint", "scopes": ["can_read", "create_api_key"]},
    )
    assert r.status_code == 201 and r.json()["scopes"] == ["can_read"], r.text

    # --- revocation takes effect immediately ------------------------------------------------
    key_id = listed[0]["id"]
    assert client.delete(f"/api-keys/{key_id}", headers=reader_h).status_code == 204
    assert client.get(
        "/concepts", headers=key_h, params={"project": "internal"}
    ).status_code == 401
    # can't revoke someone else's key (scoped to the owner)
    assert client.delete(f"/api-keys/{key_id}", headers=admin_h).status_code == 404

    # --- expired keys are rejected ----------------------------------------------------------
    plaintext, key_hash, prefix = security.generate_api_key()
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == "reader"))
        db.add(
            ApiKey(
                user_id=uid,
                name="stale",
                key_hash=key_hash,
                key_prefix=prefix,
                scopes=["can_read"],
                expires_at=_utcnow() - timedelta(days=1),
            )
        )
        db.commit()
    assert client.get(
        "/concepts", headers={"authorization": f"Bearer {plaintext}"},
        params={"project": "internal"},
    ).status_code == 401

    # --- admins see and manage another user's keys -----------------------------------------
    with SessionLocal() as db:
        reader_id = db.scalar(select(User.id).where(User.username == "reader"))
    keys_url = f"/admin/users/{reader_id}/api-keys"
    assert client.get(keys_url, headers=reader_h).status_code == 403
    listed = client.get(keys_url, headers=admin_h).json()
    assert {k["name"] for k in listed} == {"ci", "forced", "stale"}, listed
    forced = next(k for k in listed if k["name"] == "forced")
    assert forced["scopes"] == ["can_read"] and not forced["scopes_pinned"], forced

    # a second unpinned key, then one an admin pins at can_read
    r = client.post("/api-keys", headers=reader_h, json={"name": "pinned"})
    pinned_id = r.json()["id"]
    r = client.patch(f"{keys_url}/{pinned_id}", headers=admin_h, json={"scopes": ["can_read"]})
    assert r.status_code == 200 and r.json()["scopes_pinned"], r.text
    # scopes stay bounded by the owner, and the body must say what it means
    assert client.patch(
        f"{keys_url}/{pinned_id}", headers=admin_h, json={"scopes": ["can_edit"]}
    ).status_code == 400
    assert client.patch(f"{keys_url}/{pinned_id}", headers=admin_h, json={}).status_code == 422
    # a key of somebody else is not reachable through this user's URL
    admin_key_id = next(
        k["id"] for k in client.get("/api-keys", headers=admin_h).json() if k["name"] == "writer"
    )
    assert client.patch(
        f"{keys_url}/{admin_key_id}", headers=admin_h, json={"scopes": None}
    ).status_code == 404

    # --- promoting the owner raises their unpinned keys, never the pinned ones --------------
    r = client.patch(
        f"/admin/users/{reader_id}", headers=admin_h,
        json={"capabilities": ["can_edit", "create_api_key"]},
    )
    assert r.status_code == 200, r.text
    by_name = {k["name"]: k for k in client.get(keys_url, headers=admin_h).json()}
    assert by_name["forced"]["scopes"] == ["can_read_detail"], by_name
    assert by_name["pinned"]["scopes"] == ["can_read"], by_name
    assert by_name["ci"]["scopes"] == ["can_read"], by_name  # revoked: left alone
    # new keys follow suit
    r = client.post("/api-keys", headers=reader_h, json={"name": "after"})
    assert r.json()["scopes"] == ["can_read_detail"] and not r.json()["scopes_pinned"], r.text

    # resetting a pinned key hands it back to the owner default
    r = client.patch(f"{keys_url}/{pinned_id}", headers=admin_h, json={"scopes": None})
    assert r.json()["scopes"] == ["can_read_detail"] and not r.json()["scopes_pinned"], r.text

    # --- the boot pass raises keys stuck from before promotions raised them -----------------
    from api.main import _raise_unpinned_keys  # noqa: E402

    with SessionLocal() as db:
        k = db.get(ApiKey, forced["id"])
        k.scopes = ["can_read"]
        db.commit()
    _raise_unpinned_keys()
    _raise_unpinned_keys()  # idempotent
    with SessionLocal() as db:
        assert db.get(ApiKey, forced["id"]).scopes == ["can_read_detail"]

    # --- admin revoke ------------------------------------------------------------------------
    assert client.delete(f"{keys_url}/{pinned_id}", headers=admin_h).status_code == 204
    assert client.patch(
        f"{keys_url}/{pinned_id}", headers=admin_h, json={"scopes": None}
    ).status_code == 409

    # --- deactivating the owner disables their keys immediately -----------------------------
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == "reader"))
        u.is_active = False
        db.commit()
    assert client.get(
        "/concepts", headers=admin_key_h, params={"project": "internal"}
    ).status_code == 200  # admin's key (different owner) still fine

print("API KEYS SMOKE OK")
