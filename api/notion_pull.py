"""Export per-concept documentation from a Notion database into ``notion_docs.json``.

The file this writes is exactly what ``api/importer.py`` applies to the concept rows
(``{name: {clinical, implementation, caveats, status, url}}``, page title = the concept's
canonical name), so a deployment that runs ``python -m api.reimport`` by hand gets the same
documentation a deployment running the vars-sync sidecar gets.

The sidecar owns the same export in ``sync/sync.py`` (``fetch_notion_docs``). The two are
deliberate duplicates: the api and sync images are separate build contexts — the api image
copies ``api/`` only — so neither can import the other at runtime. Any change to the Notion
API version, the page flattening or the exported shape must be made in both places.

Config via env (the sidecar's names, so one .env configures either mode):
  NOTION_API_KEY      integration token; unset = no export, reimport proceeds without one
  NOTION_DATABASE_ID  the documentation database; required with the key
  NOTION_FIELDS_FILE  column mapping; default: notion_fields.json next to the docs file
                      (i.e. in the bind-mounted reference dir), falling back to DEFAULT_FIELDS

Standard ``HTTP_PROXY``/``HTTPS_PROXY``/``NO_PROXY`` are honoured: the client is built with
httpx's default ``trust_env``, which is what a container behind a corporate proxy needs.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx

from .config import settings

NOTION = "https://api.notion.com/v1"
NOTION_VERSION = "2025-09-03"
TIMEOUT = 30.0

# Used when no mapping file is present: the column names sync/notion_fields.json ships with.
DEFAULT_FIELDS = {
    "clinical": "Description (clinical)",
    "implementation": "Description (implementation)",
    "caveats": "Known Caveats",
    "status": "Status",
}


def configured() -> bool:
    return bool(settings.notion_api_key and settings.notion_database_id)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.notion_api_key}",
        "Notion-Version": NOTION_VERSION,
    }


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT)


def fields_path() -> Path:
    """The column mapping's location: NOTION_FIELDS_FILE, else beside notion_docs.json."""
    if settings.notion_fields_file:
        return Path(settings.notion_fields_file)
    return Path(settings.reference_notion_docs_file).parent / "notion_fields.json"


def load_fields() -> dict[str, str]:
    """The mapping, or the built-in default when no file is there.

    An explicitly configured NOTION_FIELDS_FILE that does not exist is an error, not a
    silent fallback: it means the operator meant a mapping this export never used.
    """
    path = fields_path()
    if path.exists():
        return json.loads(path.read_text())
    if settings.notion_fields_file:
        raise FileNotFoundError(f"NOTION_FIELDS_FILE {path} does not exist")
    return dict(DEFAULT_FIELDS)


def _plain_text(rich: list | None) -> str | None:
    text = "".join((t.get("plain_text") or "") for t in (rich or [])).strip()
    return text or None


def _flatten_page(page: dict, fields: dict[str, str]) -> tuple[str, dict] | None:
    """One Notion page -> (title, doc dict in the shape api/importer.py applies)."""
    props = page.get("properties") or {}
    title = next(
        (_plain_text(p.get("title")) for p in props.values() if p.get("type") == "title"),
        None,
    )
    if not title:
        return None
    doc: dict[str, str | None] = {}
    for key in ("clinical", "implementation", "caveats"):
        prop = props.get(fields.get(key, ""), {})
        doc[key] = _plain_text(prop.get("rich_text")) if prop.get("type") == "rich_text" else None
    status_prop = props.get(fields.get("status", ""), {})
    doc["status"] = (
        (status_prop.get("status") or {}).get("name")
        if status_prop.get("type") == "status"
        else None
    )
    doc["url"] = page.get("url") or f"https://www.notion.so/{page['id'].replace('-', '')}"
    return title, doc


def fetch_notion_docs(client: httpx.Client) -> dict[str, dict]:
    """All pages of the documentation database, flattened per the field mapping.

    The 2025-09-03 API queries *data sources*, not databases, so the database's first data
    source is resolved on every fetch (it is stable, but this keeps the code stateless).
    """
    fields = load_fields()
    r = client.get(f"{NOTION}/databases/{settings.notion_database_id}", headers=_headers())
    r.raise_for_status()
    sources = r.json().get("data_sources") or []
    if not sources:
        raise RuntimeError("Notion database exposes no data source")
    ds_id = sources[0]["id"]

    docs: dict[str, dict] = {}
    cursor: str | None = None
    while True:
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = client.post(f"{NOTION}/data_sources/{ds_id}/query", headers=_headers(), json=body)
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            flat = _flatten_page(page, fields)
            if flat:
                docs[flat[0]] = flat[1]
        if not data.get("has_more"):
            return docs
        cursor = data.get("next_cursor")


def pull_notion_docs() -> int | None:
    """Fetch the export and write it to ``reference_notion_docs_file``.

    Returns the number of documented concepts, or None when Notion is not configured (a
    deployment that documents nothing). Every failure past that point propagates: callers
    must not fall back to whatever stale file happens to lie in the reference dir.
    """
    if not configured():
        return None
    with _client() as client:
        docs = fetch_notion_docs(client)
    path = Path(settings.reference_notion_docs_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(docs, indent=1, sort_keys=True))
    return len(docs)
