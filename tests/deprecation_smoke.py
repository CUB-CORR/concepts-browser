"""Retiring a duplicate concept: request, review, and what a retired concept still does.

Run: uv run python tests/deprecation_smoke.py

The split is the point — an editor may ask, only a publisher may decide — so most of this is
about who is allowed to do what, and about what survives the decision: the names still resolve,
the version history is untouched, `successor_id` points readers at the replacement (through a
chain, if one formed), and no new versions can be started.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "deprecation.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["APP_SHARED_SECRET"] = ""  # app mode: the project gate is off for this test
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

ND = {"type": "native_dynamic", "table_name": "diagnoses"}


def nd(where: str) -> dict:
    return {**ND, "where_clause": where}


with TestClient(app) as c:
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    admin_h = {"authorization": f"Bearer {tok['access_token']}"}
    c.headers["authorization"] = admin_h["authorization"]
    _raw_get = c.get
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    with SessionLocal() as db:
        db.add_all(
            [
                User(username="editor", password_hash=security.hash_password("pw"),
                     capabilities=["can_read", "can_edit"], is_active=True),
                User(username="publisher", password_hash=security.hash_password("pw"),
                     capabilities=["can_read", "can_edit", "can_publish"], is_active=True),
            ]
        )
        db.commit()

    def login(username: str) -> dict:
        r = c.post("/auth/login", json={"username": username, "password": "pw"})
        assert r.status_code == 200, r.text
        return {"authorization": f"Bearer {r.json()['access_token']}"}

    editor_h = login("editor")
    publisher_h = login("publisher")

    def concept(name: str) -> int:
        r = c.post("/concepts", json={"name": name}, headers=admin_h)
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def publish(concept_id: int, definition: dict) -> int:
        r = c.post(
            f"/concept/id/{concept_id}/drafts", headers=admin_h,
            json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
                  "json": definition},
        )
        assert r.status_code == 201, r.text
        r = c.post(
            f"/concept/id/{concept_id}/drafts/{r.json()['id']}/publish",
            headers=admin_h, json={},
        )
        assert r.status_code == 200, r.text
        return r.json()["version_no"]

    aki = concept("aki")
    akin = concept("akin")
    kdigo = concept("kdigo_aki")
    publish(aki, nd("code LIKE 'N17%'"))
    publish(akin, nd("code LIKE 'N17%'"))
    publish(kdigo, nd("code LIKE 'N17%'"))

    # --- the gates ------------------------------------------------------------------------------
    assert c.get("/deprecation-requests", headers=editor_h).status_code == 403
    assert c.post(
        f"/concept/id/{akin}/deprecation-request", headers=editor_h,
        json={"reason": "duplicate of aki", "successor_id": aki},
    ).status_code == 201
    # …an editor asks, and cannot then decide their own request
    open_requests = c.get("/deprecation-requests?status=pending", headers=publisher_h).json()
    assert len(open_requests) == 1, open_requests
    request_id = open_requests[0]["id"]
    assert open_requests[0]["requested_by"] == "editor", open_requests[0]
    assert open_requests[0]["concept"]["name"] == "akin", open_requests[0]
    assert open_requests[0]["successor"]["name"] == "aki", open_requests[0]
    assert c.post(f"/deprecation-requests/{request_id}/approve",
                  headers=editor_h, json={}).status_code == 403
    assert c.post(f"/deprecation-requests/{request_id}/reject",
                  headers=editor_h, json={}).status_code == 403

    # One open request at a time, and nothing to ask about a concept that isn't there.
    assert c.post(
        f"/concept/id/{akin}/deprecation-request", headers=editor_h, json={"reason": "again"}
    ).status_code == 409
    assert c.post(
        "/concept/id/9999/deprecation-request", headers=editor_h, json={"reason": "x"}
    ).status_code == 404
    assert c.post(
        f"/concept/id/{akin}/deprecation-request", headers=editor_h,
        json={"reason": "x", "successor_id": akin},
    ).status_code in (400, 409)

    # --- rejection leaves the concept alone -------------------------------------------------------
    r = c.post(f"/deprecation-requests/{request_id}/reject", headers=publisher_h, json={})
    assert r.status_code == 200 and r.json()["status"] == "rejected", r.text
    assert r.json()["resolved_by"] == "publisher", r.json()
    assert c.get(f"/concept/id/{akin}").json()["deprecated_at"] is None
    # …and a decision is made once
    assert c.post(f"/deprecation-requests/{request_id}/reject",
                  headers=publisher_h, json={}).status_code == 409
    assert c.post("/deprecation-requests/9999/approve",
                  headers=publisher_h, json={}).status_code == 404

    # --- approval retires the concept ---------------------------------------------------------------
    r = c.post(
        f"/concept/id/{akin}/deprecation-request", headers=editor_h,
        json={"reason": "duplicate of aki", "successor_id": aki},
    )
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]
    r = c.post(f"/deprecation-requests/{request_id}/approve", headers=publisher_h, json={})
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text

    retired = c.get(f"/concept/id/{akin}").json()
    assert retired["deprecated_at"] is not None, retired
    assert retired["successor_id"] == aki, retired
    # Its names still resolve and its history is exactly where it was — deprecation retires an
    # identity, it does not rewrite anything.
    by_name = c.get("/concept/corr_v1/akin").json()
    assert [m["id"] for m in by_name] == [akin] and by_name[0]["version"] == 1, by_name
    assert [h["version"] for h in c.get(f"/concept/id/{akin}/history").json()] == [1]
    listed = {x["name"]: x for x in c.get("/concepts").json()}
    assert listed["akin"]["concept_deprecated_at"] is not None, listed["akin"]
    assert listed["akin"]["successor_id"] == aki, listed["akin"]

    # No new versions on a retired concept, by either address.
    for url in (f"/concept/id/{akin}/drafts", "/concept/corr_v1/akin/drafts"):
        r = c.post(url, headers=admin_h,
                   json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
                         "json": nd("code LIKE 'N18%'")})
        assert r.status_code == 409 and "deprecated" in r.json()["detail"], (url, r.text)

    # …and the orphan guard steps aside once the concept is retired: its last name may go.
    pointer_id = retired["names"][0]["id"]
    r = c.post(f"/concept/id/{akin}/pointers/{pointer_id}/deprecate", headers=admin_h, json={})
    assert r.status_code == 200, r.text
    assert c.get("/concept/corr_v1/akin").json()[0]["id"] == akin  # still resolves, flagged

    # --- a chain -------------------------------------------------------------------------------------
    # `aki` is later retired in favour of `kdigo_aki`; anybody following akin's successor wants
    # where the chain ends, not the next hop.
    r = c.post(
        f"/concept/id/{aki}/deprecation-request", headers=editor_h,
        json={"reason": "superseded", "successor_id": kdigo},
    )
    assert r.status_code == 201, r.text
    assert c.post(
        f"/deprecation-requests/{r.json()['id']}/approve", headers=publisher_h, json={}
    ).status_code == 200
    assert c.get(f"/concept/id/{akin}").json()["successor_id"] == kdigo
    assert c.get(f"/concept/id/{aki}").json()["successor_id"] == kdigo
    assert c.get(f"/concept/id/{kdigo}").json()["successor_id"] is None

    # --- a name the concept can spare -------------------------------------------------------------
    # An alias is a second pointer at one concept — the app's "Alias" tab is exactly this POST.
    # Retiring it must cost the alias and nothing else: the definition behind it, its history and
    # the name everybody else uses were never what the request was about.
    sodium = concept("blood_sodium")
    publish(sodium, nd("code LIKE 'E87%'"))
    r = c.post(f"/concept/id/{sodium}/pointers", headers=admin_h, json={"identifier": "test_2"})
    assert r.status_code == 201, r.text
    alias_pointer = r.json()["id"]

    # A request names one of *this* concept's names, or none at all.
    assert c.post(
        f"/concept/id/{sodium}/deprecation-request", headers=editor_h,
        json={"reason": "x", "pointer_id": 999999},
    ).status_code == 404
    assert c.post(
        f"/concept/id/{kdigo}/deprecation-request", headers=editor_h,
        json={"reason": "x", "pointer_id": alias_pointer},
    ).status_code == 404

    r = c.post(
        f"/concept/id/{sodium}/deprecation-request", headers=editor_h,
        json={"reason": "alias added by mistake", "pointer_id": alias_pointer,
              "successor_id": kdigo},
    )
    assert r.status_code == 201, r.text
    alias_req = r.json()["id"]
    assert r.json()["pointer"]["name"] == "test_2", r.json()
    assert r.json()["retires"] == "name", r.json()

    r = c.post(f"/deprecation-requests/{alias_req}/approve", headers=publisher_h, json={})
    assert r.status_code == 200, r.text
    assert r.json()["retires"] == "name", r.json()

    # The concept is exactly where it was: live, unsuperseded, and still taking new versions.
    after = c.get(f"/concept/id/{sodium}").json()
    assert after["deprecated_at"] is None, after
    assert after["successor_id"] is None, after
    assert publish(sodium, nd("code LIKE 'E87.1%'")) == 2

    # Only the alias's window closed; the original name still resolves and still lists.
    names = {n["identifier"]: n for n in after["names"]}
    assert names["test_2"]["deprecated_at"] is not None, names
    assert names["blood_sodium"]["deprecated_at"] is None, names
    assert [m["id"] for m in c.get("/concept/corr_v1/blood_sodium").json()] == [sodium]
    listed = {x["name"]: x for x in c.get("/concepts").json()}
    assert "blood_sodium" in listed and listed["blood_sodium"]["concept_deprecated_at"] is None
    # …and a name that is already retired cannot be asked for again.
    assert c.post(
        f"/concept/id/{sodium}/deprecation-request", headers=editor_h,
        json={"reason": "x", "pointer_id": alias_pointer},
    ).status_code == 409

    # --- …and the last name takes the concept with it ---------------------------------------------
    r = c.post(
        f"/concept/id/{sodium}/deprecation-request", headers=editor_h,
        json={"reason": "duplicate", "pointer_id": names["blood_sodium"]["id"],
              "successor_id": kdigo},
    )
    assert r.status_code == 201 and r.json()["retires"] == "concept", r.text
    r = c.post(f"/deprecation-requests/{r.json()['id']}/approve", headers=publisher_h, json={})
    assert r.status_code == 200 and r.json()["retires"] == "concept", r.text
    gone = c.get(f"/concept/id/{sodium}").json()
    assert gone["deprecated_at"] is not None, gone
    assert gone["successor_id"] == kdigo, gone
    # Retiring the concept still leaves its names alone — they keep resolving, as they always did.
    assert {n["identifier"]: n["deprecated_at"] for n in gone["names"]}["blood_sodium"] is None
    assert [m["id"] for m in c.get("/concept/corr_v1/blood_sodium").json()] == [sodium]

    # --- the queue ------------------------------------------------------------------------------------
    everything = c.get("/deprecation-requests", headers=publisher_h).json()
    assert [r["status"] for r in everything] == [
        "approved", "approved", "approved", "approved", "rejected"
    ], everything
    assert len(c.get("/deprecation-requests?status=pending", headers=publisher_h).json()) == 0
    assert len(c.get("/deprecation-requests?status=approved", headers=publisher_h).json()) == 4
    # A request written before names were addressable carries no pointer and means the concept.
    assert [r["retires"] for r in everything if r["pointer"] is None] == ["concept"] * 3

print("DEPRECATION SMOKE OK")
