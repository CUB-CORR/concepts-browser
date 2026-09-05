"""Deployment-specific variables the reference import picks up on top of ``vars.json``.

Some deployments derive part of their variable set programmatically rather than authoring it —
CORR's own ``cub_hdp`` source generates its ``medication`` and ``laboratory`` variables from two
parquet mapping files, and reads the ATC codes for those substances out of the same files. That
generation depends on the deployment's data layout, so this module is a **seam**: the public
build ships the no-op below and a deployment overlays the file (bind-mount, image layer, or a
private fork) with its own implementation.

The contract is one function, ``load_special_variables()``, returning two maps:

* ``variables``  — ``{variable_name: definition}``, merged into the authored ``vars.json``
  entries and imported the same way. ``settings.auto_generated_types`` decides which of them
  are read-only in the browser.
* ``pointers``   — ``{variable_name: {taxonomy_key: [identifier, …]}}``, extra taxonomy names
  the importer maintains for that variable (e.g. its ATC codes). The importer owns these rows:
  it adds what upstream lists, retires what upstream dropped, and never touches a name a user
  created. An identifier may be listed for several variables — that is a group, and legal.

Both maps may be empty; a deployment with only authored variables needs neither.
"""
from __future__ import annotations


def load_special_variables() -> tuple[dict[str, dict], dict[str, dict[str, list[str]]]]:
    """No generated variables and no importer-managed pointers — see the module docstring."""
    return {}, {}
