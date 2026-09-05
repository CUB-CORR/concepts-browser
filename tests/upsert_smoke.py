"""The upsert reference import. Run: uv run python tests/upsert_smoke.py

The production import path: it keys on one taxonomy that must be 1:1 for the incoming names,
creates what is new, mints a `sync` version for what changed, leaves identical definitions
alone, and keeps the taxonomy names it owns in step with upstream — including the ones that
point at several concepts. Everything a person did by hand (a name they added, a concept they
retired) has to come through untouched, which is most of what is checked here.

Drives ``api/importer.py`` directly against a temporary reference directory, with a stand-in
for the deployment's ``special_vars`` overlay (see api/special_vars.py) supplying generated
variables and their pointers.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_ref = tempfile.mkdtemp()
VARS = os.path.join(_ref, "vars.json")
PY = os.path.join(_ref, "variables.py")

db_path = os.path.join(tempfile.mkdtemp(), "upsert.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["REFERENCE_VARS_FILE"] = VARS
os.environ["REFERENCE_PYTHON_FILE"] = PY
os.environ["REFERENCE_DATASETS"] = "[]"          # the primary dataset alone
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"  # the boot import stays out of the way
os.environ["FILE_DIR"] = tempfile.mkdtemp()

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import select  # noqa: E402

from api import importer  # noqa: E402
from api.config import settings  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import ConceptTaxonomy, Taxonomy  # noqa: E402


def nd(where: str) -> dict:
    return {"type": "native_dynamic", "table_name": "diagnoses", "where_clause": where}


def write_vars(variables: dict) -> None:
    with open(VARS, "w") as f:
        json.dump({"variables": variables}, f)


def write_py(source: str) -> None:
    with open(PY, "w") as f:
        f.write(source)


def overlay(variables: dict, pointers: dict) -> None:
    """Stand in for the deployment's special_vars module for the next import pass."""
    importer.load_special_variables = lambda: (variables, pointers)


UPSTREAM = {
    "heart_rate": nd("code = 'HR'"),
    "blood_sodium": nd("code = 'NA'"),
    "any_dialysis": nd("code LIKE 'Z49%'"),
}
MED = {"med_ipratropium": {"type": "medication", "drug": "ipratropium"}}

write_vars(UPSTREAM)
write_py("def heart_rate(var, cohort):\n    return cohort\n")
overlay(MED, {"med_ipratropium": {"ATC": ["R03BB01"]}})

