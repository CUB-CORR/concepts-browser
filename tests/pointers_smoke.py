"""Names as pointers: groups, aliases, renames, and the routes that address a concept by id.

Run: uv run python tests/pointers_smoke.py

The invariants the model exists for:

* one identifier may name several concepts (a *group*), so a name read is always a list;
* anything that addresses one concept's history — `?v=`, `?draft=`, a write — refuses a group
  with a machine-readable `ambiguous_name` 400 instead of picking a member;
* a renamed concept's old name keeps resolving, flagged, forever;
* a live concept can never lose its last name;
* `/concept/id/...` is the form that is never ambiguous, and `?date=` moves the whole lens.
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

db_path = os.path.join(tempfile.mkdtemp(), "pointers.db")
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
os.environ["JWT_SECRET"] = "test-secret-that-is-at-least-32-bytes-long!!"
os.environ["APP_SHARED_SECRET"] = ""  # app mode: the project gate is off for this test
os.environ["BOOTSTRAP_ADMIN_USERNAME"] = "admin"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
os.environ.setdefault("SCHEMA_DIR", "reference/schema")
os.environ["IMPORT_REFERENCE_ON_FIRST_RUN"] = "false"
os.environ["FILE_DIR"] = tempfile.mkdtemp()

import warnings  # noqa: E402

warnings.filterwarnings("ignore")

from fastapi.testclient import TestClient  # noqa: E402

from api import security  # noqa: E402
from api.db import SessionLocal  # noqa: E402
from api.main import app  # noqa: E402
from api.models import User  # noqa: E402

ND = {"type": "native_dynamic", "table_name": "drugs"}


def nd(where: str) -> dict:
    return {**ND, "where_clause": where}


def stamp() -> str:
    """Now, as the query string spells it (`Z`, so the offset survives the URL). Truncated to
    the second, so the callers sleep either side of it to keep the ordering unambiguous."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


