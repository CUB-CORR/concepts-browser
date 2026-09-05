# Contributing

Thanks for your interest in the Concepts Browser!

## Development setup

```bash
uv sync                                  # API dependencies (Python 3.13)
cd app && pnpm install                   # frontend dependencies
```

Run the API and frontend locally:

```bash
DATABASE_URL=sqlite:///./data/concepts.db uv run uvicorn api.main:app --reload
cd app && pnpm dev
```

## Tests

Tests are standalone scripts against a temporary SQLite database — no services or network
needed:

```bash
for t in tests/*_smoke.py tests/smoke.py tests/reimport_safety.py; do uv run python "$t"; done
```

Please make sure they pass (and extend them for new behaviour) before opening a PR.

## Conventions

- Python is linted with `ruff`; the frontend uses the repo's Prettier/ESLint config.
- Dependencies are managed with `uv add` / `pnpm add` (lockfiles are committed).
- Keep comments explaining *why*, matching the density of the surrounding code.
- There is no Alembic. `create_all()` creates missing *tables* on an existing database, so a
  new table needs nothing; a new **column** is a hand-rolled idempotent `_add_column` call in
  `_migrate()` (`api/main.py`), safe to re-run on every boot.
- A published `config` row is immutable history: never change its `json`, `py`, `type`,
  authorship or timestamps, never renumber it, and never delete one. Superseding a definition
  means appending a new version — including for the reference import, which mints a
  `change_type: "sync"` version rather than rewriting what is stored.
- `concept_taxonomy` rows are append-only too: a name is retired by stamping `deprecated_at`,
  never by deleting or editing the row, so `?date=` can reconstruct what an identifier meant
  at any point and a name that once resolved keeps resolving.

## Pull requests

- Branch from `main`, keep PRs focused, and describe the motivation in the PR body.
- By contributing you agree that your contributions are licensed under the
  [Elastic License 2.0](LICENSE).

## Releases

Versions are git tags. The version lives in `pyproject.toml`, `app/package.json` and
`CITATION.cff`; bump all three, commit, then tag and push:

```bash
git tag -a v1.1.0 -m "v1.1.0" && git push origin v1.1.0
```

The docker workflow builds the tag and publishes it as `1.1.0` and `1.1` image tags
(`IMAGE_TAG=1.1.0` in a deployment's `.env` pins it).
