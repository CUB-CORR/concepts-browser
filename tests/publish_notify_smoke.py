"""Publish-notification smoke test. Run: uv run python tests/publish_notify_smoke.py

Publishing with `notify: true` tells the people a new version concerns:

* everyone who has used the concept (the usage rollup), plus the leads of every project it was
  used from (the audit log) — one message each, however many ways a person qualifies;
* never the publisher, who already knows, and never a deactivated account;
* a user the directory has no address for is a recorded skip, not a failure;
* `notify` defaults to false: an ordinary publish mails nobody.

The EWS transport is monkeypatched exactly as in `tests/email_smoke.py`; everything above it
runs for real through the publish API.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "publish_notify.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = "app-secret"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "false"
os.environ["EXCHANGE_ENABLED"] = "false"  # the transport is faked below; nothing may leave the box
os.environ["FRONTEND_ORIGIN"] = "https://concepts.example.org"
os.environ["APP_DISPLAY_NAME"] = "Concepts Browser"
os.environ["CONTACT_EMAIL"] = "concepts@example.org"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import mailer, security  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import EMAIL_SENT, ProjectLead, User  # noqa: E402

NS_Z49 = {"type": "native_dynamic", "table_name": "diagnoses",
          "where_clause": "code LIKE 'Z49%'"}

APP = {"x-app-secret": "app-secret"}
PROJECT = "study-x"

# --- capture the EWS transport ---------------------------------------------------------------
sent: list[dict] = []


def _fake_send(to, subject, text_body, html_body=None):
    sent.append({"to": to, "subject": subject, "text": text_body, "html": html_body})
    return EMAIL_SENT, None


mailer._send = _fake_send


def _login(client, username, password="pw"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"authorization": f"Bearer {r.json()['access_token']}"}


def _mail(username, address=True):
    profile = {"cn": [f"Doe, {username.title()}"]}
    if address:
        profile["mail"] = [f"{username}@example.org"]
    return profile


# username -> (capabilities, has a directory address)
PEOPLE = {
    "publisher": (["can_publish"], True),
    "usera": (["can_read"], True),
    "userb": (["can_read"], True),   # also a lead: must still get exactly one message
    "lead": (["can_read"], True),    # a lead who never read the concept himself
    "exlead": (["can_read"], True),  # a lead, but deactivated
    "nomail": (["can_read"], True),  # a user the directory has no address for (set below)
}


def _draft_and_publish(client, headers, name, *, message, notify=None, change_type="improvement"):
    r = client.post(
        f"/concept/corr_v1/{name}/drafts",
        headers={**headers, **APP},
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
              "json": NS_Z49, "message": message},
    )
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]
    body = {"change_type": change_type, "message": message}
    if notify is not None:
        body["notify"] = notify
    r = client.post(
        f"/concept/corr_v1/{name}/drafts/{draft_id}/publish",
        headers={**headers, **APP},
        json=body,
    )
    assert r.status_code == 200, r.text
    return r.json()


with TestClient(app) as client:
    with SessionLocal() as db:
        for username, (caps, _) in PEOPLE.items():
            db.add(
                User(
                    username=username,
                    password_hash=security.hash_password("pw"),
                    display_name=username.title(),
                    capabilities=caps,
                    ldap_profile=_mail(username, address=username != "nomail"),
                    is_active=True,
                )
            )
        db.commit()
        ids = {
            u.username: u.id
            for u in db.scalars(select(User).where(User.username.in_(PEOPLE)))
        }

    admin_h = _login(client, "admin", "admin")
    h = {name: _login(client, name) for name in PEOPLE}

    # --- a concept, its first published version ------------------------------------------
    r = client.post("/concepts", json={"name": "any_dialysis"}, headers={**h["publisher"], **APP})
    assert r.status_code == 201, r.text
    concept_id = r.json()["id"]
    _draft_and_publish(client, h["publisher"], "any_dialysis", message="first")
    assert sent == [], sent  # nothing published so far asked to notify anybody

    # A live project for the external reads to name, with two leads: one who reads the concept
    # himself and one who never does. Plus a deactivated lead, who is not told anything. (The
    # creating admin always leads their own project — he is a recipient too, and the directory
    # has no address for a local account, so his message is a recorded skip.)
    r = client.post(
        "/projects", headers={**admin_h, **APP}, json={"name": PROJECT, "accept_license": True}
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]
    with SessionLocal() as db:
        for username in ("userb", "lead", "exlead"):
            db.add(ProjectLead(project_id=project_id, user_id=ids[username]))
        db.get(User, ids["exlead"]).is_active = False
        db.commit()

    # --- the reads that make someone a recipient -------------------------------------------
    # Direct API reads, naming the project: these are what the rollup counts and what attributes
    # the concept to the project.
    for username in ("usera", "userb", "nomail", "publisher"):
        r = client.get(
            "/concept/corr_v1/any_dialysis", headers=h[username], params={"project": PROJECT}
        )
        assert r.status_code == 200, r.text
    # `lead` only ever browsed it in the web app — not usage, but he leads the project that did.
    r = client.get(
        "/concept/corr_v1/any_dialysis",
        headers={**h["lead"], **APP},
        params={"project": "internal"},
    )
    assert r.status_code == 200, r.text

    # --- publish with notify -----------------------------------------------------------------
    published = _draft_and_publish(
        client, h["publisher"], "any_dialysis",
        message="widened the code range", notify=True, change_type="critical",
    )
    assert published["version_no"] == 2, published

    # usera + userb (users), lead + userb (leads) => three people, userb once.
    assert sorted(m["to"] for m in sent) == [
        "lead@example.org",
        "usera@example.org",
        "userb@example.org",
    ], sent
    # The publisher is not told about his own publish, and neither is the deactivated lead.
    assert not any("publisher" in m["to"] or "exlead" in m["to"] for m in sent), sent

    mail = next(m for m in sent if m["to"] == "usera@example.org")
    assert mail["subject"] == "Concepts Browser — critical update to corr_v1/any_dialysis", mail
    assert mail["text"].startswith("Dear Usera Doe!"), mail["text"]
    url = "https://concepts.example.org/concepts/tax/corr_v1/any_dialysis?cid=" + str(concept_id)
    assert url in mail["text"], mail["text"]
    assert url in mail["html"], mail["html"]
    assert "widened the code range" in mail["text"], mail["text"]
    assert "widened the code range" in mail["html"], mail["html"]
    assert "you have used: corr_v1/any_dialysis." in mail["text"], mail["text"]
    assert "<strong>corr_v1/any_dialysis</strong>" in mail["html"], mail["html"]
    assert "concepts@example.org" in mail["text"], mail["text"]
    assert "version 2" in mail["text"], mail["text"]

    # --- every attempt is an `email` row, including the one with nowhere to go ---------------
    events = client.get(
        "/audit/events", headers={**admin_h, **APP}, params={"event": "email"}
    ).json()
    rows = events["items"]
    assert events["total"] == 5, events  # 3 sent + 2 with nowhere to send to
    assert all(r["email_kind"] == "publish_alert" for r in rows), rows
    skipped = [r for r in rows if r["email_status"] != EMAIL_SENT]
    assert sorted(r["user"]["username"] for r in skipped) == ["admin", "nomail"], skipped
    nomail_row = next(r for r in skipped if r["user"]["username"] == "nomail")
    assert nomail_row["email_to"] is None, nomail_row
    assert nomail_row["detail"]["reason"] == "no_ldap_mail_address", nomail_row
    assert nomail_row["detail"]["concept_id"] == concept_id, nomail_row
    assert nomail_row["detail"]["version_no"] == 2, nomail_row

    # --- notify is opt-in: the default publish mails nobody -----------------------------------
    before = len(sent)
    _draft_and_publish(client, h["publisher"], "any_dialysis", message="quiet one")
    assert len(sent) == before, sent[before:]
    _draft_and_publish(
        client, h["publisher"], "any_dialysis", message="explicitly quiet", notify=False
    )
    assert len(sent) == before, sent[before:]

    # --- an improvement says so, and a missing note is simply left out ------------------------
    _draft_and_publish(
        client, h["publisher"], "any_dialysis", message=None, notify=True,
    )
    fresh = sent[before:]
    assert len(fresh) == 3, fresh
    assert fresh[0]["subject"] == "Concepts Browser — update to corr_v1/any_dialysis", fresh[0]
    assert "note" not in fresh[0]["text"], fresh[0]["text"]

print("PUBLISH NOTIFY SMOKE OK")
