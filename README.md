# Concepts Browser

A web application and API for storing, browsing and versioning **clinical concept
definitions** — a schema-conformant JSON plus an optional Python snippet, per data source,
with full audit trails. The JSON + Python are evaluated by a separate package
([corr-vars](https://github.com/CUB-CORR/corr-vars)); this service only stores and serves
them.

Created by researchers at [Charité – Universitätsmedizin Berlin](https://www.charite.de)
for the Charité Outcomes Research Repository (CORR), and built to be institution-agnostic:
directory (LDAP) sign-in, email notifications, and all branding are deployment
configuration.

## Stack

FastAPI + SQLAlchemy + **SQLite** for the API, a **SvelteKit** (adapter-node) frontend, and
an optional **vars-sync** sidecar — Docker Compose services. Reads and writes require a
bearer token and the matching capability; per-project API keys serve external clients.

## Run

```bash
cp example.env .env        # edit JWT_SECRET and the admin password at minimum
docker compose up --build
```

Prebuilt images are published to GHCR on every push to `main` (and on `v*` tags):
`ghcr.io/cub-corr/concepts-browser/{api,app,sync}`. Deployments can skip building
entirely:

```bash
docker compose pull && docker compose up --no-build -d     # IMAGE_TAG in .env pins a version
```

Everything institution-specific is runtime configuration (env vars and the `/brand`
bind-mount, see Branding below), so the stock images are meant to be used as-is.

- Frontend: http://localhost:3000 (sign in as the bootstrap admin)
- API:      http://localhost:8000
- Docs:     http://localhost:8000/docs
- Health:   http://localhost:8000/health

On first boot the API creates the tables, seeds a bootstrap admin (from
`BOOTSTRAP_ADMIN_*`), and inserts the reference data in **`api/seed.yaml`** (sources,
common taxonomies, optional concepts). The seed is idempotent — rows are inserted only if
absent, so you can extend the file and restart.

It then imports the **reference datasets** (`api/importer.py`): every variable in a dataset's
vars file becomes a concept (named under `corr_v1`) plus one published config for that
dataset's source, with its JSON validated against the per-(source, type) schema; entries that
don't conform are **skipped with a warning**, never imported. The pass is an **upsert** and
runs on every boot: a variable whose definition moved upstream gets a new version
(`change_type: "sync"`), an identical one is compared and skipped, and a variable that
disappeared upstream is reported but never removed (see [the reference import](#the-reference-import)). Toggle the whole pass with
`IMPORT_REFERENCE_ON_FIRST_RUN=false`.

Two datasets ship:

- the **primary** one (`IMPORT_SOURCE_KEY`, default `cub_hdp`) — `reference/vars.json`, plus
  each variable's same-named function from `reference/variables.py` as its `py` snippet, the
  source's data files (walked into its versioned file library), and whatever a deployment's
  `special_vars` overlay generates (below). This is the one the vars-sync sidecar refreshes.
- **reprodICU** (`reference/reprodicu_vars.json`) — definitions only: no snippets, no data
  files. See [the reprodICU dataset](#the-reprodicu-dataset) for the two things the
  import derives for it. Further datasets go in `REFERENCE_DATASETS`; `[]` imports the
  primary one alone.

A concept both datasets define ends up with **one config per source**, which is the data model
working as intended. `version_no` is a per-concept sequence shared by all of a concept's
sources, so the second dataset's config continues that concept's numbering (`v2`) while still
being its own source's `initial` version.

> Apart from reprodICU this repository ships a **small sample dataset** (a handful of example
> variables and mapping rows) so the stack boots into something browsable. A real deployment
> replaces `reference/` with its own dataset — by baking the files into the image,
> bind-mounting them, or running the vars-sync sidecar against an upstream repo.

### Generated variables (the `special_vars` seam)

Some deployments derive part of their variable set programmatically rather than authoring it —
CORR's own `cub_hdp` source generates its **`medication`** (`med_*`) and **`laboratory`**
(`lab_*`) variables from two parquet mapping files, and reads those substances' ATC codes out
of the same files. That generation depends on the deployment's data layout, so
`api/special_vars.py` is a **seam**: this build ships a no-op, and a deployment overlays the
module (bind-mount, image layer, or a private fork). Its one function returns two maps —
the extra `{name: definition}` variables, and `{name: {taxonomy: [identifier, …]}}` taxonomy
names the importer then maintains for them.

`sync/row_source.py` is the same seam on the *sidecar* side, for a deployment that would
rather generate outside the API process: it returns rows, which the sidecar posts to
[`/internal/variables/upsert`](#posting-variables-instead-of-staging-files) after each
reimport. Both are no-ops in this build, and running both is safe — identical definitions mean
whichever arrives second sees `unchanged` — so a deployment can move one type at a time. A
deployment that does move should list those types in `EXTERNALLY_MANAGED_TYPES`.

Variables whose type is listed in `AUTO_GENERATED_TYPES` (config) are imported **read-only**:
stamped `"Auto-generated variable, not versioned"` in place of a changelog, refused by the
write API's draft endpoints, and **italicized** with an `auto` badge in the concept list. So
adjusting which types are read-only needs no schema or DB change.

### The reprodICU dataset

[reprodICU](https://github.com/CUB-CORR/corr-vars) is a public harmonised ICU dataset, and its
158 variable mappings ship here as the reference example of a second source. An entry names a
table (`path`), a `column` in it, whether that column is a polars struct, and a `filter`
expression — no `table_name`/`where_clause`, so `reprodicu`'s schemas are a different shape
than `cub_hdp`'s even where the two share a type name. That is exactly what per-(source, type)
schemas are for.

Upstream authors these definitions without a **`type`**, so the importer assigns one from the
entry's shape, deterministically:

| | `dynamic` absent or `true` | `dynamic: false` |
|---|---|---|
| no `calculation` | `native_dynamic` (148) | `native_static` (7) |
| `calculation` present | `derived_dynamic` (3) | `derived_static` (0) |

The four `reference/schema/reprodicu_*.json` state the same rule from the other side — a
`native_*` schema forbids `calculation`, a `*_static` schema requires `dynamic: false` — so the
derivation and the validation cannot drift: an entry the rule mistyped fails its schema and is
skipped with a warning. `derived_static` has no members today and exists because the rule is a
cross product; a definition of that shape must have somewhere valid to land.

Upstream also keeps **units** in a separate `units.json`. Rather than drop them or serve them
from a second file, the import folds each into its variable's `json` as a `unit` field (75 of
the 158 get one), so a unit travels with the version like everything else about the variable
and is covered by the schemas. Blank/`null` units — the dimensionless variables: scores, flags,
categories — are omitted rather than stored as empty, and units naming a variable `vars.json`
no longer defines are ignored. Upstream's own keys are never rewritten: drop `type` and `unit`
and you have the entry as authored.

Finally, `reference/reprodicu_pointers.json` names 25 of these variables in **LOINC** and
**SNOMED CT** — `{variable: {taxonomy: [identifier, …]}}`, the same shape the `special_vars`
seam returns — so a fresh install boots with a worked example of a concept carrying coding-
system names beside its `corr_v1` one. Add `"pointers"` to a `REFERENCE_DATASETS` entry (or set
`REFERENCE_POINTERS_FILE` for the primary dataset) to ship such a file with any dataset. The
pointers are **import-owned**: the importer adds them, keeps them in step with the file, and
retires the ones the file drops, while leaving anything a user added by hand alone. A taxonomy
the seed does not define is skipped with a warning, and an absent file simply means no
pointers.

## Authentication

Two ways in, both issuing the same JWT session:

- **Local users** — the bootstrap admin (and any locally-created account) with a password
  stored in the DB. This is all you need for development and evaluation.
- **LDAP directory sign-in** (optional, `LDAP_ENABLED=true`) — identity comes from your
  institution's directory via search-then-bind; authorization (capabilities) stays in this
  service's DB. New directory users land in a pending state until an admin grants
  capabilities; admins can also pre-provision people straight from a directory search. See
  the `LDAP_*` settings in `example.env` and `api/config.py`.

### Capabilities

Most capabilities are **incremental**: they form one chain, and holding one grants every
lesser one.

```
can_read  <  can_read_detail  <  can_edit  <  can_publish
```

A publisher reads, edits and answers the review queues without those being granted separately; an
editor is shown the snippet they are about to change. Granting is therefore a single choice —
how far along the chain this person goes — and the checks are one-way: a reader is still not an
editor. Entailment is applied when a request is *evaluated* (`security.expand_capabilities`,
reached through `deps.has_capability`), never written into the stored grants: a user's row may
hold `can_publish` alone and stays that way.

Two things stay outside the chain, as separate dimensions:

- **Project membership.** Who may edit a project is decided by its lead list, not by a
  capability. `add_project` (may create projects) and `create_api_key` (may mint keys) are
  independent flags — no amount of publishing confers them.
- **API keys.** A key carries its own scopes and its effective capability is
  `key scopes ∩ owner capabilities`, recomputed on every request, with entailment applied to
  each side. A key scoped `can_publish` on a publishing owner reads code; a key scoped
  `can_read` on that same owner does not. Scopes still narrow — they narrow along the chain.

`can_admin` is the one blanket capability: it implies all of the above.

Reading is two capabilities, not one. `can_read` gets the concept, its names, its
documentation and its **JSON definitions** — enough to browse and to understand what a variable
means. `can_read_detail` adds what the definition *computes with*: the `py` snippets and the
bytes of the data files those snippets read. A caller holding only `can_read` still gets a
`200` on the concept routes, with the withheld snippet marked (`sources[*].py_locked: true`,
plus an `X-Concepts-Locked: can_read_detail` response header) — never a silent `null` that a
machine consumer could mistake for "this definition has no code". The download routes refuse
outright with a `403`. Upgrading an existing deployment grants `can_read_detail` to everyone
who held `can_read` and nothing above it, and to their live API keys, exactly once at boot
(anything higher already entails it); accounts created afterwards — including LDAP
auto-granted ones — start with `can_read` alone.

Optionally, approval notifications go out through **Exchange Web Services**
(`EXCHANGE_*` settings; verify connectivity with `docker compose exec api python -m
api.mail_check`).

## Branding

The default look is Charité-inspired (colors) with an attribution footer; everything
institution-specific is swappable without a rebuild:

- **`PUBLIC_*` env vars** (see `example.env`) override the product name, sign-in hint,
  logos, background, footer and docs links at runtime.
- **`app/static/brand/`** holds the swappable assets: fonts (`brand.css` + open typefaces
  by default), the sign-in background and logos. A deployment can bind-mount its own
  directory over `/app/build/client/brand` to swap in corporate typefaces and imagery.
- **`PUBLIC_GITHUB_ISSUE_URL`** points the concept page's "Report issue" button at your
  issue tracker. It is a URL template whose `{tax_name}` and `{concept_name}` placeholders
  are substituted (percent-encoded) with the concept being viewed, e.g.
  `https://github.com/ORG/REPO/issues/new?template=concept.yml&title=[{tax_name}/{concept_name}]`
  — prefill the body on the tracker's side. Unset, no button is rendered.
- **`PUBLIC_BUILD_COMMIT`** is the git commit the app was built from; the footer shows it
  abbreviated (full hash on hover) so you can tell which release is live. CI bakes it into
  the published app image as a build arg; unset, nothing is rendered.

## Clinical documentation

Each concept carries editable clinical documentation: a clinical description, an
implementation description, known caveats, and a workflow **status** label. It lives on the
concept row and is edited straight from the concept page (pencil icon on the Documentation
card). The prose fields need `can_edit`; changing the status needs `can_publish` (a plain
workflow flip, not tracked in the audit log). The API surface is
`PATCH /concept/{taxonomy}/{name}/documentation`.

Deployments that keep their documentation in **Notion** can have the sidecar export it (see
below): page titles are matched to concept names (taxonomy configurable via
`NOTION_DOCS_TAXONOMY`), column names are mapped in `sync/notion_fields.json`, and the
importer applies the export on every reimport — in-app edits are then superseded by the
upstream page, and concepts with a Notion page get an "Open in Notion" button.

## Study context: a project's PICO frame and study team

A **project** carries a **Study context** card on its page: the PICO frame the study is built
on (Population, Intervention, Comparison, Outcome — four free-text fields) and the study team
behind it (*Projektteilnehmer*, free text). They describe the study, which is what a project
is — not any concept it reads — so they are columns on the project row.

They go through the ordinary `PATCH /projects/{id}`, so they follow the project's own
permission model: a **project lead** or an administrator may edit them, no capability is
involved, and the edit is audited like every other authenticated request. Nothing outside the
app writes them, so what a lead types stays until somebody edits it again. The card stays
hidden for readers until someone fills it in.

## vars-sync sidecar (optional)

Start with `docker compose --profile sync up` and set `VARS_REPO` (plus
`VARS_GITHUB_TOKEN` for a private repo). The sidecar polls the repo via the GitHub API and,
when the branch tip moves, downloads `vars.json` + `variables.py` (plus the parquet
mappings) and calls the API's token-guarded `POST /internal/reimport`, which **wipes the
concept graph and rebuilds it** from the new files. Useful while the authoritative variable
definitions live in a git repo rather than in this service.

It also stages the **data files the source ships** as `files/<relpath>` in the shared
reference dir, and the reimport walks that tree into the source's
[file library](#data-files-live-in-the-source-and-are-versioned), minting a new file version
wherever the bytes moved — and, exactly like an upload, publishing a new version of every
concept whose current config reads a file whose bytes moved. There is no manifest saying which
variable needs which file: a snippet says so itself with `getfile("<uuid>")`, and only the API
knows what uuid a path was given. The sidecar only ever writes to the shared volume — all database work stays on the API
side, so it needs no DB or upload credentials.

Finally it generates `pyapi.json`, the completion surface for the app's code editor, served
by the API at `GET /sources/{key}/pyapi` (404 without the sidecar). It covers the corr_vars
helper modules (AST-parsed from upstream), the names a snippet gets for free (`variables.py`'s
import header, `var`'s fields, `cohort`'s public surface) and the members of the **installed**
polars/pandas — each with its signature and the first line of its docstring. That is name +
signature + docstring completion, **not** type inference: what a chained expression evaluates
to needs a real language server (Pyright in WASM) and is deliberately out of scope. See
`sync/pyapi.py` for the document shape.

`VARS_EXTRA_SOURCES` (`key=repo/dir`, comma-separated) adds **definitions-only** sources — the
shape reprodICU has. Only their `vars.json`/`units.json` are staged, as `<key>_vars.json` /
`<key>_units.json` (a flat reference dir has room for exactly one `vars.json`), which is what
`REFERENCE_DATASETS` reads them under. Such a source has no `variables.py`, so the data-file
scan and the pyapi generation are skipped for it in silence — that is the normal shape of a
definitions-only source, not a degraded one.

With `NOTION_API_KEY` + `NOTION_DATABASE_ID` set, the same sidecar also refetches the
Notion documentation database every `NOTION_POLL_INTERVAL` seconds, writes
`notion_docs.json` into the shared reference dir, and triggers a reimport when it changed
(Notion-only operation without `VARS_REPO` works too).

## Updating the reference data without the sidecar

The sidecar is optional. A deployment that keeps its reference files by hand replaces them in
the bind-mounted reference dir and runs

```
docker compose exec api python -m api.reimport
```

which performs the same upsert the sidecar triggers (new variables become concepts, changed
ones get a new version, nothing is deleted) and prints the stats. The destructive `force`
rebuild is deliberately not offered there.

Notion documentation is pulled by that command too, so it can't go stale in this mode: set
`NOTION_API_KEY` + `NOTION_DATABASE_ID` **on the api service** and the export is fetched and
written to `notion_docs.json` before the upsert applies it. Column names map through
`notion_fields.json` in the reference dir if you put one there, otherwise through the default
mapping in `api/notion_pull.py` (`NOTION_FIELDS_FILE` overrides the location) — the same
mapping file the sidecar takes. Unset credentials mean the pull is skipped with a one-line
notice and the reimport proceeds; a configured pull that fails aborts the command non-zero
**before** the upsert, rather than quietly re-applying yesterday's documentation.

## Schema validation

A config's `json` is validated against a **per-(source, type) JSON Schema** on draft
create/edit and again at publish. The schemas live as files in `SCHEMA_DIR` (default
`reference/schema`) and are indexed by their `$id`
(`…/src/<source>/<type>/schema.json`) — **drop a file in that folder and the type appears
automatically**; no DB change, no code change. `supported_types` is derived from the
folder, so it can never drift from what's on disk.

A source becomes *schema-governed* once at least one type schema exists for it. Sources
without schemas are pass-through until theirs are added — nothing has to be registered
anywhere for that to work. For `cub_hdp` this repo ships a deliberately **basic example
schema set** (a `native_dynamic` type with `table_name`/`where_clause`/`filter`, plus the
auto-generated `medication`/`laboratory` contracts); a deployment mounts its institution's
full schema folder over `SCHEMA_DIR` and the richer types appear automatically. The
`reprodicu` set is the real thing, and shows two sources carrying the same type name for
entirely different JSON. Inspect what's loaded:

```bash
curl -s localhost:8000/sources                          # supported_types + schema_governed
curl -s localhost:8000/sources/cub_hdp/types
curl -s localhost:8000/sources/cub_hdp/schema/native_dynamic
curl -s localhost:8000/sources/reprodicu/schema/native_dynamic    # same name, other shape
```

## Concept names are pointers

A concept row is identity-only (an `id` + description). Its human-facing **name** is a
*pointer*: a row in `concept_taxonomy` saying "this identifier, in this taxonomy, means this
concept, from `created_at` until `deprecated_at`". Creating a concept registers a pointer
under the **`corr_v1`** taxonomy by default (override with `taxonomy` in the create body);
the same concept can also be named in ICD-10, ATC, LOINC, ….

Pointers are append-only. Nothing is deleted, and there is **no unique constraint** on
`(taxonomy, identifier)`, because two things are legitimate:

- **aliases** — one concept, several identifiers in one taxonomy. All of them resolve; the
  secondary ones carry `relationship: "alias"`.
- **groups** — one identifier, several concepts. Mostly ATC codes, where one code covers
  several substances. `POST .../pointers` refuses to form one by accident: it takes
  `confirm_group: true`.

So **`GET /concept/{taxonomy}/{name}` always returns a JSON list**, one element per concept
the name resolves to, ordered by concept id, each carrying the `pointer` it was reached
through. Anything that addresses one concept's history — `?v=`, `?draft=`, any write, any
subresource — refuses a group with `400 {"error": "ambiguous_name", "members": [...]}` rather
than picking a member, and the **id routes** (`/concept/id/{id}`, plus `/history`, `/drafts`,
`/files/{uuid}`, `/documentation`, the draft operations) are the form that is never ambiguous.

`?date=` (`d=`) moves the whole lens: it selects which pointers were active then *and* which
versions existed. A name whose pointers have all been retired still resolves — to what it last
meant, flagged via `pointer.deprecated_at` — so a link or a pinned client name never breaks.

`GET /concepts?taxonomy=<key>` (default `corr_v1`) returns **one row per active pointer**, with
`group_size` (how many concepts share that identifier there) and `relationship`, so the app can
badge aliases and collapse group members into one display row. `include_deprecated=true` adds
the retired names, flagged.

`GET /concepts/search?q=&limit=` matches a substring against every identifier and display name
in **every** taxonomy and groups the hits per concept — what the "point at an existing concept"
and successor pickers run on.

### Renaming, grouping and retiring a concept

```
POST /concept/id/{id}/pointers                            # {taxonomy, identifier, display_name?, confirm_group?}
POST /concept/id/{id}/pointers/{pointer_id}/deprecate     # close its window
```

Both need `can_edit`. **Renaming** is those two in order: add the new name, retire the old one.
The old identifier keeps resolving afterwards, flagged, which is the whole point of the window.
A live concept can never lose its last active name (adding a replacement first is the fix), and
there is no pointer delete endpoint.

**Retiring a concept** is a reviewed decision, because it takes a definition out of circulation
for every client pinned to it:

```
POST /concept/id/{id}/deprecation-request      # {reason, successor_id?}   (can_edit)
GET  /deprecation-requests?status=pending                                  (can_publish)
POST /deprecation-requests/{id}/approve                                    (can_publish)
POST /deprecation-requests/{id}/reject                                     (can_publish)
```

Approving stamps the concept's `deprecated_at`/`deprecated_by`/`successor_id`; rejecting only
closes the request. Nothing is deleted and **no version is ever renumbered** — the concept's
names keep resolving to it and its history stays exactly where it was. Concept reads report
`deprecated_at` and `successor_id`, the latter walked to the **end** of the chain, so a client
following it lands on the concept that is actually current. New drafts on a deprecated concept
are refused with a 409.

### The review queue

A draft and a deprecation request are both finished work waiting for somebody to decide it,
and both are otherwise only visible on the one concept page they belong to. Two cross-concept
queues make them findable:

```
GET /drafts                                                                (can_publish)
GET /deprecation-requests?status=pending                                   (can_publish)
```

`GET /drafts` returns every unpublished draft, newest first, each row already carrying the
concept's `taxonomy`/`name`/`concept_id` (resolved the way an id-addressed read picks a name),
its `source`, `type`, `change_type`, `message`, `author` and whether the concept has since been
retired — so the queue renders without a concept read per row, and links straight back to the
draft. The app puts both queues on **`/review`**.

Watching the queues and answering them are one capability, `can_publish`: whoever is tasked
with reviews is who releases the result, so there is no separate reviewer role. An editor
writes drafts and files deprecation requests, and sees neither queue.

### Drafts copy from the previous version

Creating a draft **copies `type` / `json` / `py` from the latest published version** of
that (concept, source) by default — you only send what changes. The `type` is inherited
and cannot change while copying. To start a brand-new definition (e.g. to **change a
variable's type**), pass `empty: true` and supply the new `type` + `json`. Which data files a
draft reads is not copied from anywhere — it is read out of the snippet the draft holds
(below).

### Data files live in the source, and are versioned

A `py` snippet often reads a data file — a postcode mapping, a pickled classifier. Those files
belong to the **source**, not to one concept's version, and are versioned in its library. A
snippet names one by uuid:

```python
mapping = pl.read_csv(getfile("6f1e0c2a-…"))
```

What a config version carries is therefore a **pin**: this file uuid at this file version. A
client reading v3 gets the bytes v3 was published against, and a new version of a file
**publishes a new version of every concept whose current config reads it** — a replaced
mapping table changes what a definition computes just as surely as rewriting its code would.
That is why uploads need `can_publish`, not `can_edit`, and why the app asks for confirmation
with the affected-concept count. Identical bytes are recognised by digest and mint nothing.

This holds for **every** way new bytes arrive: an upload through the route below, and a file
the sidecar restages for the reference import. The import versions its own variables and then
runs the same cascade for what it restaged, so a snippet somebody wrote in the app is never
left silently pinned to a mapping table the source has replaced. A definition already reading
the newest bytes is skipped, so nothing is versioned twice for one replacement.

```
GET    /sources/{key}/files                                # can_read — the editor completes from this
GET    /sources/{key}/files/{uuid}                         # metadata + full version history
GET    /sources/{key}/files/{uuid}/download?version=2      # can_read_detail — bytes; ETag = sha256
GET    /sources/{key}/files/{uuid}/references              # concepts whose current config reads it
POST   /sources/{key}/files                                # can_publish — multipart: path, file, message, uuid?
DELETE /sources/{key}/files/{uuid}                         # can_publish — soft; 409 while referenced
GET    /concept/id/{id}/files/{uuid}?v=3                   # can_read_detail; same v / date / draft selectors
```

Retiring is always a **soft** delete: older published versions pin file versions forever and
have to keep serving them. It is refused with `409 {"detail": {"references": [...]}}` while any
current published config still reads the file.

Every concept read lists what the served version pins, under `sources.<key>.files` — the
manifest a client pre-downloads from before running the snippet:

```json
{"uuid": "6f1e0c2a-…", "path": "postcode/postcode_mapping.csv", "version_no": 2,
 "size": 20480, "sha256": "…", "media_type": "text/csv",
 "url": "/concept/id/42/files/6f1e0c2a-…?v=3"}
```

`path` is where a consumer lays the file out beside the code; `uuid` is what the snippet asks
for.

A file's **uuid is derived, not random**: `uuid5` of the source key and the path the file was
first created under (`models.source_file_uuid`, and see README_DEV.md — the derivation is
shared with corr-vars, which computes it offline). So the same file has the same uuid in a
fresh database and in every deployment, and a snippet may hardcode it before the bytes have
ever been uploaded.

The uuid is minted once and then **frozen**, which is what makes a rename possible: uploading a
new version with `uuid=<the file's uuid>` and a different `path` renames the file. Nothing
referencing it breaks. Where the name is read from then follows one rule — the library
describes the file *as it stands*, a manifest describes what one config version *pinned*:

| Where | Which name |
|---|---|
| `GET /sources/{key}/files`, the file page, `FileUploadResult.path` | the file's current path |
| `sources.<key>.files[].path` in a concept read, and the file download served for it | the path pinned when that config version was published |
| a version-history entry (`versions[].path`) | the path *that version* was uploaded under |

A rename onto a path another file of the source already holds is refused with
`409 {"detail": {"error": "file_path_taken"}}`. Bytes live under `FILE_DIR` (default `/data/files`, on the same volume as the database —
back them up together); `MAX_UPLOAD_BYTES` and `ALLOWED_FILE_SUFFIXES` bound what may be
uploaded.

> **Breaking change.** The public download route was `GET /concept/{tax}/{name}/files/{path}`
> and is now `GET /concept/{tax}/{name}/files/{uuid}` (likewise the `/concept/id/{id}` mirror).
> A path is no longer an address: it is a label a file can be renamed under, while the uuid is
> what the snippet itself names. Clients map uuid → path from the manifest above. The per-draft
> attachment routes (`POST`/`DELETE /concept/.../drafts/{id}/files`) are gone entirely —
> uploading is a source-library operation now.

## The reference import

`api/importer.py` is an **upsert**, not a rebuild. Per variable it resolves the name in the
**key taxonomy** (`?key_taxonomy=`, default `corr_v1`), which must be 1:1 for the incoming
names:

- **not found** → new concept + pointer (`origin: "import"`) + published `v1`
  (`change_type: "initial"`).
- **found, definition identical** → nothing is written. `type`, `json` (deep equality after a
  JSON round-trip) and `py` (empty normalized to null) are what "identical" means.
- **found, definition moved** → a new published version, numbered next in that concept's
  sequence, `change_type: "sync"`, message from `SYNC_IMPORT_MESSAGE`.
- **name points at several concepts** → skipped with a warning (`skipped_ambiguous`); the
  import will not guess which member upstream meant.
- **stored but no longer offered upstream** → reported as `missing_upstream`, never removed.
  Retiring a concept is a reviewed decision, not an import's to make.

The taxonomy names a `special_vars` overlay lists for a variable (e.g. its ATC codes) are
maintained the same way: identifiers upstream added are created, ones it dropped are
deprecated, and `origin: "user"` pointers — names a person typed in — are never touched. A live
user pointer that is exactly what the import wants is **adopted** (its `origin` flips) rather
than duplicated, which is how a database that predates the distinction settles.

```bash
curl -sX POST localhost:8000/internal/reimport -H "x-internal-token: $INTERNAL_TOKEN"
```

The response carries the pass's counts (`imported`, `updated`, `unchanged`,
`skipped_ambiguous`, `pointers_added`, `pointers_deprecated`, `missing_upstream`, …). This is
what the vars-sync sidecar calls on every upstream push.

### Posting variables instead of staging files

A generator that derives variables from something other than a vars.json — a mapping table,
a database — can post them as rows and skip the file round-trip entirely:

```bash
curl -sX POST localhost:8000/internal/variables/upsert \
  -H "x-internal-token: $INTERNAL_TOKEN" -H 'content-type: application/json' \
  -d '{"rows": [{"name": "med_ipratropium",
                 "definition": {"type": "medication", "drug": "ipratropium"},
                 "pointers": {"ATC": ["R03BB01"]}}]}'
```

Same upsert, same rules, same counts back — a row identical to what is stored writes nothing.
The whole batch is one transaction; `"dry_run": true` reports what it would do and rolls back.

The one thing rows have to be explicit about is what they *don't* carry. `mode` is `partial`
by default: the batch says nothing about completeness and no missing-upstream report is
computed. `mode: "complete"` with a non-empty `complete_for_types` says these rows are
everything the sender has for those types, so stored names of those types that are absent are
reported. **Nothing is ever deprecated by either mode** — the report is a signal for a person,
exactly as it is on the file path.

A row the JSON schema turns away is skipped and itemised in `errors` (what the file import
does, with the log line a poster cannot read); `"on_invalid": "reject"` refuses the batch
whole instead, and is the default in complete mode, where a skipped row would otherwise be
indistinguishable from a retired one in the report. A malformed request — a duplicate name, a
row outside `complete_for_types` — is a 422 that writes nothing.

Set `EXTERNALLY_MANAGED_TYPES` to the types a deployment feeds in this way. They then drop out
of the *file* import's missing-upstream report, which otherwise names every one of them on
every poll, since the files never carried them.

**`?force=true` is a development reset, not the production path.** It wipes the whole concept
graph — file pins, configs, pointers, concepts — and rebuilds it from the current files, so
every in-app edit, every version number and every hand-made name is gone. Audit rows survive,
detached from the concepts they named. The sources' **file libraries survive**: they are not
part of the concept graph, and taking them along would invalidate every `getfile("…")` uuid in
the snippets the rebuild is about to write.

## Quick tour

```bash
# log in -> token
TOKEN=$(curl -s localhost:8000/auth/login -H 'content-type: application/json' \
  -d '{"username":"admin","password":"admin"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# create a concept (needs can_edit) -> registers "any_dialysis" under corr_v1
curl -s localhost:8000/concepts -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"name":"any_dialysis","display_name":"Any Dialysis"}'

# first draft for a source: nothing to copy yet, so empty=true + a valid json/type
curl -s localhost:8000/concept/corr_v1/any_dialysis/drafts -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{
    "source":"cub_hdp","empty":true,"type":"native_dynamic",
    "json":{"type":"native_dynamic","table_name":"diagnoses","where_clause":"code LIKE '"'"'Z49%'"'"'"},
    "message":"initial definition"}'
# (an invalid json here returns 400 with {"error":"schema_validation_failed","errors":[...]})

# publish it (needs can_publish) -> becomes version 1
curl -s -X POST localhost:8000/concept/corr_v1/any_dialysis/drafts/1/publish \
  -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{}'

# improve it: copy from v1 (no json needed), then edit/publish via PUT + /publish
curl -s localhost:8000/concept/corr_v1/any_dialysis/drafts -H "authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"source":"cub_hdp"}'

# read it — {taxonomy}/{name}, which always answers with a *list* (a name may point at more
# than one concept). Reads take a required `project` query param; its value is only validated
# for external clients when APP_SHARED_SECRET is configured (see example.env).
curl -s 'localhost:8000/concept/corr_v1/any_dialysis?project=internal' -H "authorization: Bearer $TOKEN"
curl -s 'localhost:8000/concept/corr_v1/any_dialysis?project=internal&v=1' -H "authorization: Bearer $TOKEN"
curl -s 'localhost:8000/concept/corr_v1/any_dialysis?project=internal&date=2026-05-01T05:00Z' -H "authorization: Bearer $TOKEN"
```

## Run locally without Docker

```bash
uv sync
DATABASE_URL=sqlite:///./data/concepts.db uv run uvicorn api.main:app --reload
# and in another shell:
cd app && pnpm install && pnpm dev
```

The dev server can also run against a deployed-style backend and a private brand overlay —
useful when a deployment repo carries your institution's branding and data:

```bash
API_INTERNAL_URL=http://localhost:8000 \
BRAND_DIR=/path/to/deploy-repo/brand \
APP_SHARED_SECRET=<same value as the api> \
pnpm dev
```

`BRAND_DIR` makes `pnpm dev` serve `/brand/*` from that directory (falling back to
`static/brand`), mirroring the bind-mount a production deployment uses.

Tests are standalone scripts against a temp SQLite DB:

```bash
for t in tests/*_smoke.py tests/smoke.py tests/reimport_safety.py; do uv run python "$t"; done
```

## Backups

```bash
chmod +x scripts/backup.sh
./scripts/backup.sh ./data/concepts.db
```

## License

Elastic License 2.0 (ELv2) — see [LICENSE](LICENSE). See also [CONTRIBUTING.md](CONTRIBUTING.md) and
[SECURITY.md](SECURITY.md).
