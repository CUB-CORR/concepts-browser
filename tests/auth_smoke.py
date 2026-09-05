"""LDAP-provisioning + admin user-management smoke test. Run: uv run python tests/auth_smoke.py

The real LDAP bind only works from the deployment host, so `ldap_auth.authenticate` is
monkeypatched to return a controlled identity; everything downstream of it (upsert by stable
guid, empty-cap provisioning, live authz, admin capability grants, deactivation) is exercised
for real against a temp SQLite DB.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "auth.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
# Keep the external project gate off (don't inherit a developer's .env APP_SHARED_SECRET).
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from api import ldap_auth  # noqa: E402
from api.main import app  # noqa: E402

# --- unit: empty credentials never authenticate (unauthenticated-bind guard) -------------
assert ldap_auth.authenticate("someone", "") is None
assert ldap_auth.authenticate("", "pw") is None

# --- monkeypatch the directory bind: uid -> (guid, display_name, profile) -----------------
_PROFILE = {"displayName": ["Doe, Jane"], "mail": ["jane.doe@example.org"]}
_DIRECTORY = {"doej": ("GUID-abc==", "Doe, Jane", _PROFILE)}
# A person who exists in the directory but has NEVER logged in — the proactive-provisioning
# target. Kept separate from `_DIRECTORY` (which the rename scenario later clears).
_DIR_ONLY = {"muellera": ("GUID-xyz==", "Müller, Anna", {"mail": ["anna.mueller@example.org"]})}


def _fake_authenticate(username, password):
    if password != "correct-horse":
        return None
    hit = _DIRECTORY.get(username)
    if hit is None:
        return None
    guid, display, profile = hit
    return ldap_auth.LdapIdentity(
        guid=guid, uid=username, display_name=display, profile=profile
    )


def _all_directory():
    return {**_DIRECTORY, **_DIR_ONLY}


def _fake_search_directory(query, limit=None):
    q = query.strip().lower()
    return [
        ldap_auth.LdapIdentity(guid=g, uid=u, display_name=d, profile=p)
        for u, (g, d, p) in _all_directory().items()
        if q in u.lower() or q in (d or "").lower()
    ]


def _fake_resolve(username):
    hit = _all_directory().get(username.strip())
    if hit is None:
        return None
    guid, display, profile = hit
    return ldap_auth.LdapIdentity(guid=guid, uid=username, display_name=display, profile=profile)


ldap_auth.authenticate = _fake_authenticate
ldap_auth.search_directory = _fake_search_directory
ldap_auth.resolve = _fake_resolve

with TestClient(app) as client:
    # local bootstrap admin still works (unchanged path)
    r = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    admin_h = {"authorization": f"Bearer {r.json()['access_token']}"}

    # wrong LDAP password -> 401
    assert client.post(
        "/auth/login", json={"username": "doej", "password": "nope"}
    ).status_code == 401

    # --- first LDAP login: provisioned with EMPTY caps, but a token is issued -------------
    r = client.post("/auth/login", json={"username": "doej", "password": "correct-horse"})
    assert r.status_code == 200, r.text
    user_h = {"authorization": f"Bearer {r.json()['access_token']}"}
    me = client.get("/auth/me", headers=user_h).json()
    assert me["capabilities"] == [], me  # pending approval
    assert me["display_name"] == "Doe, Jane", me

    # --- profile: a user sees their own (with the full LDAP snapshot) ----------------------
    prof = client.get("/auth/users/doej/profile", headers=user_h)
    assert prof.status_code == 200, prof.text
    assert prof.json()["ldap_profile"] == _PROFILE, prof.json()
    assert prof.json()["is_ldap"] is True, prof.json()
    # but not someone else's, and admins may view anyone's
    assert client.get("/auth/users/admin/profile", headers=user_h).status_code == 403
    assert client.get("/auth/users/doej/profile", headers=admin_h).status_code == 200
    assert client.get("/auth/users/nope/profile", headers=admin_h).status_code == 404

    # a capability-gated endpoint is forbidden while pending
    assert client.post("/concepts", json={"name": "x"}, headers=user_h).status_code == 403
    # and the admin API is closed to them
    assert client.get("/admin/users", headers=user_h).status_code == 403

    # --- admin sees the pending user (first, since empty-cap) and grants can_edit ---------
    users = client.get("/admin/users", headers=admin_h).json()
    pending = next(u for u in users if u["username"] == "doej")
    assert pending["capabilities"] == [] and pending["is_ldap"] is True, pending
    assert users[0]["username"] == "doej", "pending users should sort first"

    r = client.patch(
        f"/admin/users/{pending['id']}", headers=admin_h, json={"capabilities": ["can_edit"]}
    )
    assert r.status_code == 200 and r.json()["capabilities"] == ["can_edit"], r.text
    # unknown capability rejected
    assert client.patch(
        f"/admin/users/{pending['id']}", headers=admin_h, json={"capabilities": ["can_fly"]}
    ).status_code == 422

    # --- authz is live: the SAME (pre-grant) token now passes, no re-login ----------------
    assert client.post(
        "/concepts", json={"name": "granted_concept"}, headers=user_h
    ).status_code == 201

    # --- the chain: `can_edit` alone already reads, no second grant needed ----------------
    # Capabilities are incremental (api/security.CAPABILITY_CHAIN): an editor can read what
    # they edit. The grant above was `can_edit` and nothing else.
    assert client.get(
        "/concepts", headers=user_h, params={"project": "internal"}
    ).status_code == 200  # live, same token
    # It does not run the other way — a plain reader still cannot write.
    assert client.patch(
        f"/admin/users/{pending['id']}", headers=admin_h, json={"capabilities": ["can_read"]}
    ).status_code == 200
    assert client.post(
        "/concepts", json={"name": "refused_concept"}, headers=user_h
    ).status_code == 403
    assert client.patch(
        f"/admin/users/{pending['id']}", headers=admin_h, json={"capabilities": ["can_edit"]}
    ).status_code == 200

    # --- documentation caps split: texts need can_edit, doc_status needs can_publish ------
    doc_url = "/concept/corr_v1/granted_concept/documentation"
    # can_edit: prose edits pass, a status flip does not
    assert client.patch(doc_url, headers=user_h, json={"doc_clinical": "x"}).status_code == 200
    assert client.patch(doc_url, headers=user_h, json={"doc_status": "Done"}).status_code == 403
    # can_publish: the status flip passes, and so do the texts — publishing entails editing.
    # The split is a floor on each field, not two separate lanes.
    assert client.patch(
        f"/admin/users/{pending['id']}", headers=admin_h,
        json={"capabilities": ["can_publish"]},
    ).status_code == 200
    assert client.patch(doc_url, headers=user_h, json={"doc_clinical": "y"}).status_code == 200
    assert client.patch(doc_url, headers=user_h, json={"doc_status": "Done"}).status_code == 200
    # restore for the rest of the test
    assert client.patch(
        f"/admin/users/{pending['id']}", headers=admin_h,
        json={"capabilities": ["can_edit"]},
    ).status_code == 200
    # mixing a text field with the status still needs both capabilities
    assert client.patch(
        doc_url, headers=user_h, json={"doc_caveats": "careful", "doc_status": "Done"}
    ).status_code == 403
    # the study context is not part of this endpoint any more — it belongs to the project
    # (tests/projects_smoke.py). Unknown keys are dropped by the schema, so a body of only
    # those sets nothing and is refused rather than silently accepted.
    assert client.patch(
        doc_url, headers=user_h, json={"pico_population": "adults", "study_team": "A. Beispiel"}
    ).status_code == 400
    # anonymous cannot touch the endpoint at all
    assert client.patch(doc_url, json={"doc_clinical": "x"}).status_code in (401, 403)

    # --- proactive provisioning: admin adds a user who has NEVER logged in ----------------
    # directory search finds both people; the already-provisioned one carries its user_id.
    hits = client.get("/admin/directory", headers=admin_h, params={"q": "e"}).json()
    by_uid = {h["username"]: h for h in hits}
    assert "muellera" in by_uid and by_uid["muellera"]["user_id"] is None, hits
    assert by_uid["doej"]["user_id"] == pending["id"], hits  # existing, flagged
    # non-admins can't search the directory
    assert client.get("/admin/directory", headers=user_h, params={"q": "e"}).status_code == 403

    # add the never-logged-in user with capabilities up front
    r = client.post(
        "/admin/users", headers=admin_h,
        json={"username": "muellera", "capabilities": ["can_read", "can_edit"]},
    )
    assert r.status_code == 201, r.text
    added = r.json()
    assert added["is_ldap"] is True and added["capabilities"] == ["can_edit", "can_read"], added
    assert added["display_name"] == "Müller, Anna", added
    # they now show up in the user list, pre-approved
    listed = {u["username"]: u for u in client.get("/admin/users", headers=admin_h).json()}
    assert listed["muellera"]["capabilities"] == ["can_edit", "can_read"], listed

    # provisioning the same uid again conflicts (idempotency guard)
    assert client.post(
        "/admin/users", headers=admin_h, json={"username": "muellera"}
    ).status_code == 409
    # unknown uid → 404; unknown capability → 422
    assert client.post(
        "/admin/users", headers=admin_h, json={"username": "ghost"}
    ).status_code == 404
    assert client.post(
        "/admin/users", headers=admin_h, json={"username": "muellera", "capabilities": ["can_fly"]}
    ).status_code == 422

    # the proactively-added user can log in later and lands on their granted caps (same guid)
    _DIRECTORY["muellera"] = _DIR_ONLY["muellera"]  # they now authenticate too
    r = client.post("/auth/login", json={"username": "muellera", "password": "correct-horse"})
    assert r.status_code == 200, r.text
    mueller_h = {"authorization": f"Bearer {r.json()['access_token']}"}
    assert set(client.get("/auth/me", headers=mueller_h).json()["capabilities"]) == {
        "can_read", "can_edit"
    }
    del _DIRECTORY["muellera"]

    # --- stable-id: re-login as same guid with a renamed uid maps to the same row ---------
    _DIRECTORY.clear()
    _DIRECTORY["doej2"] = ("GUID-abc==", "Doe, Jane", _PROFILE)  # same guid, new uid
    r = client.post("/auth/login", json={"username": "doej2", "password": "correct-horse"})
    assert r.status_code == 200, r.text
    users = client.get("/admin/users", headers=admin_h).json()
    # doej's original row is refreshed in place — no duplicate for its guid.
    renamed = [u for u in users if u["username"] in ("doej", "doej2")]
    assert len(renamed) == 1, renamed  # no duplicate
    assert renamed[0]["username"] == "doej2"  # label refreshed
    assert renamed[0]["capabilities"] == ["can_edit"]  # permissions intact

    # --- deactivation locks out on the next request ---------------------------------------
    uid = renamed[0]["id"]
    assert client.patch(
        f"/admin/users/{uid}", headers=admin_h, json={"is_active": False}
    ).status_code == 200
    # existing token now rejected
    assert client.get("/auth/me", headers=user_h).status_code == 401
    # and a fresh login is refused (403 disabled) even with valid LDAP creds
    assert client.post(
        "/auth/login", json={"username": "doej2", "password": "correct-horse"}
    ).status_code == 403

    # --- self-lockout guards --------------------------------------------------------------
    me_admin = client.get("/auth/me", headers=admin_h).json()
    assert client.patch(
        f"/admin/users/{me_admin['id']}", headers=admin_h, json={"is_active": False}
    ).status_code == 400
    assert client.patch(
        f"/admin/users/{me_admin['id']}", headers=admin_h, json={"capabilities": ["can_edit"]}
    ).status_code == 400  # would drop own admin

print("AUTH SMOKE OK")
