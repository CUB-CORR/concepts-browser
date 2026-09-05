FROM python:3.13-slim

# Building behind a corporate proxy? Docker's predefined HTTP_PROXY/HTTPS_PROXY/NO_PROXY
# build args work without any ARG declaration here; set them in a compose override.

# uv binary (for reproducible installs from uv.lock)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /srv

# Install dependencies into /srv/.venv from the lockfile.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY api ./api

# JSON-Schema folder (source of truth for validation). Baked in for a self-contained
# image; docker-compose may bind-mount over /srv/schemas for live edits without a rebuild.
COPY reference/schema ./schemas
ENV SCHEMA_DIR=/srv/schemas

# Reference datasets, imported into an empty DB on first boot (see api/importer.py). They land
# at /srv/reference/, matching the default REFERENCE_VARS_FILE / REFERENCE_PYTHON_FILE and the
# paths in REFERENCE_DATASETS. `reprodicu_*` is the second, definitions-only dataset; the
# vars-sync sidecar refreshes all of these on upstream pushes (along with any deployment-
# private mapping files a `special_vars` overlay reads, which this image does not ship).
COPY reference/vars.json reference/variables.py \
     reference/reprodicu_vars.json reference/reprodicu_units.json \
     reference/reprodicu_pointers.json ./reference/

# Use the project venv directly.
ENV PATH="/srv/.venv/bin:$PATH"

EXPOSE 8000

# Single worker: SQLite serializes writes; reads are concurrent via WAL.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
