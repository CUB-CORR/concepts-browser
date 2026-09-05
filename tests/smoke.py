"""End-to-end smoke test against a temp SQLite DB. Run: uv run python tests/smoke.py"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "smoke.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret"
# Exercise the app/user read path; empty secret keeps the external project gate off (and
# stops a developer's real .env APP_SHARED_SECRET from leaking in and forcing a project).
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
# This test drives the bare API surface; the reference dataset (which would pre-create
# concepts like `any_dialysis`) is imported in its own test — see tests/import_smoke.py.
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

# Valid cub_hdp native_dynamic definitions (conform to the per-type JSON Schema).
ND_Z49 = {"type": "native_dynamic", "table_name": "diagnoses",
          "where_clause": "code LIKE 'Z49%'"}
ND_N18 = {"type": "native_dynamic", "table_name": "diagnoses",
          "where_clause": "code LIKE 'N18%'"}
# A valid reprodicu native_static — same type names as cub_hdp, entirely different shape.
REPRO_STATIC = {"type": "native_static", "path": "patient_information",
                "column": "Admission Type", "is_struct": False, "dynamic": False,
                "filter": "pl.col('Admission Type').is_not_null()"}

with TestClient(app) as client:
    # --- auth ---
    r = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    token = r.json()["access_token"]
    h = {"authorization": f"Bearer {token}"}

    r = client.get("/auth/me", headers=h)
    assert r.status_code == 200 and "can_publish" in r.json()["capabilities"], r.text

    # writes require auth
    assert client.post("/concepts", json={"name": "nope"}).status_code in (401, 403)
    # reads now require auth too (can_read); unauthenticated -> 401
    assert client.get("/concepts").status_code in (401, 403)

    # From here on authenticate every request as the admin (has can_read + all caps).
    client.headers["authorization"] = f"Bearer {token}"
    # Concept reads now take a required `project` param; in app mode (empty secret) the value is
    # ignored, but it must be present. Inject it on every GET like the BFF does. (httpx's
    # client.params clobbers inline query strings, so append to the URL instead.)
    _raw_get = client.get
    client.get = lambda url, **kw: _raw_get(
        f"{url}{'&' if '?' in url else '?'}project=internal", **kw
    )

    def one(url: str) -> dict:
        """The single concept a name resolves to — name reads always return a list."""
        r = client.get(url)
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    # --- reference / schema folder is the source of truth for types ---
    sources = {s["key"]: s for s in client.get("/sources").json()}
    assert sources["cub_hdp"]["schema_governed"] is True, sources
    assert set(sources["cub_hdp"]["supported_types"]) == {
        "native_dynamic", "medication", "laboratory",
    }, sources["cub_hdp"]
    # reprodicu ships schemas of its own, so it is governed too — and its `native_dynamic` is
    # a different shape than cub_hdp's, which is the whole point of keying schemas on the pair
    # (see tests/reprodicu_smoke.py)
    assert sources["reprodicu"]["schema_governed"] is True, sources["reprodicu"]
    assert set(sources["reprodicu"]["supported_types"]) == {
        "native_dynamic", "native_static", "derived_dynamic", "derived_static",
    }, sources["reprodicu"]
    assert "$id" in client.get("/sources/cub_hdp/schema/native_dynamic").json()
    assert client.get("/sources/cub_hdp/schema/bogus").status_code == 404

    # --- create concept (its name lives under the default corr_v1 taxonomy) ---
    r = client.post("/concepts", json={"name": "any_dialysis", "display_name": "Any Dialysis"}, headers=h)
    assert r.status_code == 201 and r.json()["taxonomy"] == "corr_v1", r.text

    # it shows up under corr_v1 only; taxonomies it isn't named in hide it
    assert "any_dialysis" in {c["name"] for c in client.get("/concepts").json()}
    assert "any_dialysis" in {c["name"] for c in client.get("/concepts?taxonomy=corr_v1").json()}
    assert client.get("/concepts?taxonomy=ICD10").json() == []
    assert client.get("/concepts?taxonomy=nope").status_code == 404  # unknown taxonomy
    # a name already in use is a 409 that says which concept holds it...
    r = client.post("/concepts", json={"name": "any_dialysis"}, headers=h)
    assert r.status_code == 409 and r.json()["detail"]["error"] == "name_exists", r.text
    assert [m["id"] for m in r.json()["detail"]["members"]] == [1], r.text

    # copy-mode with nothing published yet has nothing to copy -> 400
    assert client.post("/concept/corr_v1/any_dialysis/drafts", headers=h,
                       json={"source": "cub_hdp"}).status_code == 400

    # --- first cub_hdp definition: empty=true (no prior), must be valid ---
    r = client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={
        "source": "cub_hdp", "empty": True, "type": "native_dynamic",
        "json": ND_Z49, "message": "initial"})
    assert r.status_code == 201, r.text
    d1 = r.json()
    assert d1["validation_status"] == "passed", d1

    # invalid json is rejected with a structured error
    r = client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={
        "source": "cub_hdp", "empty": True, "type": "native_dynamic",
        "json": {"type": "native_dynamic", "where_clause": "no table_name"}})
    assert r.status_code == 400 and r.json()["detail"]["error"] == "schema_validation_failed", r.text

    # default GET: nothing published yet; draft overlay shows it. display_name comes from corr_v1
    body = one("/concept/corr_v1/any_dialysis")
    assert body["sources"] == {} and body["display_name"] == "Any Dialysis", body
    assert body["pointer"]["identifier"] == "any_dialysis" and body["pointer"]["origin"] == "user"
    assert body["deprecated_at"] is None and body["successor_id"] is None, body
    assert "cub_hdp" in one(f"/concept/corr_v1/any_dialysis?draft={d1['id']}")["sources"]
    # A source whose only definition is an open draft therefore appears in exactly one place
    # without a `?draft=` selector: the drafts listing, which names it. A client that shows open
    # work has to union the two — a concept with nothing published has an empty `sources` and
    # would otherwise render as having no sources at all.
    open_drafts = client.get(f"/concept/id/{body['id']}/drafts").json()
    assert [(x["id"], x["source"]) for x in open_drafts] == [(d1["id"], "cub_hdp")], open_drafts
    # the id route is the same concept, addressed canonically (a single object, not a list)
    by_id = client.get(f"/concept/id/{body['id']}").json()
    assert by_id["id"] == body["id"] and by_id["name"] == "any_dialysis", by_id
    assert client.get("/concept/id/99999").status_code == 404
    # a name not registered in the queried taxonomy -> 404
    assert client.get("/concept/ICD10/any_dialysis").status_code == 404

    # publish -> v1, change_type forced to "initial"
    r = client.post(f"/concept/corr_v1/any_dialysis/drafts/{d1['id']}/publish", headers=h, json={})
    assert r.status_code == 200 and r.json()["version_no"] == 1, r.text
    assert r.json()["change_type"] == "initial"
    assert one("/concept/corr_v1/any_dialysis")["sources"]["cub_hdp"]["json"]["where_clause"] \
        == "code LIKE 'Z49%'"

    # --- second source reprodicu: governed by its own schemas, on its own type vocabulary ---
    r = client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={
        "source": "reprodicu", "empty": True, "type": "native_static",
        "json": REPRO_STATIC, "message": "reprodicu init"})
    assert r.status_code == 201 and r.json()["validation_status"] == "passed", r.text
    # cub_hdp's json would be nonsense here, and vice versa — schemas are keyed on the pair
    assert client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={
        "source": "reprodicu", "empty": True, "type": "native_dynamic",
        "json": ND_Z49, "message": "wrong source's shape"}).status_code == 400
    d2 = r.json()["id"]
    assert client.post(f"/concept/corr_v1/any_dialysis/drafts/{d2}/publish", headers=h, json={}).json()["version_no"] == 2

    body = one("/concept/corr_v1/any_dialysis")
    assert body["version"] == 2 and set(body["sources"]) == {"cub_hdp", "reprodicu"}
    assert body["sources"]["cub_hdp"]["version_info"]["source_version"] == 1  # carried forward

    # --- auto-copy: a new cub_hdp draft inherits the latest published json/type ---
    r = client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={"source": "cub_hdp"})
    assert r.status_code == 201, r.text
    d3 = r.json()
    assert d3["type"] == "native_dynamic" and d3["json"]["where_clause"] == "code LIKE 'Z49%'", d3
    assert d3["validation_status"] == "passed"

    # changing the type while copying is refused (use empty=true instead)
    assert client.post("/concept/corr_v1/any_dialysis/drafts", headers=h,
                       json={"source": "cub_hdp", "type": "medication"}).status_code == 400

    # edit the copied draft, then publish it as a critical fix -> v3
    assert client.put(f"/concept/corr_v1/any_dialysis/drafts/{d3['id']}", headers=h,
                      json={"json": ND_N18, "change_type": "critical"}).status_code == 200
    assert client.post(f"/concept/corr_v1/any_dialysis/drafts/{d3['id']}/publish", headers=h,
                       json={"change_type": "critical"}).json()["version_no"] == 3
    assert one("/concept/corr_v1/any_dialysis")["sources"]["cub_hdp"]["json"]["where_clause"] \
        == "code LIKE 'N18%'"

    # querying old cub_hdp v1 now warns it was superseded by the critical fix in v3
    vi = one("/concept/corr_v1/any_dialysis?v=1")["sources"]["cub_hdp"]["version_info"]
    assert vi["source_version"] == 1
    assert vi["warning"] and vi["warning"]["corrected_in_version"] == 3, vi
    # current version carries no warning
    assert one("/concept/corr_v1/any_dialysis")["sources"]["cub_hdp"]["version_info"]["warning"] is None

    # --- unknown types are rejected for a governed source ---
    assert client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={
        "source": "cub_hdp", "empty": True, "type": "bogus_type",
        "json": {"type": "bogus_type"}}).status_code == 400
    # auto-generated types can't be drafted by hand
    assert client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={
        "source": "cub_hdp", "empty": True, "type": "medication",
        "json": {"type": "medication", "drug": "x"}}).status_code == 400
    # empty=true without a type is rejected
    assert client.post("/concept/corr_v1/any_dialysis/drafts", headers=h, json={
        "source": "cub_hdp", "empty": True, "json": ND_Z49}).status_code == 400

    # --- the documentation PATCH no longer carries the study context ---------------------
    # PICO and the study team moved to the project (see tests/projects_smoke.py). The schema
    # ignores unknown keys, so a body of nothing but those fields sets no field at all — which
    # the handler rejects rather than answering 200 to a write it did not make.
    r = client.patch("/concept/corr_v1/any_dialysis/documentation", headers=h, json={
        "pico_population": "Adults on the ICU", "study_team": "A. Beispiel"})
    assert r.status_code == 400, r.text
    # ...and they are not served on the concept either.
    body = one("/concept/corr_v1/any_dialysis")
    assert not any(k.startswith("pico_") for k in body) and "study_team" not in body, body

    # a fourth version, so the history below has one to show
    d4 = client.post("/concept/corr_v1/any_dialysis/drafts", headers=h,
                     json={"source": "cub_hdp"}).json()
    assert client.post(f"/concept/corr_v1/any_dialysis/drafts/{d4['id']}/publish", headers=h,
                       json={"change_type": "editorial"}).json()["version_no"] == 4

    # history (only the published rows)
    hist = client.get("/concept/corr_v1/any_dialysis/history").json()
    assert [row["version"] for row in hist] == [4, 3, 2, 1], hist

    # v / date / draft are mutually exclusive
    assert client.get("/concept/corr_v1/any_dialysis?v=1&draft=1").status_code == 400
    assert client.get("/concept/corr_v1/any_dialysis?v=1&date=2026-01-01T00:00Z").status_code == 400

    # aliases: v == version, date == d (and they echo back under the canonical names)
    assert one("/concept/corr_v1/any_dialysis?version=1")["requested"]["v"] == 1
    assert one("/concept/corr_v1/any_dialysis?d=2026-01-01T00:00Z")["requested"]["date"] \
        == one("/concept/corr_v1/any_dialysis?date=2026-01-01T00:00Z")["requested"]["date"]
    assert client.get("/concept/corr_v1/any_dialysis?version=1&d=2026-01-01T00:00Z").status_code == 400

print("SMOKE OK")
