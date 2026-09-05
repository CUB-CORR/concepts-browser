"""The review queues: open drafts and deprecation requests, across all concepts.

Run: uv run python tests/review_smoke.py

Two things are being checked. The gate — `can_publish` sees both queues, because reviewing is
deciding and there is no separate capability for watching; `can_edit` alone sees neither. And the listing — every open draft shows up regardless of which concept it is on,
carrying enough to link back to it (taxonomy + name + concept id, which is what pins the right
member when the name names a group), and it leaves the queue the moment it is published.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "review.db")
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
from sqlalchemy import select  # noqa: E402

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

    def concept(name: str, confirm_group: bool = False) -> int:
        r = c.post(
            "/concepts",
            json={"name": name, "confirm_group": confirm_group},
            headers=admin_h,
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def draft(concept_id: int, definition: dict, headers: dict, **extra) -> int:
        r = c.post(
            f"/concept/id/{concept_id}/drafts", headers=headers,
            json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
                  "json": definition, **extra},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    # --- the gate --------------------------------------------------------------------------
    # Nothing open yet, but who may look is already decided.
    assert c.get("/drafts", headers=editor_h).status_code == 403
    assert c.get("/deprecation-requests", headers=editor_h).status_code == 403
    for h in (publisher_h, admin_h):
        assert c.get("/drafts", headers=h).status_code == 200
        assert c.get("/deprecation-requests", headers=h).status_code == 200
    assert c.get("/drafts", headers=publisher_h).json() == []
    # …and an anonymous caller gets nowhere.
    assert _raw_get("/drafts", headers={"authorization": "Bearer nonsense"}).status_code == 401

    # --- drafts across concepts, one of them a group member ----------------------------------
    aki = concept("aki")
    # "atc_j01" names two concepts; a draft on the second member has to stay distinguishable
    # from a draft on the first, which is what `concept_id` on the row is for.
    amox = concept("atc_j01")
    ampi = concept("atc_j01", confirm_group=True)

    d_aki = draft(aki, nd("code LIKE 'N17%'"), editor_h, message="first cut")
    d_ampi = draft(ampi, nd("code LIKE 'J01CA01%'"), editor_h, change_type="critical")

    queue = c.get("/drafts", headers=publisher_h).json()
    assert [d["id"] for d in queue] == [d_ampi, d_aki], queue  # newest first
    rows = {d["id"]: d for d in queue}

    assert rows[d_aki]["concept_id"] == aki, rows[d_aki]
    assert rows[d_aki]["taxonomy"] == "corr_v1" and rows[d_aki]["name"] == "aki", rows[d_aki]
    assert rows[d_aki]["source"] == "cub_hdp", rows[d_aki]
    assert rows[d_aki]["type"] == "native_dynamic", rows[d_aki]
    assert rows[d_aki]["change_type"] == "improvement", rows[d_aki]
    assert rows[d_aki]["message"] == "first cut", rows[d_aki]
    assert rows[d_aki]["author"] == "editor", rows[d_aki]
    assert rows[d_aki]["created_at"], rows[d_aki]
    assert rows[d_aki]["concept_deprecated_at"] is None, rows[d_aki]

    # The group member resolves to the same name as its sibling — the id is what tells them
    # apart, and it is the id the app pins the concept page to.
    assert rows[d_ampi]["name"] == "atc_j01", rows[d_ampi]
    assert rows[d_ampi]["concept_id"] == ampi != amox, rows[d_ampi]
    assert rows[d_ampi]["change_type"] == "critical", rows[d_ampi]

    # The row's own link target still resolves to the pinned member.
    members = c.get("/concept/corr_v1/atc_j01").json()
    assert sorted(m["id"] for m in members) == sorted([amox, ampi]), members
    pinned = c.get(f"/concept/id/{ampi}?draft={d_ampi}").json()
    assert pinned["sources"]["cub_hdp"]["version_info"]["status"] == "draft", pinned

    # --- publishing takes the draft out of the queue ------------------------------------------
    # …and only can_publish may do it — an editor writes the draft and stops there.
    assert c.post(f"/concept/id/{aki}/drafts/{d_aki}/publish",
                  headers=editor_h, json={}).status_code == 403
    r = c.post(f"/concept/id/{aki}/drafts/{d_aki}/publish", headers=publisher_h, json={})
    assert r.status_code == 200 and r.json()["version_no"] == 1, r.text
    assert [d["id"] for d in c.get("/drafts", headers=publisher_h).json()] == [d_ampi]

    # Discarding one takes it out too — the queue is what is *open*, not what ever existed.
    assert c.delete(f"/concept/id/{ampi}/drafts/{d_ampi}", headers=editor_h).status_code == 204
    assert c.get("/drafts", headers=publisher_h).json() == []

    # --- a retired concept's leftover draft is flagged, not hidden ---------------------------
    # A deprecation can be approved while a draft is still open on the concept; the queue says
    # so rather than quietly dropping a row a reviewer would keep waiting for.
    d_amox = draft(amox, nd("code LIKE 'J01CA04%'"), editor_h)
    r = c.post(f"/concept/id/{amox}/deprecation-request", headers=editor_h,
               json={"reason": "duplicate", "successor_id": ampi})
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]

    # The reviewer sees the request waiting…
    pending = c.get("/deprecation-requests?status=pending", headers=publisher_h).json()
    assert [p["id"] for p in pending] == [request_id], pending
    assert pending[0]["concept"]["name"] == "atc_j01", pending[0]
    # …and the editor who filed it can neither see nor answer it.
    assert c.get("/deprecation-requests?status=pending", headers=editor_h).status_code == 403
    assert c.post(f"/deprecation-requests/{request_id}/approve",
                  headers=editor_h, json={}).status_code == 403
    assert c.post(f"/deprecation-requests/{request_id}/reject",
                  headers=editor_h, json={}).status_code == 403

    assert c.post(f"/deprecation-requests/{request_id}/approve",
                  headers=publisher_h, json={}).status_code == 200
    assert c.get("/deprecation-requests?status=pending", headers=publisher_h).json() == []

    queue = c.get("/drafts", headers=publisher_h).json()
    assert [d["id"] for d in queue] == [d_amox], queue
    assert queue[0]["concept_deprecated_at"] is not None, queue[0]

    # --- the nav badge counts ------------------------------------------------------------
    # `/auth/pending-counts` is the same two queues, added up, for the navigation. What it
    # must never do is answer for a queue the caller may not open: that comes back null, so
    # the app can tell "nothing waiting" from "not yours to see".
    def counts(headers: dict) -> dict:
        r = _raw_get("/auth/pending-counts", headers=headers)
        assert r.status_code == 200, r.text
        return r.json()

    assert _raw_get(
        "/auth/pending-counts", headers={"authorization": "Bearer nonsense"}
    ).status_code == 401

    # An editor sees neither queue.
    assert counts(editor_h) == {"review": None, "pending_users": None}

    # A publisher sees the review queue and not the approval queue. One draft is open
    # (d_amox, on the retired concept) and the one deprecation request was just approved.
    assert counts(publisher_h) == {"review": 1, "pending_users": None}

    # Publishing that last draft empties the queue — zero, not null: a publisher may look.
    r = c.post(f"/concept/id/{amox}/drafts/{d_amox}/publish", headers=publisher_h, json={})
    assert r.status_code == 200, r.text
    assert counts(publisher_h)["review"] == 0

    # A fresh request re-fills it: the count is drafts *plus* pending requests, and an
    # answered request drops back out.
    r = c.post(f"/concept/id/{ampi}/deprecation-request", headers=editor_h,
               json={"reason": "second thoughts"})
    assert r.status_code == 201, r.text
    req2 = r.json()["id"]
    assert counts(publisher_h)["review"] == 1
    d_extra = draft(aki, nd("code LIKE 'N18%'"), editor_h)
    assert counts(publisher_h)["review"] == 2
    assert c.post(f"/deprecation-requests/{req2}/reject",
                  headers=publisher_h, json={}).status_code == 200
    assert counts(publisher_h)["review"] == 1, counts(publisher_h)
    assert c.delete(f"/concept/id/{aki}/drafts/{d_extra}", headers=editor_h).status_code == 204

    # The admin sees both halves.
    assert counts(admin_h) == {"review": 0, "pending_users": 0}

    # A capability-less user is somebody waiting to be let in…
    with SessionLocal() as db:
        db.add_all([
            User(username="applicant", password_hash="", capabilities=[], is_active=True),
            # …a deactivated one is not: turning somebody down is deactivating them, and a
            # badge that counted those could never be cleared.
            User(username="turned-down", password_hash="", capabilities=[], is_active=False),
        ])
        db.commit()
    assert counts(admin_h) == {"review": 0, "pending_users": 1}
    # Still nothing a publisher may ask about.
    assert counts(publisher_h)["pending_users"] is None

    # Approving them clears the badge.
    with SessionLocal() as db:
        applicant_id = db.scalar(select(User.id).where(User.username == "applicant"))
    r = c.patch(f"/admin/users/{applicant_id}", headers=admin_h,
                json={"capabilities": ["can_read"], "is_active": True})
    assert r.status_code == 200, r.text
    assert counts(admin_h)["pending_users"] == 0

print("REVIEW SMOKE OK")
