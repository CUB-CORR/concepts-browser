"""Usage-tracking smoke test. Run: uv run python tests/usage_smoke.py

Proves the usage rollup (`api/usage.py`, folded from the audit log) and the endpoints over it:

* the fold counts the right thing — successful concept GETs a known user made *against the API*,
  and neither writes, nor 404s, nor group reads (which name no single concept), nor the reads
  our own web app makes while that user browses (`client_type='app'`);
* legacy rows, logged before there was a `client_type` to record, still count;
* folding is idempotent: re-running, and rebooting, never double-counts;
* per-user usage is self-or-admin — another user's usage is a 403;
* the per-concept aggregate is identity-free for a non-admin (no distinct-reader count) while
  still carrying that caller's own share;
* the versions a user read are folded alongside the counts, from the same rows;
* the rollup is derived data: a rebuild from the log reproduces it exactly.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "usage.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = "app-secret"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "false"

from datetime import datetime  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import security, usage  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import AuditLog, ConceptUsage, UsageRollupState, User  # noqa: E402

NS_Z49 = {"type": "native_dynamic", "table_name": "diagnoses",
          "where_clause": "code LIKE 'Z49%'"}

APP = {"x-app-secret": "app-secret"}


def _login(client, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"authorization": f"Bearer {r.json()['access_token']}"}


PROJECT = "study-x"


def _app_read(client, headers, path, expect=200):
    """A concept read as the web app makes it on the user's behalf: app secret, placeholder
    project. Not the user calling the API — must never land in their usage."""
    r = client.get(path, headers={**headers, **APP}, params={"project": "internal"})
    assert r.status_code == expect, r.text
    return r


def _api_read(client, headers, path, expect=200):
    """A concept read the user makes themselves: no app secret, a real project named. This is
    what the usage panel is about."""
    r = client.get(path, headers=headers, params={"project": PROJECT})
    assert r.status_code == expect, r.text
    return r


def _publish(client, headers, name, definition):
    r = client.post("/concepts", json={"name": name}, headers={**headers, **APP})
    assert r.status_code == 201, r.text
    concept_id = r.json()["id"]
    r = client.post(
        f"/concept/corr_v1/{name}/drafts",
        headers={**headers, **APP},
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
              "json": definition, "message": "m"},
    )
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]
    r = client.post(
        f"/concept/corr_v1/{name}/drafts/{draft_id}/publish",
        headers={**headers, **APP},
        json={"change_type": "improvement", "message": "m"},
    )
    assert r.status_code == 200, r.text
    return concept_id


with TestClient(app) as client:
    with SessionLocal() as db:
        for username, caps in (("reader", ["can_read"]), ("other", ["can_read"])):
            db.add(
                User(
                    username=username,
                    password_hash=security.hash_password("pw"),
                    display_name=username.title(),
                    capabilities=caps,
                    is_active=True,
                )
            )
        db.commit()

    admin_h = _login(client, "admin", "admin")
    reader_h = _login(client, "reader", "pw")
    other_h = _login(client, "other", "pw")

    with SessionLocal() as db:
        reader_id = db.scalar(select(User.id).where(User.username == "reader"))
        other_id = db.scalar(select(User.id).where(User.username == "other"))
        admin_id = db.scalar(select(User.id).where(User.username == "admin"))

    dialysis_id = _publish(client, admin_h, "any_dialysis", NS_Z49)
    ckd_id = _publish(client, admin_h, "ckd_stage", NS_Z49)

    # A live, license-accepted project, so an external client has one to name.
    r = client.post(
        "/projects", headers={**admin_h, **APP}, json={"name": PROJECT, "accept_license": True}
    )
    assert r.status_code == 201, r.text

    # --- generate reads ---------------------------------------------------------------------
    # reader: 3 reads of any_dialysis (one by id, one history), 1 of ckd_stage
    for _ in range(2):
        _api_read(client, reader_h, "/concept/corr_v1/any_dialysis")
    _api_read(client, reader_h, f"/concept/id/{dialysis_id}")
    _api_read(client, reader_h, "/concept/corr_v1/ckd_stage")
    # other: 1 read of any_dialysis
    _api_read(client, other_h, "/concept/corr_v1/any_dialysis")
    # None of these is a use: a miss, a write, and — the point of the client_type filter —
    # the reads the web app makes while these two browse the very same concepts.
    _api_read(client, reader_h, "/concept/corr_v1/nope", expect=404)
    assert client.post("/concepts", json={"name": "written"}, headers={**admin_h, **APP}).status_code == 201
    for _ in range(3):
        _app_read(client, reader_h, "/concept/corr_v1/any_dialysis")
    _app_read(client, reader_h, "/concept/corr_v1/ckd_stage")
    _app_read(client, other_h, "/concept/corr_v1/ckd_stage")

    # --- the fold ----------------------------------------------------------------------------
    r = client.get(f"/usage/users/{reader_id}", headers={**reader_h, **APP})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["concepts_used"] == 2, body
    assert body["total_reads"] == 4, body
    assert body["last_active_at"] is not None, body
    by_id = {c["concept_id"]: c for c in body["concepts"]}
    assert by_id[dialysis_id]["reads"] == 3, by_id
    assert by_id[ckd_id]["reads"] == 1, by_id
    assert by_id[dialysis_id]["name"] == "any_dialysis", by_id
    assert by_id[dialysis_id]["taxonomy"] == "corr_v1", by_id
    # One published version so far, and every read served it.
    assert by_id[dialysis_id]["versions"] == "1", by_id
    assert by_id[ckd_id]["versions"] == "1", by_id
    # Newest first.
    assert [c["concept_id"] for c in body["concepts"]] == sorted(
        by_id, key=lambda cid: by_id[cid]["last_used_at"], reverse=True
    ), body
    # The 404 and the write are not uses; the concept created by the write has no usage row.
    with SessionLocal() as db:
        assert db.get(ConceptUsage, (admin_id, dialysis_id)) is None

    # --- the web app's own reads are logged, but are not the user's API usage ----------------
    # Recording them and not counting them is deliberate: the audit log stays a complete record
    # of every request, and the rollup — derived from it — is where the line is drawn.
    with SessionLocal() as db:
        app_reads = db.scalars(
            select(AuditLog).where(
                AuditLog.client_type == "app",
                AuditLog.concept_id.is_not(None),
                AuditLog.method == "GET",
            )
        ).all()
        assert len(app_reads) == 5, app_reads  # 4 by reader, 1 by other
        # `other` browsed ckd_stage in the app and never pulled it over the API.
        assert db.get(ConceptUsage, (other_id, ckd_id)) is None
    # …and browsing does not move "last active" either, or it would contradict the two counts
    # sitting next to it on the profile.
    before_browsing = body["last_active_at"]
    _app_read(client, reader_h, "/concept/corr_v1/any_dialysis")
    after = client.get(f"/usage/users/{reader_id}", headers={**reader_h, **APP}).json()
    assert after["last_active_at"] == before_browsing, (before_browsing, after["last_active_at"])
    assert after["total_reads"] == 4, after

    # Idempotent: folding again changes nothing (the watermark has already passed those rows).
    with SessionLocal() as db:
        assert usage.refresh(db) == 0
        assert usage.refresh(db) == 0
    again = client.get(f"/usage/users/{reader_id}", headers={**reader_h, **APP}).json()
    assert again["total_reads"] == 4, again

    # --- authorization ------------------------------------------------------------------------
    assert client.get(f"/usage/users/{other_id}", headers={**reader_h, **APP}).status_code == 403
    assert client.get(f"/usage/users/{reader_id}", headers={**other_h, **APP}).status_code == 403
    assert client.get(f"/usage/users/{reader_id}", headers={**admin_h, **APP}).status_code == 200
    assert client.get(f"/usage/users/{other_id}", headers={**other_h, **APP}).status_code == 200
    assert client.get(f"/usage/users/{reader_id}").status_code == 401  # anonymous
    # A user who does not exist is a 403 for a non-admin (it must not confirm which ids do),
    # and a 404 for an admin.
    assert client.get("/usage/users/999999", headers={**reader_h, **APP}).status_code == 403
    assert client.get("/usage/users/999999", headers={**admin_h, **APP}).status_code == 404

    # --- per-concept aggregate ----------------------------------------------------------------
    rows = client.get("/usage/concepts", headers={**admin_h, **APP}, params={"sort": "reads"}).json()
    top = rows[0]
    assert top["concept_id"] == dialysis_id, rows
    assert top["reads"] == 4, rows          # reader 3 + other 1
    assert top["users"] == 2, rows          # the admin sees how many people
    assert top["name"] == "any_dialysis" and top["taxonomy"] == "corr_v1", rows

    rows = client.get("/usage/concepts", headers={**reader_h, **APP}, params={"sort": "reads"}).json()
    assert [r["concept_id"] for r in rows][0] == dialysis_id, rows
    assert rows[0]["reads"] == 4, rows      # the total is not secret…
    assert all(r["users"] is None for r in rows), rows  # …but who is behind it is
    assert rows[0]["my_reads"] == 3, rows   # a caller may always see their own share
    assert rows[0]["my_last_used_at"] is not None, rows

    # "most used by me": `other` read only any_dialysis, so ckd_stage sinks to my_reads 0.
    rows = client.get("/usage/concepts", headers={**other_h, **APP}, params={"sort": "mine"}).json()
    assert rows[0]["concept_id"] == dialysis_id and rows[0]["my_reads"] == 1, rows
    assert next(r for r in rows if r["concept_id"] == ckd_id)["my_reads"] == 0, rows
    mine_only = client.get(
        "/usage/concepts", headers={**other_h, **APP}, params={"mine_only": True}
    ).json()
    assert [r["concept_id"] for r in mine_only] == [dialysis_id], mine_only

    # --- a seeded log row folds like a real one -----------------------------------------------
    # Straight into the log, as an external client's read would land: the rollup has no other
    # source of truth, so this is the only thing it can be checked against.
    with SessionLocal() as db:
        db.add(
            AuditLog(
                event="api_call",
                created_at=datetime(2030, 1, 1, 12, 0, 0),
                user_id=other_id,
                client_type="external",
                method="GET",
                path="/concept/corr_v1/ckd_stage",
                status_code=200,
                concept_id=ckd_id,
                concept_name="ckd_stage",
                taxonomy="corr_v1",
                concept_version=3,
            )
        )
        # A row from before there was a `client_type` to record. It is history, and there is
        # nothing to tell it apart by, so it still counts.
        db.add(
            AuditLog(
                event="api_call",
                created_at=datetime(2020, 1, 1, 12, 0, 0),
                user_id=other_id,
                client_type=None,
                method="GET",
                path="/concept/corr_v1/ckd_stage",
                status_code=200,
                concept_id=ckd_id,
                concept_name="ckd_stage",
                taxonomy="corr_v1",
            )
        )
        # A group read names no concept, and must not be counted as using one.
        db.add(
            AuditLog(
                event="api_call", user_id=other_id, method="GET", path="/concept/corr_v1/grp",
                status_code=200, concept_id=None, concept_name="grp", taxonomy="corr_v1",
            )
        )
        db.commit()

    body = client.get(f"/usage/users/{other_id}", headers={**other_h, **APP}).json()
    assert body["concepts_used"] == 2, body
    assert body["total_reads"] == 3, body  # 1 live + the external seed + the legacy seed
    seeded = next(c for c in body["concepts"] if c["concept_id"] == ckd_id)
    assert seeded["reads"] == 2, seeded
    assert seeded["last_used_at"].startswith("2030-01-01"), seeded
    assert seeded["first_used_at"].startswith("2020-01-01"), seeded
    # Only the seeded read named a version; the version-less legacy row beside it adds nothing.
    assert seeded["versions"] == "3", seeded
    # The seeded read is the newest, so it sorts first.
    assert body["concepts"][0]["concept_id"] == ckd_id, body

    # --- versions accumulate as new ones are published and read ------------------------------
    # A second version of any_dialysis, then a read of it: the pair has now seen both, and the
    # list widens rather than being replaced.
    _publish(client, admin_h, "any_dialysis_v2", NS_Z49)  # unrelated concept, keeps ids apart
    r = client.post(
        "/concept/corr_v1/any_dialysis/drafts",
        headers={**admin_h, **APP},
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
              "json": NS_Z49, "message": "m"},
    )
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]
    r = client.post(
        f"/concept/corr_v1/any_dialysis/drafts/{draft_id}/publish",
        headers={**admin_h, **APP},
        json={"change_type": "improvement", "message": "m"},
    )
    assert r.status_code == 200, r.text
    _api_read(client, reader_h, "/concept/corr_v1/any_dialysis")
    body = client.get(f"/usage/users/{reader_id}", headers={**reader_h, **APP}).json()
    by_id = {c["concept_id"]: c for c in body["concepts"]}
    assert by_id[dialysis_id]["versions"] == "1, 2", by_id
    assert by_id[dialysis_id]["reads"] == 4, by_id
    # An app read of v2 by `other` must not put a version on a pair it has no reads for either.
    _app_read(client, other_h, "/concept/corr_v1/any_dialysis")
    with SessionLocal() as db:
        usage.refresh(db)
        assert db.get(ConceptUsage, (other_id, dialysis_id)).versions == "1"

    # --- rebuild reproduces the fold ----------------------------------------------------------
    with SessionLocal() as db:
        before = {
            (r.user_id, r.concept_id): (r.reads, r.first_used_at, r.last_used_at, r.versions)
            for r in db.scalars(select(ConceptUsage))
        }
        usage.rebuild(db)
        after = {
            (r.user_id, r.concept_id): (r.reads, r.first_used_at, r.last_used_at, r.versions)
            for r in db.scalars(select(ConceptUsage))
        }
    assert before == after, (before, after)

# --- a second boot is a no-op ------------------------------------------------------------------
# `_migrate()` and the rollup backfill both run on every start; neither may duplicate anything.
with SessionLocal() as db:
    watermark_before = db.get(UsageRollupState, 1).last_audit_id
    totals_before = {
        (r.user_id, r.concept_id): r.reads
        for r in db.scalars(select(ConceptUsage))
    }

with TestClient(app) as client:
    _login(client, "admin", "admin")
    with SessionLocal() as db:
        totals_after = {
            (r.user_id, r.concept_id): r.reads
            for r in db.scalars(select(ConceptUsage))
        }
        assert totals_after == totals_before, (totals_before, totals_after)
        assert db.get(UsageRollupState, 1).last_audit_id >= watermark_before

print("usage smoke: OK")
