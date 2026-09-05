# Developer notes

## Source-file uuids are derived, not random — and it is a cross-repo contract

A file in a source's library is named by a uuid, and that uuid is the only thing a snippet
ever says (`getfile("<uuid>")`). It is **not** minted randomly. It is derived:

```python
SOURCE_FILE_NS = uuid.uuid5(uuid.NAMESPACE_URL, "concepts-browser/source-file")
file_uuid      = str(uuid.uuid5(SOURCE_FILE_NS, f"{source_key}/{initial_path}"))
```

The canonical implementation is `models.source_file_uuid`; every library row is minted through
`services.store_file_version`, which is the only place that calls it (the ingest walk in
`api/importer.py` and the upload route in `api/routers/source_files.py` both go through it).

**Do not change the namespace string or the seed format.** The same derivation is implemented
on the **corr-vars** side, which computes uuids *offline* — snippets are written against a file
uuid before that file has ever been uploaded here. A different namespace, a different separator
or a normalized path would silently turn every one of those references into a dangling uuid.
The point of deriving it at all is that a fresh database, the Charité deployment and a
colleague's laptop all name the same file the same way.

The seed is the source key plus the path the file is **first created under**. After that the
uuid is written once and never re-derived. Three consequences:

- A file **renamed through the API** — uploading a new version under a different name, which
  the file page's replace control now allows — keeps its uuid. The path is a label; the
  identity is the uuid, so nothing referencing it breaks.
- A file **renamed in the staged refdata tree** arrives at the next import as a *new path*, so
  it is a *new file* with a new identity. The old library entry keeps existing, now
  unreferenced, until somebody retires it. Tree-managed files get their identity from their
  tree path — that is exactly what makes it computable offline.
- The seed can therefore be *taken*: a row created at `p`, renamed away from `p`, still holds
  `uuid5(NS, "src/p")` when something new is created at `p`. Identity is frozen, so the new row
  cannot have it; it falls back to a random uuid and logs a warning. Its reference is then not
  computable offline, which is the honest answer, not a silent reuse of somebody else's row.

## How database schema changes work (data-preserving migrations)

There is no Alembic. The migration mechanism is hand-rolled and lives in one place:
`api/main.py::_migrate()`, which runs at **every boot**, right after
`Base.metadata.create_all(engine)`. Together they give you data-preserving schema
evolution, provided you follow the discipline below.

What comes for free:

- **New tables** — `create_all()` creates any table that doesn't exist yet. Nothing to
  write.
- **New indexes on new tables** — same.

What needs an explicit migration function in `_migrate()`:

- **New columns on an existing table** — use the `_add_column` helper (idempotent,
  checks `PRAGMA table_info` first).
- **New/changed constraints or indexes on an existing table** — SQLite can create a
  (partial) index in place (see `_ensure_published_version_unique`); constraint
  changes on columns need a table rebuild (see `_relax_audit_request_columns` for the
  copy-rename pattern).
- **Data reshaping** — write a guarded fold, e.g. `_fold_merges_into_successors`, or
  the `config_file` → `source_file`/`source_file_version`/`config_file_ref` migration:
  read the old rows, build the new ones, drop the old table last.

The rules that make this safe:

1. **Every function must be idempotent.** Guard on observable state ("does this
   column/table exist", "is this data already folded"), never on a version number.
   A migration that has already run must be a no-op, because `_migrate()` runs on
   every single boot.
2. **One transaction per migration** (`engine.begin()`), so a crash mid-migration
   leaves the old state, not half of each.
3. **No down-migrations exist.** The rollback story is the database copy you take
   before deploying — take one, every time (`scripts/backup.sh`).
4. **Ship the migration in the same commit as the model change.** A model whose table
   shape differs from what `_migrate()` can produce from any historical DB is a boot
   failure on someone else's deployment.
5. **Never "fix" an old migration** — its job is to carry old databases forward, and
   editing it breaks databases that already ran the old version. Add a new function.

## MODE=PRODUCTION

Set `MODE=PRODUCTION` in the environment of any deployment whose database is the
system of record. It disables destructive dev operations — currently the
`POST /internal/reimport?force=true` graph rebuild, which would destroy every in-app
edit, draft, and version number. The regular (upsert) reimport is unaffected: it
never deletes anything and is safe to run in production.

## Capability checks go through one helper (never a membership test)

Capabilities are a chain — `can_read < can_read_detail < can_edit < can_publish` — and
holding one entails every lesser one. The chain lives in
`security.CAPABILITY_CHAIN` and is resolved in exactly one function,
`security.expand_capabilities`. Everything else asks through it:

- **Backend:** `deps.has_capability(user, cap)` for a predicate, `deps.require_capability(cap)`
  for a route dependency. Never write `cap in user.capabilities` in a router — that check is
  stricter than the rest of the API and will refuse a publisher a route a reader gets.
- **API keys:** `deps._authenticate_api_key` expands *both* the key's scopes and the owner's
  capabilities before intersecting them, so scopes narrow along the chain instead of falling
  off it.
- **Frontend:** `hasCapability(caps, cap)` / `can(user, cap)` in `app/src/lib/caps.ts`, which
  mirrors the same chain. The UI only decides what to *offer*; the API is authoritative.

Outside the chain, `create_api_key` and `add_project` are independent flags and project
editing is decided by lead membership — none of them is implied by anything but `can_admin`,
which implies everything. Entailment is evaluation-time only: stored grants are never
rewritten, so revoking `can_publish` from a row that holds it alone leaves nothing behind.
Covered by `tests/capability_chain_smoke.py`.
