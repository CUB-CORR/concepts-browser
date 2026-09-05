"""Filesystem JSON-Schema registry: the source of truth for which (source, type)
combinations exist and what a config's `json` must look like.

Schemas live as files under ``settings.schema_dir`` (default ``reference/schema``),
exactly as authored in the corr-vars repo. We never copy them into the database — the
folder *is* the source of truth, so "drop a file in the folder" is all it takes to add or
update a type. Each schema is indexed by its canonical ``$id``, e.g.::

    https://corr.charite.de/corr-vars/src/<source>/<type>/schema.json   # a type schema
    https://corr.charite.de/corr-vars/src/<source>/schema.json          # the umbrella

so ``$ref``s between schemas resolve offline and (source, type) is read from the ``$id``
rather than from brittle filename parsing (source keys contain underscores too).

A source is "schema-governed" once at least one type schema is found for it: its configs
are then strictly validated and its ``type`` must be one of the discovered types. Sources
with no schemas are pass-through until theirs are added — the registry never has to be told
about a source, only about a file.

Type names are scoped to their source rather than global: ``cub_hdp/native_dynamic`` and
``reprodicu/native_dynamic`` are the same word for two unrelated JSON shapes, which is why
the key is the pair and not the type.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .config import settings

log = logging.getLogger("concepts.schema")

# Path marker separating the host part of an $id from its source/type segments.
_SRC_MARKER = "/src/"


@dataclass
class ValidationResult:
    """Outcome of validating a config's `json` against its (source, type) schema."""

    governed: bool
    schema_id: str | None = None
    schema_sha256: str | None = None
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def report(self) -> dict:
        """The blob stored in ``Config.validation_report`` (audit / reproducibility)."""
        return {
            "schema_id": self.schema_id,
            "schema_sha256": self.schema_sha256,
            "errors": self.errors,
        }


def _id_segments(schema_id: str) -> list[str] | None:
    """Return the path segments after ``/src/`` in an $id, or None if absent."""
    if not schema_id or _SRC_MARKER not in schema_id:
        return None
    tail = schema_id.split(_SRC_MARKER, 1)[1]
    return [seg for seg in tail.split("/") if seg]


class SchemaRegistry:
    def __init__(self) -> None:
        self._loaded_from: str | None = None
        self._by_id: dict[str, dict] = {}
        self._sha: dict[str, str] = {}
        # source -> {type: $id}
        self._types: dict[str, dict[str, str]] = {}
        # source -> umbrella $id
        self._umbrella: dict[str, str] = {}
        self._registry: Registry = Registry()

    # -- loading ----------------------------------------------------------------

    def load(self, schema_dir: str | None = None) -> None:
        """(Re)scan ``schema_dir`` and rebuild the index. Safe to call repeatedly."""
        schema_dir = schema_dir or settings.schema_dir
        self._loaded_from = schema_dir
        self._by_id, self._sha, self._types, self._umbrella = {}, {}, {}, {}

        root = Path(schema_dir)
        if not root.is_dir():
            log.warning("schema_dir %r does not exist; validation is pass-through", schema_dir)
            self._registry = Registry()
            return

        resources: list[tuple[str, Resource]] = []
        for path in sorted(root.rglob("*.json")):
            try:
                schema = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("skipping unreadable schema %s: %s", path, exc)
                continue
            schema_id = schema.get("$id")
            if not schema_id:
                log.warning("skipping schema without $id: %s", path)
                continue
            segments = _id_segments(schema_id)
            if not segments:
                log.warning("schema $id has no '/src/' segment, ignoring: %s", schema_id)
                continue

            self._by_id[schema_id] = schema
            self._sha[schema_id] = hashlib.sha256(
                json.dumps(schema, sort_keys=True).encode()
            ).hexdigest()
            resources.append((schema_id, Resource.from_contents(schema)))

            # segments: [source, "schema.json"] -> umbrella; [source, type, ...] -> type
            source = segments[0]
            if len(segments) == 2:
                self._umbrella[source] = schema_id
            else:
                self._types.setdefault(source, {})[segments[1]] = schema_id

        self._registry = Registry().with_resources(resources)
        log.info(
            "loaded %d schema(s) from %s; governed sources: %s",
            len(self._by_id),
            schema_dir,
            ", ".join(sorted(self._types)) or "(none)",
        )

    def _ensure_loaded(self) -> None:
        if self._loaded_from is None:
            self.load()

    # -- queries ----------------------------------------------------------------

    def is_schema_governed(self, source: str) -> bool:
        self._ensure_loaded()
        return bool(self._types.get(source))

    def supported_types(self, source: str) -> list[str]:
        self._ensure_loaded()
        return sorted(self._types.get(source, {}))

    def get_type_schema(self, source: str, type_: str) -> dict | None:
        self._ensure_loaded()
        schema_id = self._types.get(source, {}).get(type_)
        return self._by_id.get(schema_id) if schema_id else None

    def get_umbrella_schema(self, source: str) -> dict | None:
        self._ensure_loaded()
        schema_id = self._umbrella.get(source)
        return self._by_id.get(schema_id) if schema_id else None

    # -- validation -------------------------------------------------------------

    def validate(self, source: str, type_: str, instance: dict) -> ValidationResult:
        """Validate a config's `json` against the (source, type) schema.

        Non-governed sources pass through (``governed=False``). For a governed source an
        unknown ``type`` is itself a validation error.
        """
        self._ensure_loaded()
        if not self.is_schema_governed(source):
            return ValidationResult(governed=False)

        schema_id = self._types.get(source, {}).get(type_)
        if schema_id is None:
            supported = ", ".join(self.supported_types(source))
            return ValidationResult(
                governed=True,
                errors=[{
                    "path": "type",
                    "message": (
                        f"unknown type {type_!r} for source {source!r}; "
                        f"supported types: {supported}"
                    ),
                }],
            )

        schema = self._by_id[schema_id]
        validator = Draft202012Validator(schema, registry=self._registry)
        errors = [
            {
                "path": "/".join(str(p) for p in err.absolute_path) or "(root)",
                "message": err.message,
            }
            for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
        ]
        return ValidationResult(
            governed=True,
            schema_id=schema_id,
            schema_sha256=self._sha[schema_id],
            errors=errors,
        )


# Module-level singleton; loaded at startup (api.main lifespan) and lazily on first use.
registry = SchemaRegistry()
