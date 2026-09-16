"""Release-note broadcast smoke test. Run: uv run python tests/release_notify_smoke.py

`POST /admin/notifications/release` mails a package release's notes:

* admins only — a JWT or an API key scoped `can_admin`; anything less is a 403;
* to every approved, active user — never a pending or a deactivated account;
* a user the directory has no address for is a recorded skip, not a failure;
* `dry_run` sends nothing and returns the rendered message; `only_me` mails the caller alone;
* the Markdown is rendered to styled HTML: headings, lists, code, bare URLs, `@user` / `#123`
  when the repository is given, and raw HTML escaped rather than passed through.

The EWS transport is monkeypatched exactly as in `tests/email_smoke.py`.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "release_notify.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "false"
os.environ["EXCHANGE_ENABLED"] = "false"  # the transport is faked below; nothing may leave the box
os.environ["APP_DISPLAY_NAME"] = "Concepts Browser"
os.environ["CONTACT_EMAIL"] = "concepts@example.org"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import mailer, release_notes, security  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import EMAIL_SENT, AuditLog, User  # noqa: E402

# --- capture the EWS transport ---------------------------------------------------------------
sent: list[dict] = []


def _fake_send(to, subject, text_body, html_body=None):
    sent.append({"to": to, "subject": subject, "text": text_body, "html": html_body})
    return EMAIL_SENT, None


mailer._send = _fake_send

# What GitHub's "Generate release notes" produces, plus the constructs a hand-written note uses.
NOTES = """\
## What's Changed
* Add free-days outcome by @jdoe in https://github.com/CUB-CORR/corr-vars/pull/941
* Fix `TimeFilterStep` edge case (#898), see [the docs](https://example.org/docs)
* Contact me@example.org

### Breaking
> `add_variable` now requires `project`.

```python
cohort = Cohort(project="study-x")
```

| Old | New |
|-----|-----|
| a   | b   |

<script>alert(1)</script>

**Full Changelog**: https://github.com/CUB-CORR/corr-vars/compare/v1.9.0...v2.0.0
"""
RELEASE = {
    "version": "v2.0.0",
    "notes": NOTES,
    "release_url": "https://github.com/CUB-CORR/corr-vars/releases/tag/v2.0.0",
    "repository": "CUB-CORR/corr-vars",
}
URL = "/admin/notifications/release"

# --- the renderer on its own -----------------------------------------------------------------
html = release_notes.render_markdown(NOTES, repository="CUB-CORR/corr-vars")
assert "<h2 style=" in html and "What's Changed</h2>" in html, html
assert '<a href="https://github.com/jdoe" style=' in html, html
assert 'href="https://github.com/CUB-CORR/corr-vars/pull/941"' in html, html  # bare URL linked
assert 'href="https://github.com/CUB-CORR/corr-vars/issues/898"' in html, html
assert 'href="https://example.org/docs"' in html, html
assert "https://github.com/example.org" not in html, "an e-mail address is not a mention"
assert 'href="mailto:me@example.org"' in html, html
assert '<code style="' in html and "TimeFilterStep</code>" in html, html
assert '<pre style="' in html, html
assert "<table style=" in html and "<th style=" in html, html
assert "<blockquote style=" in html, html
assert "<script>" not in html and "&lt;script&gt;" in html, "raw HTML must be escaped"
# Links inside a link are left alone: the compare URL contains no mention to rewrite.
assert html.count('href="https://github.com/CUB-CORR/corr-vars/compare/v1.9.0...v2.0.0"') == 1

plain = release_notes.render_markdown(NOTES)
assert "https://github.com/jdoe" not in plain and "@jdoe" in plain, "no repository, no mentions"
assert 'href="https://github.com/CUB-CORR/corr-vars/pull/941"' in plain, "bare URLs still linked"


def _login(client, username, password="pw"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"authorization": f"Bearer {r.json()['access_token']}"}


def _profile(username, address=True):
    profile = {"cn": [f"Doe, {username.title()}"]}
    if address:
        profile["mail"] = [f"{username}@example.org"]
    return profile


# username -> (capabilities, active, has a directory address)
PEOPLE = {
    "boss": (["can_admin"], True, True),
    "reader": (["can_read"], True, True),
    "editor": (["can_edit"], True, True),
    "pending": ([], True, True),
    "gone": (["can_read"], False, True),
    "nomail": (["can_read"], True, False),
}

with TestClient(app) as client:
    with SessionLocal() as db:
        for username, (caps, active, address) in PEOPLE.items():
            db.add(
                User(
                    username=username,
                    password_hash=security.hash_password("pw"),
                    capabilities=caps,
                    ldap_profile=_profile(username, address),
                    is_active=active,
                )
            )
        db.commit()

    boss = _login(client, "boss")
    reader = _login(client, "reader")

    # --- auth ------------------------------------------------------------------------------
    assert client.post(URL, json=RELEASE).status_code in (401, 403)
    r = client.post(URL, headers=reader, json=RELEASE)
    assert r.status_code == 403, r.text

    # An admin's key scoped below admin is refused; one scoped can_admin is what CI uses.
    r = client.post("/api-keys", headers=boss, json={"name": "weak", "scopes": ["can_publish"]})
    weak_key = {"authorization": f"Bearer {r.json()['key']}"}
    r = client.post("/api-keys", headers=boss, json={"name": "ci", "scopes": ["can_admin"]})
    assert r.status_code == 201, r.text
    ci_key = {"authorization": f"Bearer {r.json()['key']}"}
    assert client.post(URL, headers=weak_key, json=RELEASE).status_code == 403

    # --- validation ------------------------------------------------------------------------
    for bad in (
        {**RELEASE, "notes": ""},
        {**RELEASE, "repository": "not a repo"},
        {**RELEASE, "release_url": "javascript:alert(1)"},
        {"notes": NOTES},  # no version
    ):
        assert client.post(URL, headers=boss, json=bad).status_code == 422, bad

    # --- dry run ---------------------------------------------------------------------------
    r = client.post(URL, headers=ci_key, json={**RELEASE, "dry_run": True})
    assert r.status_code == 202, r.text
    body = r.json()
    # admin (bootstrap, no address), boss, reader, editor, nomail — not pending, not gone.
    assert body["status"] == "dry_run", body
    assert body["recipients"] == 5, body
    assert body["without_address"] == 2, body  # the bootstrap admin and nomail
    assert body["subject"] == "Concepts Browser — corr_vars v2.0.0 released", body
    assert 'href="https://github.com/jdoe"' in body["html"], body["html"]
    assert 'href="https://github.com/CUB-CORR/corr-vars/releases/tag/v2.0.0"' in body["html"]
    assert sent == [], "a dry run sends nothing"

    # --- only_me ---------------------------------------------------------------------------
    r = client.post(URL, headers=ci_key, json={**RELEASE, "only_me": True})
    assert r.status_code == 202, r.text
    assert r.json()["recipients"] == 1, r.json()
    assert [m["to"] for m in sent] == ["boss@example.org"], sent
    sent.clear()

    # --- the broadcast ---------------------------------------------------------------------
    r = client.post(URL, headers=ci_key, json=RELEASE)
    assert r.status_code == 202, r.text
    assert r.json() == {
        "status": "queued",
        "package": "corr_vars",
        "version": "v2.0.0",
        "recipients": 5,
        "without_address": 2,
        "subject": None,
        "html": None,
    }, r.json()
    assert sorted(m["to"] for m in sent) == [
        "boss@example.org",
        "editor@example.org",
        "reader@example.org",
    ], sent
    reader_mail = next(m for m in sent if m["to"] == "reader@example.org")
    assert reader_mail["subject"] == "Concepts Browser — corr_vars v2.0.0 released"
    assert reader_mail["text"].startswith("Dear Reader Doe!"), reader_mail["text"]
    assert "## What's Changed" in reader_mail["text"], "the text body carries the Markdown as is"
    assert "Dear Reader Doe!" in reader_mail["html"], reader_mail["html"]
    assert "<script>" not in reader_mail["html"]

    # --- the audit trail -------------------------------------------------------------------
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditLog).where(AuditLog.email_kind == mailer.EMAIL_KIND_RELEASE_NOTE)
        ).all()
        by_status: dict[str, int] = {}
        for row in rows:
            by_status[row.email_status] = by_status.get(row.email_status, 0) + 1
            assert row.detail["version"] == "v2.0.0", row.detail
        # 1 (only_me) + 3 sent, 2 skipped for want of an address.
        assert by_status == {"sent": 4, "skipped": 2}, by_status

print("release notify smoke: OK")
