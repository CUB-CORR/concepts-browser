"""Re-import safety: `import_reference(force=True)` must rebuild the concept graph but never
touch the users table, and must survive audit rows that reference the concepts it wipes.

Also covers what the default (upsert) path does *not* do: it never wipes, so a concept an
operator retired stays retired and a name they added by hand stays theirs.
Run: uv run python tests/reimport_safety.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "reimport.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = "app-secret"  # lets the concept read below count as the app
os.environ["LDAP_ENABLED"] = "false"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "true"  # seed a real concept graph

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from api import services  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.importer import import_reference  # noqa: E402
from api.main import app  # noqa: E402
from api.models import AuditLog, Concept, ConceptTaxonomy, User  # noqa: E402

APP = {"x-app-secret": "app-secret"}

with TestClient(app) as client:  # lifespan seeds + imports the reference dataset
    # Provision an LDAP-style user with granted capabilities we expect to survive.
    with SessionLocal() as db:
        db.add(
            User(
                username="alice",
                ldap_guid="GUID-alice==",
                display_name="Alice",
                password_hash="",
                capabilities=["can_edit", "can_publish"],
                is_active=True,
            )
        )
        db.commit()
        users_before = db.scalar(select(func.count()).select_from(User))
        concepts_before = db.scalar(select(func.count()).select_from(Concept))
    assert users_before == 2 and concepts_before > 0, (users_before, concepts_before)

    # Read a concept, so an audit row points at one (audit_log.concept_id is a FK into the very
    # table the re-import wipes — in production this is what made the wipe fail).
    r = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    admin_h = {"Authorization": f"Bearer {r.json()['access_token']}", **APP}
    r = client.get(
        "/concept/corr_v1/heart_rate", headers=admin_h, params={"project": "internal"}
    )
    assert r.status_code == 200, r.text
    heart_rate_id = r.json()[0]["id"]

    with SessionLocal() as db:
        audited = db.scalar(
            select(AuditLog).where(AuditLog.concept_id.is_not(None)).order_by(AuditLog.id.desc())
        )
        assert audited is not None and audited.concept_name == "heart_rate", audited
        audited_id = audited.id

    # --- the upsert path leaves operator decisions alone --------------------------------------
    # A hand-added second name for an imported concept, and a retired concept.
    r = client.post(
        f"/concept/id/{heart_rate_id}/pointers",
        headers=admin_h,
        json={"taxonomy": "LOINC", "identifier": "8867-4"},
    )
    assert r.status_code == 201, r.text
    sodium_id = client.get(
        "/concept/corr_v1/blood_sodium", headers=admin_h, params={"project": "internal"}
    ).json()[0]["id"]
    r = client.post(
        f"/concept/id/{sodium_id}/deprecation-request",
        headers=admin_h,
        json={"reason": "duplicate", "successor_id": heart_rate_id},
    )
    assert r.status_code == 201, r.text
    request_id = r.json()["id"]
    assert client.post(
        f"/deprecation-requests/{request_id}/approve", headers=admin_h, json={}
    ).status_code == 200

    stats = import_reference()
    assert stats is not None and (stats.imported, stats.updated) == (0, 0), stats
    with SessionLocal() as db:
        sodium = db.get(Concept, sodium_id)
        assert sodium.deprecated_at is not None, "the upsert un-retired a concept"
        assert sodium.successor_id == heart_rate_id, sodium.successor_id
        loinc = db.scalar(
            select(ConceptTaxonomy).where(ConceptTaxonomy.identifier == "8867-4")
        )
        assert loinc is not None and loinc.origin == "user", loinc
        assert loinc.deprecated_at is None, "the upsert retired a user's name"

    # --- the forced rebuild -------------------------------------------------------------------
    stats = import_reference(force=True)
    assert stats is not None and stats.imported > 0, stats

    with SessionLocal() as db:
        # Concept graph rebuilt...
        assert db.scalar(select(func.count()).select_from(Concept)) > 0
        again = services.resolve_pointers(db, "corr_v1", "heart_rate")
        assert len(again) == 1 and again[0][0].origin == "import", again

        # ...the audit row survives, detached from the wiped concept but still naming what was
        # read. Keeping the old id would re-point it at whatever concept now holds that id.
        row = db.get(AuditLog, audited_id)
        assert row is not None, "re-import deleted an audit row"
        assert row.concept_id is None, row.concept_id
        assert row.concept_name == "heart_rate" and row.taxonomy == "corr_v1", row
        # ...but every user row and its capabilities are untouched.
        assert db.scalar(select(func.count()).select_from(User)) == users_before
        alice = db.scalar(select(User).where(User.username == "alice"))
        assert alice is not None and alice.capabilities == ["can_edit", "can_publish"], alice
        assert alice.ldap_guid == "GUID-alice=="

print("REIMPORT SAFETY OK")
