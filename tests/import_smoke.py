"""Reference-import test against a temp SQLite DB. Run: uv run python tests/import_smoke.py

Boots the app (whose lifespan seeds + imports reference/), then asserts the primary dataset
landed: the variable count, type/json/py round-tripping, schema-failures skipped, and that a
second pass over unchanged files writes nothing. The upsert engine itself (changes, pointer
sync, ambiguity) is exercised in tests/upsert_smoke.py.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "import.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret"
# Keep the external project gate off (don't inherit a developer's .env APP_SHARED_SECRET).
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "true"  # the behaviour under test
# Scoped to the primary dataset; the multi-dataset pass is its own test (reprodicu_smoke.py).
os.environ["REFERENCE_DATASETS"] = "[]"
# A sidecar-style Notion export the importer must apply to the concept rows.
_docs_path = os.path.join(tempfile.mkdtemp(), "notion_docs.json")
with open(_docs_path, "w") as f:
    json.dump(
        {
            "heart_rate": {
                "clinical": "Beats per minute.",
                "implementation": "Read from the monitoring feed.",
                "caveats": "Artifacts during transport.",
                "status": "In Production",
                "url": "https://www.notion.so/abc123",
            }
        },
        f,
    )
os.environ["REFERENCE_NOTION_DOCS_FILE"] = _docs_path

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

# Ground truth straight from the source files, so the assertions track the data.
ALL = json.load(open("reference/vars.json"))["variables"]
# The entry that deliberately doesn't fit its schema (missing table_name) — it must be
# skipped, not imported.
SKIPPED = {"invalid_example"}
EXPECTED = set(ALL) - SKIPPED

with TestClient(app) as client:  # entering the context runs the lifespan (seed + import)
    # Concept reads require can_read now; authenticate as the bootstrap admin for all calls.
    _tok = client.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    client.headers["authorization"] = f"Bearer {_tok['access_token']}"
    # Concept reads now take a required `project` param; app mode ignores its value but it must
    # be present. Inject it on every GET like the BFF does.
    _raw_get = client.get
    client.get = lambda url, **kw: _raw_get(
        f"{url}{'&' if '?' in url else '?'}project=internal", **kw
    )

    listed = {c["name"]: c for c in client.get("/concepts").json()}
    assert set(listed) == EXPECTED, sorted(set(listed) ^ EXPECTED)[:10]
    assert len(listed) == len(EXPECTED), (len(listed), len(EXPECTED))
    # The import owns the names it created, so a later pass can tell them from hand-made ones.
    assert all(c["origin"] == "import" for c in listed.values()), listed
    assert all(c["group_size"] == 1 for c in listed.values()), listed

    def one(url: str) -> dict:
        body = client.get(url).json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    # the schema-failing variables were skipped entirely
    for name in SKIPPED:
        assert name not in listed, name
        assert client.get(f"/concept/corr_v1/{name}").status_code == 404, name

    # every imported concept is a published v1, single source `cub_hdp`, type carried from JSON
    sample = listed["heart_rate"]
    assert sample["version"] == 1 and sample["sources"] == ["cub_hdp"], sample
    assert sample["types"] == ["native_dynamic"], sample
    assert sample["read_only"] is False, sample

    body = one("/concept/corr_v1/heart_rate")
    cub = body["sources"]["cub_hdp"]
    assert cub["json"] == ALL["heart_rate"], cub["json"]            # JSON round-trips intact
    assert cub["json"]["type"] == "native_dynamic"
    # heart_rate is the sample with a matching function in reference/variables.py
    assert cub["py"] and cub["py"].lstrip().startswith("def heart_rate("), (cub["py"] or "")[:60]
    vi = cub["version_info"]
    assert vi["source_version"] == 1 and vi["change_type"] == "initial", vi
    assert vi["status"] == "published" and vi["author"] == "admin", vi

    # a variable with NO matching function has no python snippet
    map_ = one("/concept/corr_v1/mean_arterial_pressure")["sources"]["cub_hdp"]
    assert map_["json"]["type"] == "native_dynamic", map_
    assert map_["py"] is None, map_

    # a non-auto-generated variable is editable (not read-only)
    assert vi["read_only"] is False, vi

    # the Notion export was applied to the concept row (and only to the listed concept)
    hr = one("/concept/corr_v1/heart_rate")
    assert hr["doc_clinical"] == "Beats per minute.", hr
    assert hr["doc_implementation"] == "Read from the monitoring feed.", hr
    assert hr["doc_caveats"] == "Artifacts during transport.", hr
    assert hr["doc_status"] == "In Production", hr
    assert hr["notion_url"] == "https://www.notion.so/abc123", hr
    other = one("/concept/corr_v1/mean_arterial_pressure")
    assert other["doc_clinical"] is None and other["notion_url"] is None, other

    # documentation PATCH: partial (untouched fields keep their value), null clears, and the
    # response echoes the row. The admin has every capability, so both gates pass.
    r = client.patch(
        "/concept/corr_v1/heart_rate/documentation",
        json={"doc_clinical": "Edited in app.", "doc_caveats": None},
    )
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["doc_clinical"] == "Edited in app." and doc["doc_caveats"] is None, doc
    assert doc["doc_implementation"] == "Read from the monitoring feed.", doc  # untouched
    r = client.patch("/concept/corr_v1/heart_rate/documentation", json={"doc_status": "Deprecated"})
    assert r.status_code == 200 and r.json()["doc_status"] == "Deprecated", r.text
    # an empty body is a 400, and no token is a 401
    assert client.patch("/concept/corr_v1/heart_rate/documentation", json={}).status_code == 400
    assert (
        client.patch(
            "/concept/corr_v1/heart_rate/documentation",
            json={"doc_status": "x"},
            headers={"authorization": ""},
        ).status_code
        == 401
    )

    # idempotency: a second pass over the same files finds everything unchanged and writes
    # nothing — no new versions, no new concepts.
    from api.importer import import_reference
    stats = import_reference()
    assert stats is not None, stats
    assert (stats.imported, stats.updated) == (0, 0), stats
    assert stats.unchanged == len(EXPECTED), stats
    assert len(client.get("/concepts").json()) == len(EXPECTED)
    assert one("/concept/corr_v1/heart_rate")["version"] == 1

print("IMPORT SMOKE OK")
