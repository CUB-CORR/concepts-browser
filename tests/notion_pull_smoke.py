"""`python -m api.reimport` pulls the Notion documentation before it upserts.

Run: uv run python tests/notion_pull_smoke.py

Covers the three shapes a sidecar-less deployment can be in: Notion unconfigured (pull
skipped, upsert still runs), configured but unreachable (non-zero exit, upsert NOT run —
a half-run that silently applied a stale export is the failure mode), and a successful
fetch (notion_docs.json written, documentation applied to the concept rows). The Notion API
is faked at the HTTP layer with an httpx MockTransport; nothing leaves the box.
"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ref_dir = tempfile.mkdtemp()
db_path = os.path.join(tempfile.mkdtemp(), "notion_pull.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ["LDAP_ENABLED"] = "false"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "true"  # a real concept graph to document
os.environ["REFERENCE_DATASETS"] = "[]"  # the primary dataset is enough here
# The pull writes here, and the importer reads it back from the same setting.
_docs_path = os.path.join(_ref_dir, "notion_docs.json")
os.environ["REFERENCE_NOTION_DOCS_FILE"] = _docs_path
# Credentials stay unset at import time; each case sets them on `settings` directly.
os.environ["NOTION_API_KEY"] = ""
os.environ["NOTION_DATABASE_ID"] = ""
os.environ["NOTION_FIELDS_FILE"] = ""

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import notion_pull, reimport  # noqa: E402
from api.config import settings  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Concept, ConceptTaxonomy  # noqa: E402

DB_ID = "db-1234"
PAGES = [
    {
        "id": "aaaa-bbbb",
        "url": "https://www.notion.so/heart-rate",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "heart_rate"}]},
            "Description (clinical)": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "Beats per "}, {"plain_text": "minute."}],
            },
            "Description (implementation)": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "Monitoring feed."}],
            },
            "Known Caveats": {"type": "rich_text", "rich_text": []},
            "Status": {"type": "status", "status": {"name": "In Production"}},
        },
    },
    {
        # No `url` key: the export derives one from the page id, like the sidecar does.
        "id": "cccc-dddd",
        "properties": {
            "Name": {"type": "title", "title": [{"plain_text": "blood_sodium"}]},
            "Description (clinical)": {
                "type": "rich_text",
                "rich_text": [{"plain_text": "Serum sodium."}],
            },
            "Status": {"type": "status", "status": {"name": "Draft"}},
        },
    },
    # Untitled pages are not concepts and must be dropped.
    {"id": "eeee-ffff", "properties": {"Name": {"type": "title", "title": []}}},
]

seen: list[tuple[str, str]] = []  # (method, path) of every request the pull made


def _handler(request: httpx.Request) -> httpx.Response:
    seen.append((request.method, request.url.path))
    assert request.headers["authorization"] == "Bearer test-key", request.headers
    assert request.headers["notion-version"] == notion_pull.NOTION_VERSION, request.headers
    if request.method == "GET" and request.url.path == f"/v1/databases/{DB_ID}":
        return httpx.Response(200, json={"data_sources": [{"id": "ds-1"}]})
    if request.method == "POST" and request.url.path == "/v1/data_sources/ds-1/query":
        body = json.loads(request.content)
        assert body["page_size"] == 100, body
        if not body.get("start_cursor"):  # first page of a paginated database
            return httpx.Response(
                200, json={"results": PAGES[:1], "has_more": True, "next_cursor": "cur-2"}
            )
        assert body["start_cursor"] == "cur-2", body
        return httpx.Response(200, json={"results": PAGES[1:], "has_more": False})
    raise AssertionError(f"unexpected request {request.method} {request.url}")


def _fake_client(handler=_handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def run_main() -> tuple[int, str]:
    out = io.StringIO()
    with redirect_stdout(out):
        rc = reimport.main()
    return rc, out.getvalue()


def documentation(name: str) -> Concept | None:
    with SessionLocal() as db:
        ct = db.scalar(
            select(ConceptTaxonomy).where(
                ConceptTaxonomy.identifier == name, ConceptTaxonomy.deprecated_at.is_(None)
            )
        )
        return db.get(Concept, ct.concept_id) if ct else None


with TestClient(app):  # the lifespan seeds and imports the reference dataset
    imported = []
    _real_import = reimport.import_reference
    reimport.import_reference = lambda *a, **k: (imported.append(1), _real_import(*a, **k))[1]

    # --- Notion unconfigured: say so, skip the pull, still upsert -------------------------
    rc, out = run_main()
    assert rc == 0, (rc, out)
    assert "notion not configured" in out, out
    assert len(imported) == 1, imported
    assert not os.path.exists(_docs_path), "the skipped pull wrote a docs file"

    # --- configured but unreachable: non-zero, and the upsert never runs ------------------
    settings.notion_api_key = "test-key"
    settings.notion_database_id = DB_ID

    def _dead(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    notion_pull._client = lambda: _fake_client(_dead)
    rc, out = run_main()
    assert rc == 2, (rc, out)
    assert len(imported) == 1, "the upsert ran after a failed docs pull"
    assert not os.path.exists(_docs_path), "a failed pull wrote a docs file"

    # An HTTP error (a revoked token, a wrong database) is just as fatal.
    notion_pull._client = lambda: _fake_client(
        lambda request: httpx.Response(401, json={"message": "API token is invalid."})
    )
    rc, out = run_main()
    assert rc == 2, (rc, out)
    assert len(imported) == 1, "the upsert ran after a 401 from Notion"

    # --- a real export: written, counted, and applied to the concepts ---------------------
    notion_pull._client = _fake_client
    rc, out = run_main()
    assert rc == 0, (rc, out)
    assert "2 documented concept(s)" in out, out
    assert len(imported) == 2, imported
    assert seen == [
        ("GET", f"/v1/databases/{DB_ID}"),
        ("POST", "/v1/data_sources/ds-1/query"),
        ("POST", "/v1/data_sources/ds-1/query"),
    ], seen

    docs = json.load(open(_docs_path))
    assert set(docs) == {"heart_rate", "blood_sodium"}, docs  # the untitled page is dropped
    assert docs["heart_rate"] == {
        "clinical": "Beats per minute.",  # rich-text runs are joined
        "implementation": "Monitoring feed.",
        "caveats": None,  # empty rich text is None, not ""
        "status": "In Production",
        "url": "https://www.notion.so/heart-rate",
    }, docs["heart_rate"]
    # a page without `url`, and columns it simply doesn't have
    assert docs["blood_sodium"] == {
        "clinical": "Serum sodium.",
        "implementation": None,
        "caveats": None,
        "status": "Draft",
        "url": "https://www.notion.so/ccccdddd",
    }, docs["blood_sodium"]

    hr = documentation("heart_rate")
    assert hr.doc_clinical == "Beats per minute." and hr.doc_status == "In Production", hr
    assert hr.notion_url == "https://www.notion.so/heart-rate", hr.notion_url
    assert documentation("mean_arterial_pressure").doc_clinical is None

    # --- the column mapping comes from the reference dir when a file is there -------------
    with open(os.path.join(_ref_dir, "notion_fields.json"), "w") as f:
        json.dump({"clinical": "Klinik", "implementation": "x", "caveats": "y", "status": "z"}, f)
    assert notion_pull.load_fields()["clinical"] == "Klinik", notion_pull.load_fields()
    rc, out = run_main()
    assert rc == 0, (rc, out)
    # Nothing maps to the fixture's German column, so the clinical text is now empty…
    assert json.load(open(_docs_path))["heart_rate"]["clinical"] is None
    # …and the import cleared the concept's field: the export is authoritative.
    assert documentation("heart_rate").doc_clinical is None

    # A NOTION_FIELDS_FILE pointing at nothing is an error, not a silent default.
    settings.notion_fields_file = os.path.join(_ref_dir, "absent.json")
    rc, out = run_main()
    assert rc == 2, (rc, out)

print("NOTION PULL OK")
