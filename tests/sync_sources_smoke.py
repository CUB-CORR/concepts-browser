"""The sidecar staging more than one source. Run: uv run python tests/sync_sources_smoke.py

Two shapes have to work: the primary source (variables.py, its data files, the completion
surface) and a **definitions-only** source such as reprodICU, which has none of those. The
point of the second case is that the passes it has nothing for are skipped *quietly* — a
source without a variables.py is the normal shape, not a degraded one, so a sidecar that
warned about it every cycle would train its operator to ignore the log.

Nothing here talks to GitHub: the repo is a fake tree and the fetches are stubbed, which is
also what makes the "which paths did it ask for" assertions possible.
"""
import logging
import shutil
import os
import sys
import tempfile
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "sync"))

TARGET = Path(tempfile.mkdtemp()) / "reference"
os.environ["TARGET_DIR"] = str(TARGET)
os.environ["EXTRA_SOURCES"] = "reprodicu=src/corr_vars/sources/reprodicu/mapping"

import sync  # noqa: E402  — reads its configuration from the env at import

CUB = "src/corr_vars/sources/cub_hdp/mapping"
REPRO = "src/corr_vars/sources/reprodicu/mapping"

assert sync.EXTRA_SOURCES == [("reprodicu", REPRO)], sync.EXTRA_SOURCES
# malformed entries are dropped, not taken as the repo root
assert sync._parse_extra_sources("  , nodir, =x, k=/a/b/ ") == [("k", "a/b")]

VARIABLES_PY = '''
import polars as pl
from pathlib import Path

POSTCODE = Path(__file__).parent / "postcode" / "map.csv"


def postcodes(var, cohort):
    return pl.read_csv(POSTCODE)
'''

BLOBS = {
    "sha-cub-vars": b'{"variables": {}}',
    "sha-cub-py": VARIABLES_PY.encode(),
    "sha-cub-csv": b"plz,state\n10117,BE\n",
    "sha-repro-vars": b'{"variables": {"blood_sodium": {}}}',
    "sha-repro-units": b'{"blood_sodium": "mmol/L"}',
}
FULL_TREE = {
    f"{CUB}/vars.json": "sha-cub-vars",
    f"{CUB}/variables.py": "sha-cub-py",
    f"{CUB}/postcode/map.csv": "sha-cub-csv",
    f"{REPRO}/vars.json": "sha-repro-vars",
    f"{REPRO}/units.json": "sha-repro-units",
}

reimports: list[int] = []
pyapi_calls: list[str] = []
fetched: list[str] = []
tree: dict[str, str] = {}

sync.list_tree = lambda client, ref: dict(tree)
sync.fetch_blob = lambda client, sha: BLOBS[sha]
sync.trigger_reimport = lambda client: reimports.append(1)
# pyapi generation has its own test (tests/pyapi_smoke.py); here only *whether* it runs matters.
sync.sync_pyapi = lambda client, sha, tree_: pyapi_calls.append(sha)


def _fetch_file(client, path, ref):
    fetched.append(path)
    return BLOBS[tree[path]]


sync.fetch_file = _fetch_file


