"""Variables this deployment computes rather than fetches, posted straight to the API.

The sidecar's counterpart to ``api/special_vars.py``. Some deployments derive part of their
variable set programmatically — CORR's own ``cub_hdp`` source generates its ``medication`` and
``laboratory`` variables from two parquet mapping files — and that generation depends on the
deployment's data layout, so this module is a **seam**: the public build ships the no-op below
and a deployment overlays the file (bind-mount, image layer, or a private fork) with its own
implementation. With the no-op, the sidecar posts nothing and behaves exactly as before.

Doing it here rather than in ``special_vars`` keeps the generation where the mapping files
already are, out of the API process, and lets it fail on its own: a generator that breaks
stops posting rows instead of breaking every reimport. Running both is safe — identical
definitions mean the second one through sees `unchanged` — so a deployment can move one type
at a time.

The contract is one function, ``build_rows()``, returning two things:

* ``rows`` — ``[{"name", "type"?, "definition", "python"?, "pointers"?}, …]``, the body of
  ``POST /internal/variables/upsert`` (see ``api/routers/internal.py`` for the full shape).
  ``definition`` is validated against the ``(source, type)`` JSON schema, and those schemas are
  closed: it carries the definition and nothing else — no provenance, no build metadata.
  ``pointers`` is ``{taxonomy key: [identifier, …]}``, the extra names the importer maintains
  for that variable (e.g. its ATC codes).
* ``complete_for_types`` — the types these rows are the **whole** of. The API reports stored
  variables of those types that the batch does not carry (report only; nothing is ever
  deprecated by it). **A type whose generator failed must not appear here**, and neither must
  a partial result: claiming completeness for a type that produced nothing turns a broken
  build into a report saying every one of those variables disappeared. Returning an empty list
  is always safe — the rows are then upserted without any completeness claim at all.

Both may be empty; ``([], [])`` means "nothing to post", and the sidecar skips the call.
"""
from __future__ import annotations


def build_rows() -> tuple[list[dict], list[str]]:
    """No generated rows and no completeness claim — see the module docstring."""
    return [], []