with TestClient(app) as c:
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    c.headers["authorization"] = f"Bearer {tok['access_token']}"
    _raw_get = c.get
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    def one(url: str) -> dict:
        body = c.get(url).json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    # The boot import is switched off above so every pass below is driven (and counted) here;
    # the passes themselves must run, so re-enable the switch they check.
    settings.import_reference_on_first_run = True

    def pointers(taxonomy: str, identifier: str | None = None) -> list[ConceptTaxonomy]:
        with SessionLocal() as db:
            tax = db.scalar(select(Taxonomy).where(Taxonomy.key == taxonomy))
            q = select(ConceptTaxonomy).where(ConceptTaxonomy.taxonomy_id == tax.id)
            if identifier is not None:
                q = q.where(ConceptTaxonomy.identifier == identifier)
            return list(db.scalars(q.order_by(ConceptTaxonomy.id)))

    # --- first pass: everything is new ----------------------------------------------------------
    stats = importer.import_reference()
    assert stats is not None, stats
    assert (stats.imported, stats.updated, stats.unchanged) == (4, 0, 0), stats
    assert stats.with_python == 1 and stats.pointers_added == 1, stats
    assert stats.missing_upstream == [], stats

    listed = {x["name"]: x for x in c.get("/concepts").json()}
    assert set(listed) == set(UPSTREAM) | set(MED), sorted(listed)
    assert all(x["origin"] == "import" for x in listed.values()), listed
    hr = one("/concept/corr_v1/heart_rate")
    assert hr["version"] == 1, hr
    assert hr["sources"]["cub_hdp"]["version_info"]["change_type"] == "initial", hr
    # The generated variable came with the ATC code its mapping file lists.
    med_id = listed["med_ipratropium"]["id"]
    atc = pointers("ATC", "R03BB01")
    assert [(p.concept_id, p.origin, p.deprecated_at) for p in atc] == [(med_id, "import", None)]
    assert one("/concept/ATC/R03BB01")["id"] == med_id

    # --- second pass over unchanged files: nothing is written -------------------------------------
    stats = importer.import_reference()
    assert (stats.imported, stats.updated, stats.unchanged) == (0, 0, 4), stats
    assert (stats.pointers_added, stats.pointers_deprecated) == (0, 0), stats
    assert one("/concept/corr_v1/heart_rate")["version"] == 1

    # --- a definition that moved upstream gets a version ------------------------------------------
    write_vars({**UPSTREAM, "blood_sodium": nd("code = 'NA+'")})
    stats = importer.import_reference()
    assert (stats.imported, stats.updated, stats.unchanged) == (0, 1, 3), stats
    sodium = one("/concept/corr_v1/blood_sodium")
    assert sodium["version"] == 2, sodium
    vi = sodium["sources"]["cub_hdp"]["version_info"]
    assert vi["change_type"] == "sync" and vi["source_version"] == 2, vi
    assert vi["message"] == "Automated sync from upstream reference", vi
    assert sodium["sources"]["cub_hdp"]["json"]["where_clause"] == "code = 'NA+'"
    # v1 is still there — the import appends, it never rewrites.
    assert one("/concept/corr_v1/blood_sodium?v=1")["sources"]["cub_hdp"]["json"]["where_clause"] \
        == "code = 'NA'"
    assert [h["version"] for h in c.get("/concept/corr_v1/blood_sodium/history").json()] == [2, 1]

    # A changed python snippet is a change too, on its own.
    write_py("def heart_rate(var, cohort):\n    return cohort.head()\n")
    stats = importer.import_reference()
    assert (stats.imported, stats.updated, stats.unchanged) == (0, 1, 3), stats
    assert one("/concept/corr_v1/heart_rate")["sources"]["cub_hdp"]["py"].endswith("head()")

    # --- a new variable ------------------------------------------------------------------------------
    write_vars({**UPSTREAM, "blood_sodium": nd("code = 'NA+'"), "lactate": nd("code = 'LAC'")})
    stats = importer.import_reference()
    assert (stats.imported, stats.updated, stats.unchanged) == (1, 0, 4), stats
    assert one("/concept/corr_v1/lactate")["version"] == 1

    # --- 1:many pointers: one ATC code covering two concepts ------------------------------------------
    overlay(
        {**MED, "med_fenoterol": {"type": "medication", "drug": "fenoterol"}},
        {
            "med_ipratropium": {"ATC": ["R03BB01", "R03AL01"]},
            "med_fenoterol": {"ATC": ["R03AC04", "R03AL01"]},
        },
    )
    stats = importer.import_reference()
    assert stats.imported == 1, stats           # med_fenoterol
    assert stats.pointers_added == 3, stats     # R03AL01 twice, plus R03AC04
    group = c.get("/concept/ATC/R03AL01").json()
    assert len(group) == 2, group
    assert {x["group_size"] for x in c.get("/concepts?taxonomy=ATC").json() if x["name"] == "R03AL01"} \
        == {2}
    # A shared identifier is fine; asking for a version through it is not.
    assert c.get("/concept/ATC/R03AL01?v=1").status_code == 400

    # --- a pointer upstream dropped is retired, one it never owned is not -----------------------------
    # A name a person added by hand, in a taxonomy the import also writes to.
    med_fenoterol = one("/concept/corr_v1/med_fenoterol")["id"]
    r = c.post(
        f"/concept/id/{med_fenoterol}/pointers",
        json={"taxonomy": "ATC", "identifier": "R03CC04"},
    )
    assert r.status_code == 201, r.text

    overlay(
        {**MED, "med_fenoterol": {"type": "medication", "drug": "fenoterol"}},
        {
            "med_ipratropium": {"ATC": ["R03BB01"]},         # R03AL01 dropped upstream
            "med_fenoterol": {"ATC": ["R03AC04", "R03AL01"]},
        },
    )
    stats = importer.import_reference()
    assert (stats.pointers_added, stats.pointers_deprecated) == (0, 1), stats
    remaining = c.get("/concept/ATC/R03AL01").json()
    assert [x["id"] for x in remaining] == [med_fenoterol], remaining
    # The hand-added name is untouched, and still owned by the person who added it.
    hand = pointers("ATC", "R03CC04")
    assert [(p.origin, p.deprecated_at) for p in hand] == [("user", None)], hand

    # --- adoption: a user pointer that is exactly what the import wants ---------------------------------
    r = c.post(
        f"/concept/id/{med_fenoterol}/pointers",
        json={"taxonomy": "ATC", "identifier": "R03CC63"},
    )
    assert r.status_code == 201, r.text
    overlay(
        {**MED, "med_fenoterol": {"type": "medication", "drug": "fenoterol"}},
        {
            "med_ipratropium": {"ATC": ["R03BB01"]},
            "med_fenoterol": {"ATC": ["R03AC04", "R03AL01", "R03CC63"]},
        },
    )
    stats = importer.import_reference()
    assert stats.pointers_adopted == 1 and stats.pointers_added == 0, stats
    adopted = pointers("ATC", "R03CC63")
    assert [(p.origin, p.deprecated_at) for p in adopted] == [("import", None)], adopted
    # …taken over, not duplicated
    assert len(adopted) == 1, adopted

    # --- a taxonomy nobody seeded is skipped, the variable is not ----------------------------------------
    overlay(
        {**MED, "med_fenoterol": {"type": "medication", "drug": "fenoterol"}},
        {"med_fenoterol": {"NOT_SEEDED": ["x"], "ATC": ["R03AC04", "R03AL01", "R03CC63"]}},
    )
    stats = importer.import_reference()
    assert stats.skipped_invalid == 0 and stats.unchanged > 0, stats
    assert one("/concept/corr_v1/med_fenoterol")["version"] >= 1

    # --- an ambiguous key name is skipped, not guessed at -------------------------------------------------
    r = c.post("/concepts", json={"name": "lactate", "confirm_group": True})
    assert r.status_code == 201, r.text
    write_vars({
        **UPSTREAM, "blood_sodium": nd("code = 'NA+'"), "lactate": nd("code = 'LAC2'"),
    })
    stats = importer.import_reference()
    assert stats.skipped_ambiguous == 1, stats
    assert (stats.imported, stats.updated) == (0, 0), stats
    # …and the change upstream wanted did not land on either member
    both = c.get("/concept/corr_v1/lactate").json()
    assert len(both) == 2, both
    assert [m for m in both if m["sources"]][0]["sources"]["cub_hdp"]["json"]["where_clause"] \
        == "code = 'LAC'"

    # --- the ops endpoint the sidecar calls ----------------------------------------------------------------
    # Guarded by a shared secret, upsert by default, and it hands the pass's counts back.
    assert c.post("/internal/reimport").status_code == 404  # no token configured yet
    settings.internal_token = "sidecar-token"
    assert c.post("/internal/reimport").status_code == 403
    assert c.post("/internal/reimport", headers={"x-internal-token": "wrong"}).status_code == 403
    r = c.post("/internal/reimport", headers={"x-internal-token": "sidecar-token"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok" and body["mode"] == "upsert", body
    assert (body["imported"], body["updated"]) == (0, 0) and body["unchanged"] > 0, body
    assert "pointers_added" in body and "missing_upstream" in body, body
    settings.internal_token = ""

    # --- a variable upstream dropped is reported, never removed --------------------------------------------
    write_vars({k: v for k, v in UPSTREAM.items() if k != "any_dialysis"})
    stats = importer.import_reference()
    assert "any_dialysis" in stats.missing_upstream, stats.missing_upstream
    assert "lactate" in stats.missing_upstream, stats.missing_upstream
    assert one("/concept/corr_v1/any_dialysis")["version"] == 1, "the import removed a concept"

print("UPSERT SMOKE OK")
