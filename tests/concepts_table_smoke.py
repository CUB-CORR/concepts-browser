"""Concepts-table smoke test. Run: uv run python tests/concepts_table_smoke.py

Proves `/concepts/table` — the server-side sorted, filtered, paginated concept list:

* the default order is most-used first, ties broken by the longer documentation (seeded so the
  tiebreaker is the only thing that can decide the pair);
* the S/M/L bucket sits exactly where `services.doc_size` says it does, and the character
  count it is computed from is never served;
* the status filter, its `(none)` bucket and the facet counts that feed the control;
* the search covers documentation text, not only names;
* paging is stable — the pages of a sort partition the sorted whole, with nothing seen twice;
* "most used by me" is the caller's own reads, available to a plain reader;
* nothing in a non-admin's response says who read anything;
* the as-of date lens still moves version/last-edited, and declares the columns it cannot move.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "concepts_table.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough-to-be-ok"
os.environ["APP_SHARED_SECRET"] = "app-secret"
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["LDAP_ENABLED"] = "false"

from datetime import datetime, timedelta  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import security, services  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import Concept, User, _utcnow  # noqa: E402

NS_Z49 = {"type": "native_dynamic", "table_name": "diagnoses",
          "where_clause": "code LIKE 'Z49%'"}

APP = {"x-app-secret": "app-secret"}


def _login(client, username, password):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"authorization": f"Bearer {r.json()['access_token']}"}


PROJECT = "study-x"


def _read(client, headers, path, expect=200):
    """A read that counts as usage: the user calling the API themselves, naming a project.
    Reads the web app makes while somebody browses are not usage — see `_app_read`."""
    r = client.get(path, headers=headers, params={"project": PROJECT})
    assert r.status_code == expect, r.text
    return r


def _app_read(client, headers, path, expect=200):
    """A read the web app makes on the user's behalf. Logged, never counted (api/usage.py)."""
    r = client.get(path, headers={**headers, **APP}, params={"project": "internal"})
    assert r.status_code == expect, r.text
    return r


def _table(client, headers, **params):
    r = client.get(
        "/concepts/table",
        headers={**headers, **APP},
        params={"project": "internal", **params},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _publish(client, headers, name, definition=NS_Z49):
    r = client.post("/concepts", json={"name": name}, headers={**headers, **APP})
    assert r.status_code == 201, r.text
    concept_id = r.json()["id"]
    r = client.post(
        f"/concept/corr_v1/{name}/drafts",
        headers={**headers, **APP},
        json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
              "json": definition, "message": "m"},
    )
    assert r.status_code == 201, r.text
    draft_id = r.json()["id"]
    r = client.post(
        f"/concept/corr_v1/{name}/drafts/{draft_id}/publish",
        headers={**headers, **APP},
        json={"change_type": "improvement", "message": "m"},
    )
    assert r.status_code == 200, r.text
    return concept_id


