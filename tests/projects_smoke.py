"""Projects + the app-vs-external concept gate and audit log.

Run: uv run python tests/projects_smoke.py

Covers project CRUD, the license gate, the activity chart, the study context (PICO + study
team, gated on lead-or-admin) and, with an APP_SHARED_SECRET configured, the read-gate:
app requests (X-App-Secret) need no project; external requests must name a live project that
has accepted the current license; every query lands in audit_log attributed to the user (and,
when external, the project).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "projects.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
# Turning this on is what enables the external project gate (empty = gate off for dev/tests).
os.environ["APP_SHARED_SECRET"] = "test-app-secret"

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import AuditLog, License, Project, User  # noqa: E402
from api.security import hash_password  # noqa: E402

APP = {"x-app-secret": "test-app-secret"}

with TestClient(app) as c:
    admin = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    h = {"authorization": f"Bearer {admin['access_token']}"}
    ha = {**h, **APP}  # a request "from the app"
    admin_id = int(__import__("jwt").decode(admin["access_token"], options={"verify_signature": False})["sub"])

    # A concept to query.
    assert c.post("/concepts", headers=h, json={"name": "aki"}).status_code == 201

    # --- the read gate --------------------------------------------------------------------
    # App request: the project value is ignored (app auth via the secret), but the required
    # param must still be present — the BFF sends the placeholder `internal`.
    assert c.get("/concepts", headers=ha, params={"project": "internal"}).status_code == 200
    assert c.get("/concept/corr_v1/aki", headers=ha, params={"project": "internal"}).status_code == 200
    # External request (no app header): the project param is mandatory. Omitting it entirely is a
    # 422 (FastAPI required-param validation); naming an unknown project is a 404.
    assert c.get("/concepts", headers=h).status_code == 422
    assert c.get("/concepts", headers=h, params={"project": "nope"}).status_code == 404

    # Two projects: one to query, one we'll delete.
    p1 = c.post("/projects", headers=h, json={"name": "study-x", "accept_license": True})
    assert p1.status_code == 201, p1.text
    pid = p1.json()["id"]
    p2 = c.post("/projects", headers=h, json={"name": "study-del", "accept_license": True}).json()

    # External query naming a live project succeeds; a deleted one is rejected.
    assert c.get("/concepts", headers=h, params={"project": "study-x"}).status_code == 200
    assert c.get("/concept/corr_v1/aki", headers=h, params={"project": "study-x"}).status_code == 200
    c.post(f"/projects/{p2['id']}/delete", headers=h)
    assert c.get("/concepts", headers=h, params={"project": "study-del"}).status_code == 403
    # Completed projects stay usable.
    c.patch(f"/projects/{pid}", headers=h, json={"completed": True})
    assert c.get("/concepts", headers=h, params={"project": "study-x"}).status_code == 200

    # --- the license gate -------------------------------------------------------------------
    # A project may only query while its license acceptance is current. Both failures — never
    # accepted, and accepted at a version the active license has since outrun — are 403s, and
    # neither is attributed to the project (the gate rejects before it resolves one).
    p3 = c.post("/projects", headers=h, json={"name": "study-lic", "accept_license": True}).json()
    assert c.get("/concepts", headers=h, params={"project": "study-lic"}).status_code == 200

    with SessionLocal() as db:
        db.get(Project, p3["id"]).license_approval = 0  # never accepted
        db.commit()
    r = c.get("/concepts", headers=h, params={"project": "study-lic"})
    assert r.status_code == 403, r.text
    assert "license" in r.json()["detail"], r.text  # the message says what to do about it

    # Re-accepting through the app clears it again.
    assert c.patch(f"/projects/{p3['id']}", headers=h, json={"accept_license": True}).status_code == 200
    assert c.get("/concepts", headers=h, params={"project": "study-lic"}).status_code == 200

    # Publishing a higher license version invalidates every prior approval until a lead re-accepts.
    with SessionLocal() as db:
        db.query(License).update({License.active: False})
        db.add(License(version=2, body="CORR license v2", active=True))
        db.commit()
    assert c.get("/concepts", headers=h, params={"project": "study-lic"}).status_code == 403
    assert c.patch(f"/projects/{p3['id']}", headers=h, json={"accept_license": True}).status_code == 200
    assert c.get("/concepts", headers=h, params={"project": "study-lic"}).status_code == 200
    # App requests never run the gate, so the web app keeps working through a license bump.
    assert c.get("/concepts", headers=ha, params={"project": "internal"}).status_code == 200

    # --- audit log ------------------------------------------------------------------------
    with SessionLocal() as db:
        rows = db.query(AuditLog).all()
        assert rows, "expected audit rows"
        # Every row is attributed to the requesting user.
        assert all(r.user_id == admin_id for r in rows), "audit_log must store the user id"
        external = [r for r in rows if r.project_id == pid]
        assert len(external) == 3, f"expected 3 external queries for study-x, got {len(external)}"
        assert all(r.client_type == "external" for r in external)
        assert any(r.client_type == "app" for r in rows), "app requests should be logged too"

    # --- activity reflects the audit log --------------------------------------------------
    act = c.get(f"/projects/{pid}/activity", headers=h).json()
    assert act["last_24h"]["total"] == 3, act["last_24h"]["total"]
    assert act["last_week"]["total"] == 3 and act["last_month"]["total"] == 3

    # --- the concepts read under the project -------------------------------------------------
    # The profile page's usage table, narrowed to one project. The rollup has no project
    # dimension, so this comes straight from the log — under the same rule the fold uses.
    # study-x's approval is stale since the license bump above, so ask the app for the id.
    # study-x's approval is stale since the license bump above, so ask the app for the id.
    aki_id = c.get("/concept/corr_v1/aki", headers=ha, params={"project": "internal"}).json()[0]["id"]
    rows = c.get(f"/projects/{pid}/usage", headers=h).json()
    assert [r["concept_id"] for r in rows] == [aki_id], rows
    # One of the three external queries read a concept; the other two listed them.
    assert rows[0]["reads"] == 1 and rows[0]["name"] == "aki", rows
    assert rows[0]["taxonomy"] == "corr_v1", rows
    assert rows[0]["last_used_at"] >= rows[0]["first_used_at"], rows

    # Seeded log rows: a versioned external read counts and names its version; an app read
    # attributed to the project does not count at all, exactly as in the rollup.
    with SessionLocal() as db:
        for client_type, version in (("external", 2), ("external", 4), ("app", 9)):
            db.add(AuditLog(event="api_call", user_id=admin_id, project_id=pid,
                            client_type=client_type, method="GET", path="/concept/corr_v1/aki",
                            status_code=200, concept_id=aki_id, concept_name="aki",
                            taxonomy="corr_v1", concept_version=version))
        # A write, a miss and a group read are not reads of a concept either.
        db.add(AuditLog(event="api_call", user_id=admin_id, project_id=pid,
                        client_type="external", method="POST", path="/concepts",
                        status_code=201, concept_id=aki_id, concept_name="aki"))
        db.add(AuditLog(event="api_call", user_id=admin_id, project_id=pid,
                        client_type="external", method="GET", path="/concept/corr_v1/nope",
                        status_code=404, concept_id=aki_id, concept_name="aki"))
        db.add(AuditLog(event="api_call", user_id=admin_id, project_id=pid,
                        client_type="external", method="GET", path="/concept/corr_v1/grp",
                        status_code=200, concept_id=None, concept_name="grp"))
        db.commit()
    rows = c.get(f"/projects/{pid}/usage", headers=h).json()
    assert len(rows) == 1 and rows[0]["reads"] == 3, rows  # 1 live + the 2 versioned seeds
    assert rows[0]["versions"] == "2, 4", rows

    # Another project sees none of it, and an unknown project is a 404.
    assert c.get(f"/projects/{p3['id']}/usage", headers=h).json() == []
    assert c.get("/projects/nope/usage", headers=h).status_code == 404
    assert c.get(f"/projects/{pid}/usage").status_code == 401  # anonymous

    # --- study context: the PICO frame and the study team -----------------------------------
    # They describe the *study*, which is what a project is, so they live on the project row and
    # are edited through the ordinary project PATCH — no capability, just the project's own gate
    # (`_can_edit`: a lead or an admin).
    PICO = ["pico_population", "pico_intervention", "pico_comparison", "pico_outcome"]
    p4 = c.post("/projects", headers=h, json={"name": "study-pico", "accept_license": True}).json()
    # empty for a fresh project — nothing but the project page ever writes them
    assert all(p4[f] is None for f in PICO) and p4["study_team"] is None, p4

    # Two ordinary users: one made a lead of the project, one with nothing to do with it.
    with SessionLocal() as db:
        for name in ("lead", "outsider"):
            db.add(User(username=name, password_hash=hash_password("pw"),
                        capabilities=["can_read"], is_active=True))
        db.commit()
        ids = {u.username: u.id for u in db.query(User).all()}
    lead_h = {"authorization": f"Bearer {c.post('/auth/login', json={'username': 'lead', 'password': 'pw'}).json()['access_token']}"}
    out_h = {"authorization": f"Bearer {c.post('/auth/login', json={'username': 'outsider', 'password': 'pw'}).json()['access_token']}"}
    assert c.patch(f"/projects/{p4['id']}", headers=h,
                   json={"lead_ids": [admin_id, ids["lead"]]}).status_code == 200

    # A lead may write it, and the response echoes the whole project back.
    ctx = {"pico_population": "Adults on the ICU", "pico_intervention": "Any dialysis",
           "pico_comparison": "No renal replacement", "pico_outcome": "28-day mortality",
           "study_team": "A. Beispiel (lead), B. Muster"}
    r = c.patch(f"/projects/{p4['id']}", headers=lead_h, json=ctx)
    assert r.status_code == 200, r.text
    assert all(r.json()[f] == v for f, v in ctx.items()), r.json()
    # ...and it round-trips through the detail read and the list alike.
    assert c.get(f"/projects/{p4['id']}", headers=lead_h).json()["pico_outcome"] == "28-day mortality"
    listed = {p["name"]: p for p in c.get("/projects", headers=lead_h).json()}
    assert listed["study-pico"]["study_team"] == "A. Beispiel (lead), B. Muster", listed["study-pico"]

    # A signed-in non-member may read it but not write it — same 403 as any other project edit.
    assert c.get(f"/projects/{p4['id']}", headers=out_h).json()["pico_population"] == "Adults on the ICU"
    assert c.get(f"/projects/{p4['id']}", headers=out_h).json()["can_edit"] is False
    assert c.patch(f"/projects/{p4['id']}", headers=out_h,
                   json={"pico_population": "hijacked"}).status_code == 403
    # An admin may write it without being a lead.
    assert c.patch(f"/projects/{p4['id']}", headers=h,
                   json={"pico_intervention": "Any RRT"}).status_code == 200

    # Partial: an omitted field keeps its value, an explicit null clears one — which is why the
    # handler goes by what the body *set*, not by the value being non-null.
    r = c.patch(f"/projects/{p4['id']}", headers=lead_h, json={"pico_comparison": None})
    assert r.status_code == 200 and r.json()["pico_comparison"] is None, r.text
    assert r.json()["pico_population"] == "Adults on the ICU", r.json()
    assert r.json()["pico_intervention"] == "Any RRT", r.json()
    # Whitespace is not content: an all-blank field clears, so the card can go back to hidden.
    assert c.patch(f"/projects/{p4['id']}", headers=lead_h,
                   json={"study_team": "   "}).json()["study_team"] is None

    # The lead cannot edit a *deleted* project's study context either — `_can_edit` refuses
    # before it looks at any field.
    assert c.patch(f"/projects/{p2['id']}", headers=h,
                   json={"study_team": "x"}).status_code == 404

print("PROJECTS SMOKE OK")
