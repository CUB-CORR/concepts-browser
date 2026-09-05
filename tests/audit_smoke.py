"""Audit-log smoke test. Run: uv run python tests/audit_smoke.py

Proves the audit log actually holds the events the audit page reads back:

* every login attempt — successful ones attributed to the user, failed ones to the attempted
  username (and to nobody);
* every authenticated API call, split app (our web app, by shared secret) vs external;
* concept reads attributed to the concept, and to the version *served* — with the selector the
  client sent (`v` / `date` / `draft`) recorded alongside it, since the two differ whenever a
  client pins a version or reads as-of a past date;

and that `/audit/*` is admin-only and filters on each of date, user, project and concept.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "audit.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = "app-secret"  # turns the app/external distinction on
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "false"

from datetime import date, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from api import security  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import User  # noqa: E402

NS_Z49 = {"type": "native_dynamic", "table_name": "diagnoses",
          "where_clause": "code LIKE 'Z49%'"}
NS_N18 = {"type": "native_dynamic", "table_name": "diagnoses",
          "where_clause": "code LIKE 'N18%'"}

APP = {"x-app-secret": "app-secret"}


def _login(client, username, password, expect=200):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == expect, r.text
    if r.status_code != 200:
        return None
    return {"authorization": f"Bearer {r.json()['access_token']}"}


def _events(client, headers, **params):
    r = client.get("/audit/events", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


with TestClient(app) as client:
    # A plain reader, who will play the external API client.
    with SessionLocal() as db:
        db.add(
            User(
                username="reader",
                password_hash=security.hash_password("pw"),
                display_name="Reader",
                capabilities=["can_read"],
                is_active=True,
            )
        )
        db.commit()

    admin_h = _login(client, "admin", "admin")
    reader_h = _login(client, "reader", "pw")
    _login(client, "reader", "wrong-password", expect=401)  # failed attempt: also an event

    # --- the audit log is admin-only ---------------------------------------------------------
    assert client.get("/audit/events", headers=reader_h).status_code == 403
    assert client.get("/audit/filter-options", headers=reader_h).status_code == 403
    assert client.get("/audit/events").status_code == 401  # anonymous

    # --- logins tab --------------------------------------------------------------------------
    logins = _events(client, admin_h, event="login")
    assert logins["total"] == 3, logins  # admin ok, reader ok, reader failed
    by_status = {(e["status_code"], (e["user"] or {}).get("username")) for e in logins["items"]}
    assert (200, "admin") in by_status and (200, "reader") in by_status, by_status
    # The failed attempt is recorded against *nobody* — the name tried is all we can keep, and
    # it's the only trace such an attempt leaves.
    failed = next(e for e in logins["items"] if e["status_code"] == 401)
    assert failed["user"] is None and failed["detail"]["username"] == "reader", failed
    assert "password" not in str(failed["detail"]).lower(), failed  # never store credentials

    # --- set up a concept with two published versions -----------------------------------------
    r = client.post("/concepts", json={"name": "any_dialysis"}, headers={**admin_h, **APP})
    assert r.status_code == 201, r.text

    for definition in (NS_Z49, NS_N18):
        r = client.post(
            "/concept/corr_v1/any_dialysis/drafts",
            headers={**admin_h, **APP},
            json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
                  "json": definition, "message": "m"},
        )
        assert r.status_code == 201, r.text
        draft_id = r.json()["id"]
        r = client.post(
            f"/concept/corr_v1/any_dialysis/drafts/{draft_id}/publish",
            headers={**admin_h, **APP},
            json={"change_type": "improvement", "message": "m"},
        )
        assert r.status_code == 200, r.text

    # An unpublished draft, to read back via the `draft` selector.
    r = client.post(
        "/concept/corr_v1/any_dialysis/drafts",
        headers={**admin_h, **APP},
        json={"source": "cub_hdp", "json": NS_Z49, "message": "wip"},
    )
    assert r.status_code == 201, r.text
    open_draft = r.json()["id"]

    # --- a project for the external client to name --------------------------------------------
    r = client.post(
        "/projects",
        headers={**admin_h, **APP},
        json={"name": "sepsis", "description": "d", "accept_license": True},
    )
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]

    # --- external concept reads, one per selector ---------------------------------------------
    # (a) no selector: whatever is current
    assert client.get(
        "/concept/corr_v1/any_dialysis", headers=reader_h, params={"project": "sepsis"}
    ).status_code == 200
    # (b) pinned to version 1
    assert client.get(
        "/concept/corr_v1/any_dialysis", headers=reader_h, params={"project": "sepsis", "v": 1}
    ).status_code == 200
    # (c) as-of a past date, via the `d` alias — before anything was published
    past = "2000-01-01T00:00:00"
    assert client.get(
        "/concept/corr_v1/any_dialysis", headers=reader_h, params={"project": "sepsis", "d": past}
    ).status_code == 200
    # (d) a draft overlay
    assert client.get(
        "/concept/corr_v1/any_dialysis",
        headers=reader_h,
        params={"project": "sepsis", "draft": open_draft},
    ).status_code == 200

    reads = _events(client, admin_h, event="api_call", concept_id=1, client_type="external")
    assert reads["total"] == 4, reads
    # newest first
    draft_read, date_read, pinned_read, current_read = reads["items"]

    for e in reads["items"]:
        assert e["concept_name"] == "any_dialysis" and e["taxonomy"] == "corr_v1", e
        assert e["project_name"] == "sepsis" and e["project_id"] == project_id, e
        assert e["user"]["username"] == "reader" and e["auth_method"] == "jwt", e
        assert e["client_type"] == "external" and e["status_code"] == 200, e

    # The served version and the requested selector are logged as two different things.
    assert current_read["concept_version"] == 2, current_read
    assert current_read["detail"]["selector"] == {"v": None, "date": None, "draft": None}

    assert pinned_read["concept_version"] == 1, pinned_read
    assert pinned_read["detail"]["selector"]["v"] == 1, pinned_read

    # As-of a date before the first publish: nothing was published yet, so nothing was served.
    assert date_read["concept_version"] is None, date_read
    assert date_read["detail"]["selector"]["date"].startswith("2000-01-01"), date_read
    assert date_read["query_string"] and "d=" in date_read["query_string"], date_read

    # A draft has no version number, so it doesn't move the served version — it's the selector.
    assert draft_read["detail"]["selector"]["draft"] == open_draft, draft_read

    # --- app traffic is distinguished from external -------------------------------------------
    assert client.get(
        "/concept/corr_v1/any_dialysis", headers={**admin_h, **APP}, params={"project": "internal"}
    ).status_code == 200
    app_reads = _events(client, admin_h, event="api_call", client_type="app", concept_id=1)
    assert app_reads["total"] == 1, app_reads
    # App browsing is not attributed to a project (the app names no real one).
    assert app_reads["items"][0]["project_id"] is None, app_reads

    # --- the request itself is captured -------------------------------------------------------
    row = reads["items"][0]
    assert row["method"] == "GET" and row["path"] == "/concept/corr_v1/any_dialysis", row
    assert row["detail"]["path_params"] == {"taxonomy": "corr_v1", "name": "any_dialysis"}, row
    assert row["detail"]["query_params"]["project"] == "sepsis", row
    assert row["ip_address"], row

    # --- filters ------------------------------------------------------------------------------
    with SessionLocal() as db:
        reader_id = db.scalar(
            __import__("sqlalchemy").select(User.id).where(User.username == "reader")
        )

    # 4 concept reads + the 2 audit-API calls the reader was denied. A refused request is an
    # audit event in its own right — that's the point of auditing at the middleware.
    assert _events(client, admin_h, user_id=reader_id, event="api_call")["total"] == 6
    denied = _events(client, admin_h, user_id=reader_id, q="/audit/")
    assert denied["total"] == 2 and all(e["status_code"] == 403 for e in denied["items"]), denied

    assert _events(client, admin_h, project_id=project_id)["total"] == 4
    assert _events(client, admin_h, concept_id=1)["total"] == 5  # 4 external + 1 app
    assert _events(client, admin_h, concept_id=999)["total"] == 0
    assert _events(client, admin_h, q="any_dialysis")["total"] >= 5
    today = date.today().isoformat()
    assert _events(client, admin_h, date_from=today, date_to=today)["total"] > 0
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert _events(client, admin_h, date_from=tomorrow)["total"] == 0
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert _events(client, admin_h, date_to=yesterday)["total"] == 0

    # paging
    page = _events(client, admin_h, limit=2, offset=0)
    assert len(page["items"]) == 2 and page["total"] > 2, page

    # --- filter options only offer values that have rows ---------------------------------------
    opts = client.get("/audit/filter-options", headers=admin_h).json()
    assert {u["username"] for u in opts["users"]} == {"admin", "reader"}, opts
    assert [p["name"] for p in opts["projects"]] == ["sepsis"], opts
    assert opts["concepts"] == [{"id": 1, "name": "any_dialysis", "taxonomy": "corr_v1"}], opts

    # --- writes are audited too (not just reads) ----------------------------------------------
    writes = _events(client, admin_h, event="api_call", q="/drafts")
    assert writes["total"] >= 3, writes
    assert all(e["user"]["username"] == "admin" for e in writes["items"]), writes

print("AUDIT SMOKE OK")
