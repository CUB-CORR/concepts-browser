"""The reprodICU dataset: derived types, folded units, and the multi-dataset import.

Run: uv run python tests/reprodicu_smoke.py

reprodICU's upstream definitions carry no `type` and keep their units in a separate file, so
this covers the two things the importer derives (api/importer.py) and the schemas that pin
them down (reference/schema/reprodicu_*.json), then boots the app to check that both bundled
datasets land in one pass — including a concept both of them define.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

REFERENCE_VARS = "reference/reprodicu_vars.json"
REFERENCE_UNITS = "reference/reprodicu_units.json"
REFERENCE_POINTERS = "reference/reprodicu_pointers.json"

# A dataset dir of our own, so the import can be tested against entries that must be skipped
# without shipping broken definitions in the reference data.
_dataset_dir = tempfile.mkdtemp()
_upstream = json.load(open(REFERENCE_VARS))
UPSTREAM = dict(_upstream["variables"])
BROKEN = {
    # no `filter`: derived as native_dynamic, and native_dynamic requires one
    "broken_missing_filter": {"path": "timeseries_labs", "column": "Sodium", "is_struct": False},
    # an empty `calculation` still derives as derived_*, where the schema then rejects it —
    # the type rule reads key presence, the schema reads the value
    "broken_empty_calculation": {
        "path": "timeseries_vitals", "column": "x", "is_struct": False,
        "filter": "pl.col('x').is_not_null()", "calculation": "",
    },
}
# reference/vars.json carries one deliberately-invalid entry of its own; every pass validates
# both datasets, so the skipped count covers all three.
PRIMARY_BROKEN = 1
_upstream["variables"] = {**UPSTREAM, **BROKEN}
with open(os.path.join(_dataset_dir, "vars.json"), "w") as f:
    json.dump(_upstream, f)
shutil.copy(REFERENCE_UNITS, os.path.join(_dataset_dir, "units.json"))
shutil.copy(REFERENCE_POINTERS, os.path.join(_dataset_dir, "pointers.json"))

db_path = os.path.join(tempfile.mkdtemp(), "reprodicu.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret"
os.environ["APP_SHARED_SECRET"] = ""
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "true"
os.environ["REFERENCE_DATASETS"] = json.dumps([
    {
        "source": "reprodicu",
        "vars": os.path.join(_dataset_dir, "vars.json"),
        "units": os.path.join(_dataset_dir, "units.json"),
        "pointers": os.path.join(_dataset_dir, "pointers.json"),
    }
])

from fastapi.testclient import TestClient  # noqa: E402

from api.importer import _load_pointers, _load_units, _prepare, _reprodicu_type  # noqa: E402
from api.main import app  # noqa: E402
from api.schema_registry import registry  # noqa: E402

# --- the type rule -------------------------------------------------------------------------

registry.load("reference/schema")
assert set(registry.supported_types("reprodicu")) == {
    "native_dynamic", "native_static", "derived_dynamic", "derived_static",
}, registry.supported_types("reprodicu")

BASE = {"path": "timeseries_vitals", "column": "Heart rate", "is_struct": False,
        "filter": "pl.col('Heart rate').is_not_null()"}
assert _reprodicu_type(BASE) == "native_dynamic"
assert _reprodicu_type({**BASE, "dynamic": False}) == "native_static"
assert _reprodicu_type({**BASE, "dynamic": True}) == "native_dynamic"
assert _reprodicu_type({**BASE, "calculation": "pl.col('a')"}) == "derived_dynamic"
assert _reprodicu_type({**BASE, "calculation": "pl.col('a')", "dynamic": False}) == "derived_static"

# Every shipped variable gets a type it actually validates against — the rule and the schemas
# are two statements of one thing, and this is what says so.
UNITS = _load_units(Path(REFERENCE_UNITS))
PREPARED = _prepare(UPSTREAM, "reprodicu", UNITS)
assert len(PREPARED) == 158, len(PREPARED)
for _name, _def in PREPARED.items():
    _result = registry.validate("reprodicu", _def["type"], _def)
    assert _result.governed and _result.ok, (_name, _result.errors)

# --- schema validation: what must be rejected ----------------------------------------------

VALID = {"type": "native_dynamic", **BASE, "unit": "/min"}
assert registry.validate("reprodicu", "native_dynamic", VALID).ok


def rejected(type_: str, definition: dict) -> list[str]:
    result = registry.validate("reprodicu", type_, definition)
    assert result.governed and not result.ok, (type_, definition)
    return [e["message"] for e in result.errors]


rejected("native_dynamic", {k: v for k, v in VALID.items() if k != "filter"})  # missing required
rejected("native_dynamic", {**VALID, "is_struct": "yes"})                      # wrong type
rejected("native_dynamic", {**VALID, "table_name": "vitals"})                  # cub_hdp's shape
rejected("native_dynamic", {**VALID, "unit": ""})                              # never store a blank
# the discriminator is enforced from the schema side too: a calculation makes a variable
# derived, and `dynamic: false` makes it static, so neither may appear under the other type
rejected("native_dynamic", {**VALID, "calculation": "pl.col('a')"})
rejected("native_dynamic", {**VALID, "dynamic": False})
rejected("native_static", {**VALID, "type": "native_static", "dynamic": True})
rejected("derived_dynamic", {**VALID, "type": "derived_dynamic"})  # no calculation
# and an unknown type is a validation failure, not a pass-through
rejected("native_hourly", VALID)

# A source with no schemas stays pass-through — adding reprodicu's must not change that.
assert registry.validate("some_other_source", "whatever", {"x": 1}).governed is False

# --- units -----------------------------------------------------------------------------

assert UNITS["blood_sodium"] == "mmol/L", UNITS["blood_sodium"]
# upstream writes null/"" for the dimensionless variables, and keeps units for variables
# vars.json no longer defines; neither may reach a definition
assert "blood_inr" not in UNITS and "unit" not in PREPARED["blood_inr"], PREPARED["blood_inr"]
assert "blood_lipase" in json.load(open(REFERENCE_UNITS)) and "blood_lipase" not in PREPARED
assert PREPARED["blood_sodium"]["unit"] == "mmol/L"
# ...and upstream's own keys are passed through untouched, so dropping the two derived ones
# gives back the entry as authored
assert {k: v for k, v in PREPARED["blood_sodium"].items() if k not in ("type", "unit")} \
    == UPSTREAM["blood_sodium"]

# --- the pointers file -----------------------------------------------------------------

POINTERS = _load_pointers(Path(REFERENCE_POINTERS))
# every name it maps is a variable this dataset actually defines, in a taxonomy seed.yaml
# seeds — an entry that is neither would import as nothing and mean nothing
assert set(POINTERS) <= set(UPSTREAM), sorted(set(POINTERS) - set(UPSTREAM))
assert {t for by_tax in POINTERS.values() for t in by_tax} == {"LOINC", "SNOMED"}, POINTERS
assert POINTERS["blood_sodium"] == {"LOINC": ["2951-2"], "SNOMED": ["25197003"]}, \
    POINTERS["blood_sodium"]

# an absent file is a no-op, not an error, and a taxonomy with no identifiers is dropped
# rather than passed on — an empty list would tell `_sync_pointers` to retire the lot
assert _load_pointers(None) == {} and _load_pointers(Path("reference/nope.json")) == {}
_tmp = Path(_dataset_dir) / "edge_pointers.json"
_tmp.write_text(json.dumps({"a": {"LOINC": []}, "b": "nonsense", "c": {"SNOMED": ["x"]}}))
assert _load_pointers(_tmp) == {"c": {"SNOMED": ["x"]}}, _load_pointers(_tmp)

# --- the multi-dataset import ---------------------------------------------------------------

with TestClient(app) as client:  # the lifespan seeds and imports both bundled datasets
    _tok = client.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    client.headers["authorization"] = f"Bearer {_tok['access_token']}"
    _raw_get = client.get
    client.get = lambda url, **kw: _raw_get(
        f"{url}{'&' if '?' in url else '?'}project=internal", **kw
    )

    listed = {c["name"]: c for c in client.get("/concepts").json()}
    # both datasets landed: the primary sample plus every reprodicu variable
    assert set(UPSTREAM) <= set(listed), sorted(set(UPSTREAM) - set(listed))[:10]
    assert "mean_arterial_pressure" in listed, "the primary dataset was not imported"
    # the deliberately broken entries were skipped, not imported half-validated
    for name in BROKEN:
        assert name not in listed, name

    types = {}
    for name in UPSTREAM:
        for t in listed[name]["types"]:
            types[t] = types.get(t, 0) + 1
    assert types == {"native_dynamic": 148, "native_static": 7, "derived_dynamic": 3}, types

    def one(url: str) -> dict:
        body = client.get(url).json()
        assert isinstance(body, list) and len(body) == 1, body
        return body[0]

    sodium = one("/concept/corr_v1/blood_sodium")["sources"]["reprodicu"]
    assert sodium["json"] == PREPARED["blood_sodium"], sodium["json"]
    assert sodium["py"] is None, sodium              # no variables.py for this source
    vi = sodium["version_info"]
    assert vi["source_version"] == 1 and vi["change_type"] == "initial", vi
    assert vi["status"] == "published" and vi["read_only"] is False, vi

    static = one("/concept/corr_v1/admission_type")["sources"]["reprodicu"]
    assert static["json"]["type"] == "native_static" and static["json"]["dynamic"] is False, static
    derived = one("/concept/corr_v1/mean_bp_combined")["sources"]["reprodicu"]
    assert derived["json"]["type"] == "derived_dynamic" and derived["json"]["calculation"], derived

    # A concept both datasets define carries a config per source. `version_no` is a per-concept
    # sequence shared by its sources (api/models.py), so the second one continues it at 2 —
    # while still being that source's "initial" version.
    shared = one("/concept/corr_v1/heart_rate")
    assert set(shared["sources"]) == {"cub_hdp", "reprodicu"}, shared["sources"]
    assert shared["sources"]["cub_hdp"]["version_info"]["source_version"] == 1
    repro = shared["sources"]["reprodicu"]["version_info"]
    assert repro["source_version"] == 2 and repro["change_type"] == "initial", repro

    # The pointers file put every name it maps on the right concept, import-owned so a later
    # pass keeps maintaining them, and it named nothing it was not asked to.
    def coded(name: str) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for n in one(f"/concept/corr_v1/{name}")["names"]:
            if n["taxonomy"] == "corr_v1" or n["deprecated_at"]:
                continue
            assert n["origin"] == "import", n  # import-owned, so later passes maintain them
            out.setdefault(n["taxonomy"], []).append(n["identifier"])
        return {t: sorted(v) for t, v in out.items()}

    assert coded("blood_sodium") == POINTERS["blood_sodium"], coded("blood_sodium")
    assert coded("spo2") == POINTERS["spo2"], coded("spo2")
    # a variable the file says nothing about keeps its corr_v1 name and nothing else
    assert coded("admission_type") == {}, coded("admission_type")

    # and nothing beyond the file was named: listing a coding taxonomy returns exactly the
    # identifiers it maps and no others, so the cub_hdp sample dataset gained none
    for _tax in ("LOINC", "SNOMED"):
        _listed = {c["name"] for c in client.get(f"/concepts?taxonomy={_tax}").json()}
        _want = {i for p in POINTERS.values() for i in p.get(_tax, [])}
        assert _listed == _want, (_tax, _listed ^ _want)

    # the schema folder is what /sources reports from
    meta = client.get("/sources/reprodicu/types").json()
    assert meta["schema_governed"] is True, meta
    assert set(meta["supported_types"]) == {
        "native_dynamic", "native_static", "derived_dynamic", "derived_static",
    }, meta
    schema = client.get("/sources/reprodicu/schema/derived_static").json()
    assert schema["$id"].endswith("/src/reprodicu/derived_static/schema.json"), schema["$id"]

    # idempotency: a second pass over unchanged files writes nothing for either dataset
    from api.importer import import_reference
    stats = import_reference()
    assert stats is not None and (stats.imported, stats.updated) == (0, 0), stats
    assert stats.skipped_invalid == len(BROKEN) + PRIMARY_BROKEN, stats
    assert len(client.get("/concepts").json()) == len(listed)

    # ...and a source whose configs are gone is filled in again on the next pass, which is what
    # adding a dataset to a running deployment looks like: the concepts already exist, so only
    # the missing source's definitions are written.
    from sqlalchemy import delete, select

    from api.db import SessionLocal
    from api.models import Config, Source

    with SessionLocal() as db:
        repro_id = db.scalar(select(Source.id).where(Source.key == "reprodicu"))
        db.execute(delete(Config).where(Config.source_id == repro_id))
        db.commit()
    stats = import_reference()
    assert stats is not None and stats.imported == len(UPSTREAM), stats
    assert stats.skipped_invalid == len(BROKEN) + PRIMARY_BROKEN, stats
    assert set(one("/concept/corr_v1/heart_rate")["sources"]) == {"cub_hdp", "reprodicu"}

print("REPRODICU SMOKE OK")