with TestClient(app) as client:
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

    # Four concepts. `tie_long` and `tie_short` are read the same number of times and differ
    # only in how much documentation they carry — the pair the tiebreaker is proven on.
    ids = {
        name: _publish(client, admin_h, name)
        for name in ("busy", "quiet", "tie_long", "tie_short", "undocumented")
    }

    # --- documentation, at the bucket boundaries ------------------------------------------
    # S/M and M/L are half-open below the threshold, so the boundary character count is the
    # *larger* bucket: 399 chars is S, 400 is M, 1499 is M, 1500 is L.
    with SessionLocal() as db:
        def doc(name, clinical, implementation="", caveats="", status=None):
            c = db.get(Concept, ids[name])
            c.doc_clinical = clinical or None
            c.doc_implementation = implementation or None
            c.doc_caveats = caveats or None
            c.doc_status = status
        doc("busy", "b" * 100, status="In Production")           # S
        doc("quiet", "q" * 200, "q" * 200, status="Draft")       # 400 -> M
        doc("tie_long", "t" * 800, "t" * 700, status="Draft")    # 1500 -> L
        doc("tie_short", "t" * 199, "t" * 200)                   # 399 -> S, no status
        # `undocumented` keeps all three fields NULL.
        db.commit()

    assert services.doc_size(0) is None and services.doc_size(None) is None
    assert services.doc_size(399) == "S" and services.doc_size(400) == "M"
    assert services.doc_size(1499) == "M" and services.doc_size(1500) == "L"

    # --- reads: busy 3, tie_long 2, tie_short 2, quiet 1, undocumented 0 -------------------
    # A project for the external reads to name.
    assert client.post(
        "/projects", headers={**admin_h, **APP}, json={"name": PROJECT, "accept_license": True}
    ).status_code == 201
    for _ in range(3):
        _read(client, reader_h, "/concept/corr_v1/busy")
    for _ in range(2):
        _read(client, reader_h, "/concept/corr_v1/tie_long")
    for _ in range(2):
        _read(client, admin_h, "/concept/corr_v1/tie_short")
    _read(client, reader_h, "/concept/corr_v1/quiet")

    # --- default sort: usage desc, then documentation length desc -------------------------
    page = _table(client, reader_h)
    order = [r["name"] for r in page["rows"]]
    assert order == ["busy", "tie_long", "tie_short", "quiet", "undocumented"], order
    # The tie is decided by documentation alone: both were read twice.
    by_name = {r["name"]: r for r in page["rows"]}
    assert by_name["tie_long"]["usage_reads"] == by_name["tie_short"]["usage_reads"] == 2, page
    assert by_name["busy"]["usage_reads"] == 3, page
    assert by_name["undocumented"]["usage_reads"] == 0, page
    assert page["total"] == 5 and page["page"] == 1 and page["pages"] == 1, page
    assert page["degraded"] == [], page

    # Browsing `undocumented` in the app does not make it used, here or anywhere: the column
    # counts concepts pulled out of the repository, not pages opened in it.
    for _ in range(5):
        _app_read(client, reader_h, "/concept/corr_v1/undocumented")
    after_browsing = {r["name"]: r for r in _table(client, reader_h)["rows"]}
    assert after_browsing["undocumented"]["usage_reads"] == 0, after_browsing
    assert [r for r in after_browsing] == order, after_browsing

    # --- the S/M/L column, and the count behind it staying behind it ----------------------
    assert by_name["busy"]["doc_size"] == "S", by_name
    assert by_name["tie_short"]["doc_size"] == "S", by_name
    assert by_name["quiet"]["doc_size"] == "M", by_name
    assert by_name["tie_long"]["doc_size"] == "L", by_name
    assert by_name["undocumented"]["doc_size"] is None, by_name
    assert not any("chars" in key or "doc_length" in key for key in by_name["busy"]), by_name

    # Sorting the column sorts by the underlying count, not by the letter.
    docsorted = [r["name"] for r in _table(client, reader_h, sort="documentation")["rows"]]
    assert docsorted == ["tie_long", "quiet", "tie_short", "busy", "undocumented"], docsorted
    ascending = [
        r["name"] for r in _table(client, reader_h, sort="documentation", dir="asc")["rows"]
    ]
    assert ascending[0] == "undocumented" and ascending[-1] == "tie_long", ascending

    # --- status filter and facets ----------------------------------------------------------
    facets = {f["value"]: f["count"] for f in page["statuses"]}
    assert facets == {"Draft": 2, "In Production": 1, "(none)": 2}, facets
    drafts = _table(client, reader_h, status="Draft")
    assert sorted(r["name"] for r in drafts["rows"]) == ["quiet", "tie_long"], drafts
    assert drafts["total"] == 2, drafts
    # The facet list is computed ignoring the status filter, so the others stay offerable.
    assert {f["value"] for f in drafts["statuses"]} == {"Draft", "In Production", "(none)"}
    both = _table(client, reader_h, status=["Draft", "In Production"])
    assert both["total"] == 3, both
    unset = _table(client, reader_h, status="(none)")
    assert sorted(r["name"] for r in unset["rows"]) == ["tie_short", "undocumented"], unset

    # --- search reaches into the documentation text ----------------------------------------
    with SessionLocal() as db:
        db.get(Concept, ids["quiet"]).doc_caveats = "beware the haemofiltration edge case"
        db.commit()
    hit = _table(client, reader_h, q="haemofiltration")
    assert [r["name"] for r in hit["rows"]] == ["quiet"], hit
    # …and still by name and description.
    assert [r["name"] for r in _table(client, reader_h, q="tie_")["rows"]] == [
        "tie_long", "tie_short"
    ]
    assert _table(client, reader_h, q="nothing matches this")["total"] == 0

    # --- pagination is stable ---------------------------------------------------------------
    whole = [r["name"] for r in _table(client, reader_h, page_size=200)["rows"]]
    paged = []
    for n in (1, 2, 3):
        p = _table(client, reader_h, page=n, page_size=2)
        assert p["pages"] == 3 and p["total"] == 5, p
        paged += [r["name"] for r in p["rows"]]
    assert paged == whole, (paged, whole)
    assert len(set(paged)) == len(paged), paged

    # --- most used by me, for a plain reader -------------------------------------------------
    # `tie_short` was read only by the admin, so it is not the reader's at all.
    mine = _table(client, reader_h, sort="mine")
    assert [r["name"] for r in mine["rows"]][:3] == ["busy", "tie_long", "quiet"], mine
    mine_by_name = {r["name"]: r for r in mine["rows"]}
    assert mine_by_name["busy"]["my_reads"] == 3, mine
    assert mine_by_name["tie_short"]["my_reads"] == 0, mine
    # The total is not the caller's share: tie_short is read twice by somebody else.
    assert mine_by_name["tie_short"]["usage_reads"] == 2, mine

    # --- no identity leak --------------------------------------------------------------------
    assert all(r["usage_users"] is None for r in mine["rows"]), mine
    leaky = {"user", "users", "user_id", "username", "readers", "last_used_by"}
    assert not (set(mine["rows"][0]) & leaky), mine["rows"][0]
    # An admin does get the distinct-reader count.
    admin_rows = {r["name"]: r for r in _table(client, admin_h)["rows"]}
    assert admin_rows["busy"]["usage_users"] == 1, admin_rows
    assert admin_rows["tie_long"]["usage_users"] == 1, admin_rows

    # --- last edited / by, and the extra columns ----------------------------------------------
    assert admin_rows["busy"]["last_edited_by"] == "admin", admin_rows
    assert admin_rows["busy"]["last_edited_at"] is not None, admin_rows
    assert admin_rows["busy"]["version"] == 1, admin_rows
    assert admin_rows["busy"]["names_count"] == 1, admin_rows
    editor_sorted = _table(client, admin_h, sort="editor", dir="asc")
    assert all(r["last_edited_by"] == "admin" for r in editor_sorted["rows"]), editor_sorted
    assert [r["name"] for r in _table(client, admin_h, sort="name", dir="asc")["rows"]] == [
        "busy", "quiet", "tie_long", "tie_short", "undocumented"
    ]

    # --- the as-of date lens -------------------------------------------------------------------
    before = (_utcnow() - timedelta(days=1)).isoformat()
    past = _table(client, reader_h, date=before)
    assert past["total"] == 0, past  # no name was registered yet
    now = _table(client, reader_h, date=_utcnow().isoformat())
    assert now["total"] == 5, now
    # Usage, documentation and status are concept-level and unversioned: the lens cannot move
    # them, and the response says so rather than implying it measured the past.
    assert now["degraded"] == ["usage", "documentation", "status"], now

    # --- source / type / configured filters, and their facets ------------------------------
    unconfigured_id = client.post(
        "/concepts", json={"name": "no_config"}, headers={**admin_h, **APP}
    ).json()["id"]
    assert unconfigured_id
    full = _table(client, admin_h, page_size=200)
    assert {f["value"]: f["count"] for f in full["sources"]} == {"cub_hdp": 5}, full["sources"]
    assert {f["value"]: f["count"] for f in full["types"]} == {"native_dynamic": 5}, full["types"]
    assert _table(client, admin_h, configured="configured")["total"] == 5
    assert [r["name"] for r in _table(client, admin_h, configured="unconfigured")["rows"]] == [
        "no_config"
    ]
    assert _table(client, admin_h, source="cub_hdp")["total"] == 5
    assert _table(client, admin_h, source="nope")["total"] == 0
    assert _table(client, admin_h, type="native_dynamic")["total"] == 5
    assert _table(client, admin_h, type="native_static")["total"] == 0

    # --- ids for the export ---------------------------------------------------------------------
    withids = _table(client, admin_h, q="tie_", include_ids=True)
    assert withids["ids"] == sorted([ids["tie_long"], ids["tie_short"]]), withids
    assert _table(client, admin_h)["ids"] is None

    # --- gates ------------------------------------------------------------------------------------
    assert client.get("/concepts/table", params={"project": "internal"}).status_code == 401
    assert client.get(
        "/concepts/table", headers={**reader_h, **APP},
        params={"project": "internal", "sort": "nope"},
    ).status_code == 422
    assert client.get(
        "/concepts/table", headers={**reader_h, **APP},
        params={"project": "internal", "taxonomy": "nope"},
    ).status_code == 404

    # --- retired names ------------------------------------------------------------------------------
    with SessionLocal() as db:
        from api.models import ConceptTaxonomy
        ct = db.scalar(
            select(ConceptTaxonomy).where(ConceptTaxonomy.identifier == "undocumented")
        )
        ct.deprecated_at = datetime(2000, 1, 1)
        db.commit()
    assert _table(client, reader_h)["total"] == 5
    retired = _table(client, reader_h, include_deprecated=True)
    assert retired["total"] == 6
    assert any(r["deprecated_at"] for r in retired["rows"]), retired

    # --- the clinical excerpt the Description column shows ---------------------------------
    # The column is one truncated line, so the row carries one truncated line — never the
    # prose itself, which is the largest thing a concept owns.
    long_text = ("Serum sodium concentration measured in venous blood, "
                 "reported in millimoles per litre. " * 6)
    with SessionLocal() as db:
        db.get(Concept, ids["busy"]).doc_clinical = long_text
        db.get(Concept, ids["quiet"]).doc_clinical = "  Short one.\nWith a newline.  "
        db.get(Concept, ids["tie_short"]).doc_clinical = None
        db.commit()
    excerpts = {r["name"]: r["doc_clinical_excerpt"] for r in _table(client, reader_h)["rows"]}
    assert excerpts["busy"].endswith("…"), excerpts["busy"]
    assert len(excerpts["busy"]) <= services.DOC_EXCERPT_CHARS + 1, excerpts["busy"]
    assert long_text.startswith(excerpts["busy"][:40]), excerpts["busy"]
    # Nothing in the response carries the whole text.
    assert long_text not in str(_table(client, reader_h)), "full documentation text served"
    # A short one is served whole, flattened to a single line.
    assert excerpts["quiet"] == "Short one. With a newline.", excerpts["quiet"]
    assert excerpts["tie_short"] is None, excerpts

    # --- search ranking ---------------------------------------------------------------------
    # A name hit always beats a hit that only appears in the prose, and within the name the
    # ladder is exact > prefix > substring > fuzzy. The fixtures below are read in the
    # *opposite* order to that ranking, so only relevance can produce it.
    for name in ("sodium", "sodium_intake", "lab_blood_sodium", "serum_sodium_level",
                 "natrium_sodiun", "potassium_ratio"):
        _publish(client, admin_h, name)
    with SessionLocal() as db:
        prose = db.scalar(select(Concept).join(
            ConceptTaxonomy, ConceptTaxonomy.concept_id == Concept.id
        ).where(ConceptTaxonomy.identifier == "potassium_ratio"))
        prose.doc_clinical = "Computed against the serum sodium level of the same draw."
        db.commit()
    # The prose-only match is the most-read concept in the taxonomy: usage must not save it.
    for _ in range(50):
        _read(client, reader_h, "/concept/corr_v1/potassium_ratio")

    ranked = [r["name"] for r in _table(client, reader_h, q="sodium")["rows"]]
    assert ranked[0] == "sodium", ranked                    # exact
    assert ranked[1] == "sodium_intake", ranked             # prefix
    assert set(ranked[2:4]) == {"lab_blood_sodium", "serum_sodium_level"}, ranked  # substring
    assert ranked[4] == "natrium_sodiun", ranked            # fuzzy: one typo away
    # Everything left over matched the documentation and nothing else, and sits below every
    # name hit no matter how much more it is read.
    assert set(ranked[5:]) == {"potassium_ratio", "busy"}, ranked
    assert ranked[5] == "potassium_ratio", ranked           # among those, most-read first
    # Without the ranking, 50 reads would have put it first.
    assert _table(client, reader_h)["rows"][0]["name"] == "potassium_ratio"

    # Separator-insensitive: identifiers are written with underscores and searched with spaces.
    spaced = [r["name"] for r in _table(client, reader_h, q="blood sodium")["rows"]]
    assert spaced == ["lab_blood_sodium"], spaced
    assert [r["name"] for r in _table(client, reader_h, q="blood_sodium")["rows"]] == spaced

    # Fuzzy: a typo still finds the name, and never outranks a literal hit.
    typo = [r["name"] for r in _table(client, reader_h, q="sodum")["rows"]]
    assert "lab_blood_sodium" in typo and "sodium_intake" in typo, typo
    typo_both = [r["name"] for r in _table(client, reader_h, q="sodiun")["rows"]]
    # `natrium_sodiun` contains the term literally; everything else is a typo away from it.
    assert typo_both[0] == "natrium_sodiun", typo_both
    # Short words get no typo budget at all: at three characters an edit distance of one
    # relates almost any pair, which would make the fuzzy bucket meaningless.
    assert services.fuzzy_budget("sod") == 0 and services.fuzzy_budget("sodium") == 1
    assert not services.fuzzy_name_hit(["sod"], "sad_reading")
    assert services.fuzzy_name_hit(["sodum"], "lab_blood_sodium")
    # Order does not matter — the match is per word, not over the whole string.
    assert services.fuzzy_name_hit(["sodium", "blood"], "lab_blood_sodium")

    # An explicitly sorted column wins over relevance — the reader asked for alphabetical.
    by_name = [r["name"] for r in _table(client, reader_h, q="sodium", sort="name",
                                         dir="asc")["rows"]]
    assert by_name == sorted(by_name), by_name
    assert "potassium_ratio" in by_name, by_name
    # `sort=relevance` without a search falls back to the default order rather than erroring.
    assert _table(client, reader_h, sort="relevance")["rows"][0]["name"] == "potassium_ratio"

    # --- slices partition, which is what makes the scroll append safe -------------------------
    # The infinite scroll appends slice N+1 under slice N, so the two must never overlap and
    # never skip — true only because the sort ends in the unique (identifier, id) pair.
    for params in ({}, {"q": "sodium"}, {"sort": "status", "dir": "asc"}):
        whole = [r["name"] for r in _table(client, reader_h, page_size=200, **params)["rows"]]
        appended = []
        for n in range(1, (len(whole) // 3) + 2):
            appended += [r["name"] for r in _table(client, reader_h, page=n, page_size=3,
                                                   **params)["rows"]]
        assert appended == whole, (params, appended, whole)
        assert len(set(appended)) == len(appended), (params, appended)

print("concepts table smoke: OK")