with TestClient(app) as c:
    tok = c.post("/auth/login", json={"username": "admin", "password": "admin"}).json()
    c.headers["authorization"] = f"Bearer {tok['access_token']}"
    _raw_get = c.get
    c.get = lambda url, **kw: _raw_get(f"{url}{'&' if '?' in url else '?'}project=internal", **kw)

    def concept(name: str, **body) -> int:
        r = c.post("/concepts", json={"name": name, **body})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def publish(concept_id: int, definition: dict) -> int:
        r = c.post(
            f"/concept/id/{concept_id}/drafts",
            json={"source": "cub_hdp", "empty": True, "type": "native_dynamic",
                  "json": definition},
        )
        assert r.status_code == 201, r.text
        r = c.post(f"/concept/id/{concept_id}/drafts/{r.json()['id']}/publish", json={})
        assert r.status_code == 200, r.text
        return r.json()["version_no"]

    # --- a group: one ATC code, two substances ------------------------------------------------
    ipratropium = concept("ipratropium", display_name="Ipratropium bromide")
    fenoterol = concept("fenoterol")
    publish(ipratropium, nd("atc = 'R03BB01'"))
    publish(fenoterol, nd("atc = 'R03AC04'"))

    # The code names the first one; pointing it at the second is refused until confirmed.
    assert c.post(
        f"/concept/id/{ipratropium}/pointers",
        json={"taxonomy": "ATC", "identifier": "R03AL01"},
    ).status_code == 201
    r = c.post(
        f"/concept/id/{fenoterol}/pointers",
        json={"taxonomy": "ATC", "identifier": "R03AL01"},
    )
    assert r.status_code == 409 and r.json()["detail"]["error"] == "name_exists", r.text
    assert [m["id"] for m in r.json()["detail"]["members"]] == [ipratropium], r.text
    r = c.post(
        f"/concept/id/{fenoterol}/pointers",
        json={"taxonomy": "ATC", "identifier": "R03AL01", "confirm_group": True},
    )
    assert r.status_code == 201, r.text
    fenoterol_atc = r.json()["id"]
    # ...and the same concept can never hold one identifier twice.
    assert c.post(
        f"/concept/id/{fenoterol}/pointers",
        json={"taxonomy": "ATC", "identifier": "R03AL01", "confirm_group": True},
    ).status_code == 409

    # The name now resolves to both, ordered by concept id, each carrying its own pointer.
    body = c.get("/concept/ATC/R03AL01").json()
    assert [m["id"] for m in body] == sorted([ipratropium, fenoterol]), body
    assert {m["pointer"]["identifier"] for m in body} == {"R03AL01"}, body
    assert body[0]["names"], body[0]
    # ...and both members appear in the list, told apart by group_size.
    listed = c.get("/concepts?taxonomy=ATC").json()
    assert [x["name"] for x in listed] == ["R03AL01", "R03AL01"], listed
    assert {x["group_size"] for x in listed} == {2}, listed
    assert {x["id"] for x in listed} == {ipratropium, fenoterol}, listed
    # A concept named once in corr_v1 has group_size 1 there.
    assert {x["group_size"] for x in c.get("/concepts").json()} == {1}

    # --- what a group refuses ------------------------------------------------------------------
    for url in ("/concept/ATC/R03AL01?v=1", "/concept/ATC/R03AL01?draft=1"):
        r = c.get(url)
        assert r.status_code == 400, (url, r.text)
        detail = r.json()["detail"]
        assert detail["error"] == "ambiguous_name" and detail["name"] == "R03AL01", detail
        assert sorted(m["id"] for m in detail["members"]) == sorted([ipratropium, fenoterol])
        assert {"id", "name", "display_name", "description"} <= set(detail["members"][0])
    # …the same for the subresources and the writes that address one history
    assert c.get("/concept/ATC/R03AL01/history").status_code == 400
    assert c.get("/concept/ATC/R03AL01/drafts").status_code == 400
    assert c.post("/concept/ATC/R03AL01/drafts", json={"source": "cub_hdp"}).status_code == 400
    assert c.patch("/concept/ATC/R03AL01/documentation", json={"doc_clinical": "x"}).status_code == 400
    assert c.get("/concept/ATC/R03AL01/files/x.csv").status_code == 400

    # …while the id form answers all of them.
    assert c.get(f"/concept/id/{ipratropium}?v=1").json()["id"] == ipratropium
    assert [h["version"] for h in c.get(f"/concept/id/{ipratropium}/history").json()] == [1]
    assert c.get(f"/concept/id/{ipratropium}/drafts").json() == []
    r = c.patch(f"/concept/id/{ipratropium}/documentation", json={"doc_clinical": "Anticholinergic."})
    assert r.status_code == 200 and r.json()["doc_clinical"] == "Anticholinergic.", r.text
    assert c.get(f"/concept/id/{ipratropium}").json()["doc_clinical"] == "Anticholinergic."

    # --- rename: add the new name, retire the old one -------------------------------------------
    time.sleep(1.1)
    before_rename = stamp()  # strictly after everything above, strictly before the rename
    time.sleep(1.1)
    r = c.post(
        f"/concept/id/{fenoterol}/pointers",
        json={"taxonomy": "corr_v1", "identifier": "fenoterol_inhaled"},
    )
    assert r.status_code == 201, r.text
    old = next(
        n for n in c.get(f"/concept/id/{fenoterol}").json()["names"]
        if n["identifier"] == "fenoterol"
    )
    r = c.post(f"/concept/id/{fenoterol}/pointers/{old['id']}/deprecate", json={})
    assert r.status_code == 200 and r.json()["deprecated_at"], r.text

    # The old name still resolves — flagged, so a reader knows why the URL says something else.
    old_body = c.get("/concept/corr_v1/fenoterol").json()
    assert len(old_body) == 1 and old_body[0]["id"] == fenoterol, old_body
    assert old_body[0]["pointer"]["deprecated_at"] is not None, old_body[0]["pointer"]
    assert c.get("/concept/corr_v1/fenoterol_inhaled").json()[0]["id"] == fenoterol
    # ...but it is no longer listed, unless asked for.
    names = {x["name"] for x in c.get("/concepts").json()}
    assert "fenoterol" not in names and "fenoterol_inhaled" in names, names
    with_old = {x["name"]: x for x in c.get("/concepts?include_deprecated=true").json()}
    assert with_old["fenoterol"]["deprecated_at"] is not None, with_old["fenoterol"]

    # As of before the rename, the old name was the current one and the new one did not exist.
    listed_then = {x["name"] for x in c.get(f"/concepts?date={before_rename}").json()}
    assert "fenoterol" in listed_then and "fenoterol_inhaled" not in listed_then, listed_then
    # …resolved through the pointer whose window was open then (the row is reported as it
    # stands today, so it already carries the deprecation that came later).
    then = c.get(f"/concept/corr_v1/fenoterol?date={before_rename}").json()
    assert [m["id"] for m in then] == [fenoterol], then
    assert then[0]["pointer"]["id"] == old["id"], then[0]["pointer"]
    # …and a name that had not been coined yet still says what it means, rather than 404ing.
    assert c.get(f"/concept/corr_v1/fenoterol_inhaled?date={before_rename}").json()[0]["id"] \
        == fenoterol
    # A name nobody ever registered is a 404.
    assert c.get("/concept/corr_v1/never_existed").status_code == 404

    # --- the orphan guard ------------------------------------------------------------------------
    solo = concept("solo_var")
    solo_pointer = c.get(f"/concept/id/{solo}").json()["names"][0]["id"]
    r = c.post(f"/concept/id/{solo}/pointers/{solo_pointer}/deprecate", json={})
    assert r.status_code == 409 and "last name" in r.json()["detail"], r.text
    # Retiring an already-retired pointer is a 409 too, and a foreign pointer is a 404.
    assert c.post(f"/concept/id/{fenoterol}/pointers/{old['id']}/deprecate", json={}).status_code == 409
    assert c.post(f"/concept/id/{solo}/pointers/{fenoterol_atc}/deprecate", json={}).status_code == 404

    # --- creating a second concept under an existing name ----------------------------------------
    r = c.post("/concepts", json={"name": "solo_var"})
    assert r.status_code == 409 and r.json()["detail"]["error"] == "name_exists", r.text
    r = c.post("/concepts", json={"name": "solo_var", "confirm_group": True})
    assert r.status_code == 201, r.text
    assert len(c.get("/concept/corr_v1/solo_var").json()) == 2

    # --- naming a concept in a taxonomy it has no name in -----------------------------------------
    # What the app's taxonomy selector offers on a concept page: the taxonomies a concept has a
    # live name in are exactly the ones its `names` lists undeprecated, and the greyed-out rest
    # are named through this same endpoint.
    def live_taxonomies(concept_id: int) -> set[str]:
        return {
            n["taxonomy"]
            for n in c.get(f"/concept/id/{concept_id}").json()["names"]
            if n["deprecated_at"] is None
        }

    named_here = concept("blood_ph")
    assert live_taxonomies(named_here) == {"corr_v1"}, live_taxonomies(named_here)
    r = c.post(
        f"/concept/id/{named_here}/pointers",
        json={"taxonomy": "ATC", "identifier": "V04CX99", "display_name": "Blood pH"},
    )
    assert r.status_code == 201, r.text
    ph_atc = r.json()["id"]
    # Hand-typed names are the user's, not the import's — `_sync_pointers` only ever retires
    # its own rows, so this one survives every reimport.
    assert r.json()["origin"] == "user", r.json()
    assert live_taxonomies(named_here) == {"corr_v1", "ATC"}
    # …and the page under the new name is the same concept.
    assert [m["id"] for m in c.get("/concept/ATC/V04CX99").json()] == [named_here]

    # A retired name is not a place to navigate to: the taxonomy drops out of the live set again
    # while the row stays listed, flagged.
    assert c.post(f"/concept/id/{named_here}/pointers/{ph_atc}/deprecate", json={}).status_code == 200
    assert live_taxonomies(named_here) == {"corr_v1"}
    retired = [n for n in c.get(f"/concept/id/{named_here}").json()["names"] if n["taxonomy"] == "ATC"]
    assert len(retired) == 1 and retired[0]["deprecated_at"] is not None, retired
    # …and naming it there again mints a fresh row rather than reviving the old one.
    r = c.post(
        f"/concept/id/{named_here}/pointers", json={"taxonomy": "ATC", "identifier": "V04CX99"}
    )
    assert r.status_code == 201 and r.json()["id"] != ph_atc, r.text

    # An unknown taxonomy is a 404, not a silently created one.
    assert c.post(
        f"/concept/id/{named_here}/pointers", json={"taxonomy": "nope", "identifier": "x"}
    ).status_code == 404

    # --- the picker's search ---------------------------------------------------------------------
    # Matches across taxonomies, grouped per concept, and a retired name comes back flagged.
    found = {r["concept_id"]: r for r in c.get("/concepts/search?q=fenoterol").json()}
    assert set(found) == {fenoterol}, found
    matched = {(m["taxonomy"], m["identifier"]): m for m in found[fenoterol]["matches"]}
    assert ("corr_v1", "fenoterol") in matched and ("corr_v1", "fenoterol_inhaled") in matched
    assert matched[("corr_v1", "fenoterol")]["deprecated_at"] is not None, matched
    assert matched[("corr_v1", "fenoterol_inhaled")]["deprecated_at"] is None, matched
    # Active names rank first, so the picker's top match is the current one.
    assert found[fenoterol]["matches"][0]["identifier"] == "fenoterol_inhaled", found

    # The ATC code finds both members of the group, one entry each.
    group = {r["concept_id"]: r for r in c.get("/concepts/search?q=r03al").json()}
    assert set(group) == {ipratropium, fenoterol}, group
    assert all(len(r["matches"]) == 1 for r in group.values()), group
    # A display name matches too, case-insensitively...
    assert [r["concept_id"] for r in c.get("/concepts/search?q=BROMIDE").json()] == [ipratropium]
    # ...and `limit` caps how many concepts come back.
    assert len(c.get("/concepts/search?q=o&limit=1").json()) == 1
    assert c.get("/concepts/search?q=").status_code == 422
    assert c.get("/concepts/search?q=zzz-nothing").json() == []

    # --- the audit row a group read leaves ----------------------------------------------------------
    # One row for the whole read, naming the identifier rather than any one member, with the
    # members it resolved to in `detail` — that is the only record of what the name meant then.
    events = c.get("/audit/events?q=R03AL01").json()["items"]
    group_read = next(
        e for e in events
        if e["path"] == "/concept/ATC/R03AL01" and e["status_code"] == 200
    )
    assert group_read["concept_id"] is None, group_read
    assert group_read["concept_name"] == "R03AL01" and group_read["taxonomy"] == "ATC", group_read
    assert sorted(group_read["detail"]["group_members"]) == sorted([ipratropium, fenoterol])
    # …while a name that means one concept is attributed to it, as before.
    single = next(
        e for e in c.get("/audit/events?q=fenoterol_inhaled").json()["items"]
        if e["path"] == "/concept/corr_v1/fenoterol_inhaled"
    )
    assert single["concept_id"] == fenoterol, single

    # --- the gates --------------------------------------------------------------------------------
    with SessionLocal() as db:
        db.add(
            User(
                username="reader",
                password_hash=security.hash_password("pw"),
                capabilities=["can_read"],
                is_active=True,
            )
        )
        db.commit()
    reader = c.post("/auth/login", json={"username": "reader", "password": "pw"}).json()
    reader_h = {"authorization": f"Bearer {reader['access_token']}"}
    assert c.post(
        f"/concept/id/{solo}/pointers", headers=reader_h,
        json={"taxonomy": "ATC", "identifier": "X01"},
    ).status_code == 403
    assert c.post(
        f"/concept/id/{fenoterol}/pointers/{fenoterol_atc}/deprecate", headers=reader_h, json={}
    ).status_code == 403
    # …reading is not gated beyond can_read
    assert c.get("/concepts/search?q=fenoterol", headers=reader_h).status_code == 200

print("POINTERS SMOKE OK")