class Records(logging.Handler):
    """The sidecar's WARNING/ERROR lines, which are the thing under test in case 2."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


records = Records()
sync.log.addHandler(records)


def run(mapping_dir: str, files: list[str], extra: list[tuple[str, str]], repo_tree: dict):
    global tree
    tree = repo_tree
    sync.MAPPING_DIR, sync.FILES, sync.EXTRA_SOURCES = mapping_dir, files, extra
    records.lines.clear()
    fetched.clear()
    pyapi_calls.clear()
    sync.sync_once(object(), "0123456789abcdef")


# --- 1. the primary source, plus a definitions-only one beside it ---------------------------

run(CUB, [f"{CUB}/vars.json", f"{CUB}/variables.py"], [("reprodicu", REPRO)], FULL_TREE)

assert (TARGET / "vars.json").read_bytes() == BLOBS["sha-cub-vars"]
assert (TARGET / "variables.py").read_bytes() == BLOBS["sha-cub-py"]
# the extra source is prefixed with its key: a flat dir has room for exactly one vars.json,
# and the prefixed names are what the API's REFERENCE_DATASETS reads
assert (TARGET / "reprodicu_vars.json").read_bytes() == BLOBS["sha-repro-vars"]
assert (TARGET / "reprodicu_units.json").read_bytes() == BLOBS["sha-repro-units"]
# the primary source still gets its full treatment
# Every data file in the mapping tree is staged, under its path there — no manifest, because
# a snippet names its files by uuid and only the API knows which uuid a path was given.
assert (TARGET / "files" / "postcode" / "map.csv").read_bytes() == BLOBS["sha-cub-csv"]
# ...and vars.json is not one of them: it is an input to the import, already staged flat, and
# a copy of it in the library would be a file no definition could ever read.
assert not (TARGET / "files" / "vars.json").exists(), "staged an import input as a data file"
assert pyapi_calls and reimports == [1], (pyapi_calls, reimports)
assert not records.lines, records.lines

# --- 2. a definitions-only source as the primary one ----------------------------------------
# What reprodICU looks like to a sidecar pointed straight at it: no variables.py, so nothing
# reads a data file and there is no completion surface to build. Both passes are skipped, in
# silence.

(TARGET / "variables.py").unlink(missing_ok=True)
shutil.rmtree(TARGET / "files", ignore_errors=True)
run(REPRO, [f"{REPRO}/vars.json"], [], FULL_TREE)

assert (TARGET / "vars.json").read_bytes() == BLOBS["sha-repro-vars"]
assert not (TARGET / "files").exists(), "staged data files for a source that has no snippets"
assert not pyapi_calls, "generated a completion surface for a source with no python"
assert not records.lines, records.lines
assert reimports == [1, 1], reimports

# --- 3. what *is* worth a warning ------------------------------------------------------------

# a configured FILES path this commit doesn't have: skipped, and said so — the rest of the
# cycle still runs, so one moved file can't stop the definitions from being synced
run(CUB, [f"{CUB}/vars.json", f"{CUB}/variables.py", f"{CUB}/gone.parquet"], [], FULL_TREE)
assert any("gone.parquet" in line for line in records.lines), records.lines
assert f"{CUB}/gone.parquet" not in fetched, fetched
assert reimports == [1, 1, 1], reimports

# an extra source whose mapping dir holds nothing we recognise: its definitions were not
# updated, which is exactly the kind of silent staleness that has to be loud
run(CUB, [f"{CUB}/vars.json", f"{CUB}/variables.py"],
    [("elsewhere", "src/corr_vars/sources/elsewhere/mapping")], FULL_TREE)
assert any("elsewhere" in line for line in records.lines), records.lines
assert not (TARGET / "elsewhere_vars.json").exists()

# a source with definitions but no units is not a problem: plenty of variables are dimensionless
run(CUB, [f"{CUB}/vars.json", f"{CUB}/variables.py"], [("reprodicu", REPRO)],
    {k: v for k, v in FULL_TREE.items() if k != f"{REPRO}/units.json"})
assert not records.lines, records.lines

# --- 4. the row seam: nothing by default, one POST when a deployment fills it in --------------
# `row_source.build_rows` is the sidecar's counterpart to api/special_vars.py (a no-op in the
# public build, overlaid by a deployment). What matters here is that the sidecar posts only
# what it was given, and only when it changed.

posts: list[dict] = []


class FakeClient:
    def post(self, url, headers=None, json=None):
        posts.append({"url": url, "json": json})
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {}})()


# the public no-op: no rows, so no call at all
assert sync.row_source.build_rows() == ([], [])
assert sync.push_rows(FakeClient(), None) is None
assert posts == [], posts

ROWS = [{"name": "med_x", "definition": {"type": "medication", "drug": "x"}}]
sync.row_source.build_rows = lambda: (ROWS, ["medication"])
digest = sync.push_rows(FakeClient(), None)
assert digest and len(posts) == 1, posts
assert posts[0]["url"].endswith("/internal/variables/upsert"), posts[0]
assert posts[0]["json"] == {
    "rows": ROWS, "mode": "complete", "complete_for_types": ["medication"]
}, posts[0]

# the same rows again: hashed, not posted — an unchanged mapping file costs nothing
assert sync.push_rows(FakeClient(), digest) == digest
assert len(posts) == 1, posts

# a generator that dropped a type claims nothing, rather than claiming a type it has no rows for
sync.row_source.build_rows = lambda: (ROWS, [])
assert sync.push_rows(FakeClient(), digest) != digest
assert posts[-1]["json"] == {"rows": ROWS}, posts[-1]

# a generator that raised posts nothing and keeps the previous digest, so the next cycle retries
def _boom():
    raise RuntimeError("parquet is half-written")


sync.row_source.build_rows = _boom
records.lines.clear()
assert sync.push_rows(FakeClient(), digest) == digest
assert len(posts) == 2, posts
assert any("row generation failed" in line for line in records.lines), records.lines

print("SYNC SOURCES SMOKE OK")
