"""Approval-email smoke test. Run: uv run python tests/email_smoke.py

The mail server (like the directory) is only reachable from the deployment host, so the EWS
transport `mailer._send` is monkeypatched to capture messages; everything above it — who gets
notified, on which transition, with what recipient/greeting/body — is exercised for real
through the admin API.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "email.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "true"
os.environ["EXCHANGE_ENABLED"] = "false"  # the transport is faked below; nothing may leave the box
os.environ["FRONTEND_ORIGIN"] = "https://concepts.example.org"
os.environ["APP_DISPLAY_NAME"] = "Concepts Browser"
os.environ["CONTACT_EMAIL"] = "concepts@example.org"  # asserted to appear in the message body

from fastapi.testclient import TestClient  # noqa: E402

from api import ldap_auth, mailer  # noqa: E402
from api.main import app  # noqa: E402
from api.models import EMAIL_SENT, EMAIL_SKIPPED, User  # noqa: E402

# --- unit: the salutation is the directory `cn`, flipped into natural order ----------------
assert mailer.greeting_name(User(username="x", ldap_profile={"cn": ["Doe, Jane"]})) == (
    "Jane Doe"
)
# already natural / single-word / missing cn: left alone, then fall back down the chain
assert mailer.greeting_name(User(username="x", ldap_profile={"cn": ["Jane Doe"]})) == (
    "Jane Doe"
)
assert mailer.greeting_name(User(username="uid", display_name="Display", ldap_profile={})) == (
    "Display"
)
assert mailer.greeting_name(User(username="uid", ldap_profile=None)) == "uid"
# a local (non-LDAP) user has no directory address, so there is nobody to write to
assert mailer.recipient_for(User(username="admin", ldap_profile=None)) is None

# --- capture the EWS transport --------------------------------------------------------------
sent: list[dict] = []
_real_send = mailer._send


def _fake_send(to, subject, text_body, html_body=None):
    sent.append({"to": to, "subject": subject, "text": text_body, "html": html_body})
    return EMAIL_SENT, None  # the transport's contract: (audit status, failure reason)


mailer._send = _fake_send

# --- fake directory (same shape as tests/auth_smoke.py) ------------------------------------
_DIRECTORY = {
    "doej": (
        "GUID-abc==",
        "Doe, Jane",
        {"cn": ["Doe, Jane"], "mail": ["jane.doe@example.org"]},
    ),
    # In the directory, but with no mail attribute: approving them must not blow up.
    "nomail": ("GUID-nomail==", "Ohne, Mail", {"cn": ["Ohne, Mail"]}),
}
_DIR_ONLY = {
    "muellera": (
        "GUID-xyz==",
        "Müller, Anna",
        {"cn": ["Müller, Anna"], "mail": ["anna.mueller@example.org"]},
    )
}


def _identity(uid, hit):
    guid, display, profile = hit
    return ldap_auth.LdapIdentity(guid=guid, uid=uid, display_name=display, profile=profile)


def _fake_authenticate(username, password):
    hit = _DIRECTORY.get(username)
    return _identity(username, hit) if hit and password == "correct-horse" else None


def _fake_resolve(username):
    hit = {**_DIRECTORY, **_DIR_ONLY}.get(username.strip())
    return _identity(username.strip(), hit) if hit else None


ldap_auth.authenticate = _fake_authenticate
ldap_auth.resolve = _fake_resolve

with TestClient(app) as client:
    admin_h = {
        "authorization": "Bearer "
        + client.post(
            "/auth/login", json={"username": "admin", "password": "admin"}
        ).json()["access_token"]
    }

    # first login provisions a pending (empty-cap) user — no mail yet, nothing is approved
    assert client.post(
        "/auth/login", json={"username": "doej", "password": "correct-horse"}
    ).status_code == 200
    assert sent == [], sent

    users = {u["username"]: u for u in client.get("/admin/users", headers=admin_h).json()}
    pending_id = users["doej"]["id"]

    # --- approval: the pending -> capable transition mails the user ------------------------
    r = client.patch(
        f"/admin/users/{pending_id}",
        headers=admin_h,
        json={"capabilities": ["can_read", "can_edit"]},
    )
    assert r.status_code == 200, r.text
    assert len(sent) == 1, sent
    mail = sent[0]
    assert mail["to"] == "jane.doe@example.org", mail  # the LDAP `mail` attribute
    assert "approved" in mail["subject"].lower(), mail
    assert mail["text"].startswith("Dear Jane Doe!"), mail["text"]
    # the app is linked at its public origin, and there is somewhere to write back to
    assert "concepts@example.org" in mail["text"], mail["text"]
    assert "https://concepts.example.org" in mail["text"], mail["text"]
    assert "https://concepts.example.org" in mail["html"], mail["html"]

    # --- a later capability edit is NOT a re-approval: no second email ---------------------
    assert client.patch(
        f"/admin/users/{pending_id}",
        headers=admin_h,
        json={"capabilities": ["can_read", "can_edit", "can_publish"]},
    ).status_code == 200
    assert len(sent) == 1, sent
    # nor is deactivating them
    assert client.patch(
        f"/admin/users/{pending_id}", headers=admin_h, json={"is_active": False}
    ).status_code == 200
    assert len(sent) == 1, sent

    # --- provisioning WITH capabilities is an approval: it mails too ------------------------
    r = client.post(
        "/admin/users",
        headers=admin_h,
        json={"username": "muellera", "capabilities": ["can_read"]},
    )
    assert r.status_code == 201, r.text
    assert len(sent) == 2, sent
    assert sent[1]["to"] == "anna.mueller@example.org", sent[1]
    assert sent[1]["text"].startswith("Dear Anna Müller!"), sent[1]["text"]

    # --- provisioning with NO capabilities is not an approval: stays silent -----------------
    assert client.post(
        "/admin/users", headers=admin_h, json={"username": "nomail", "capabilities": []}
    ).status_code == 201
    assert len(sent) == 2, sent

    # ...and approving someone the directory has no address for is a no-op, not a 500
    nomail_id = {
        u["username"]: u["id"] for u in client.get("/admin/users", headers=admin_h).json()
    }["nomail"]
    assert client.patch(
        f"/admin/users/{nomail_id}", headers=admin_h, json={"capabilities": ["can_read"]}
    ).status_code == 200
    assert len(sent) == 2, sent

    # --- every attempt is an `email` row in the audit log ------------------------------------
    # Including the one that never went out: "we couldn't reach them" and "we never tried" are
    # the answers the log has to be able to give, and neither leaves any other trace.
    events = client.get("/audit/events", headers=admin_h, params={"event": "email"}).json()
    assert events["total"] == 3, events
    rows = events["items"]  # newest first

    skipped, anna, moritz = rows
    assert [r["email_status"] for r in rows] == [EMAIL_SKIPPED, EMAIL_SENT, EMAIL_SENT], rows
    assert all(r["email_kind"] == "approval" for r in rows), rows
    # An email row is attributed to its *recipient*, not to the admin who triggered it, and it
    # is not a request: no method, path or client.
    assert moritz["user"]["username"] == "doej", moritz
    assert moritz["email_to"] == "jane.doe@example.org", moritz
    assert moritz["email_subject"] == mailer.APPROVAL_SUBJECT, moritz
    # What the message told them they could do — as the schema normalized it, not as sent.
    assert moritz["detail"]["capabilities"] == ["can_edit", "can_read"], moritz
    assert (moritz["method"], moritz["path"], moritz["client_type"]) == (None, None, None), moritz
    assert anna["user"]["username"] == "muellera", anna

    # The unreachable user: no address, so nothing was sent — and the row says why.
    assert skipped["user"]["username"] == "nomail", skipped
    assert skipped["email_to"] is None, skipped
    assert skipped["detail"]["reason"] == "no_ldap_mail_address", skipped

    # The tab filters: by recipient, and by what became of the message.
    only_moritz = client.get(
        "/audit/events",
        headers=admin_h,
        params={"event": "email", "user_id": pending_id},
    ).json()
    assert [r["id"] for r in only_moritz["items"]] == [moritz["id"]], only_moritz
    unsent = client.get(
        "/audit/events",
        headers=admin_h,
        params={"event": "email", "email_status": EMAIL_SKIPPED},
    ).json()
    assert [r["id"] for r in unsent["items"]] == [skipped["id"]], unsent
    # ...and the search box, which on this tab means subject or recipient
    by_address = client.get(
        "/audit/events", headers=admin_h, params={"event": "email", "q": "anna.mueller"}
    ).json()
    assert [r["id"] for r in by_address["items"]] == [anna["id"]], by_address

# --- unit: the real transport is inert while EXCHANGE_ENABLED=false (no connection attempted)
mailer._send = _real_send
assert mailer._send("someone@example.org", "subject", "body") == (EMAIL_SKIPPED, "mail_disabled")

print("EMAIL SMOKE OK")
