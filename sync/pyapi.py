"""Generates ``pyapi.json``: the names a `py` snippet can call, for editor autocomplete.

The app's code editor had a hand-written eight-item completion list, which is wrong the day
upstream adds a helper. This builds the list instead, from three places, and the API serves it
at ``GET /sources/{key}/pyapi``.

**What this is.** Name + signature + first docstring line, per completable symbol. That is
enough for "what can I type here, and what does it take". It is emphatically **not** type
inference: nothing here knows that ``pl.read_csv(...)`` returns a ``DataFrame``, so completing
a chained expression (``var.data.group_by(...).<tab>``) is out of scope. Doing that properly
means a real language server — Pyright compiled to WASM, which the editor's existing comments
already anticipate — and is deliberately not attempted here. A generated flat surface is worth
having in the meantime precisely because it cannot drift from upstream.

**Where the names come from.**

1. *corr_vars helpers* — ``helpers.py`` and ``utils/*.py``, read as source and parsed with
   `ast`. Static parsing, not importing: the sidecar has no corr_vars checkout, no database
   drivers and no reason to execute upstream code to find out what it defines.
2. *the snippet's own scope* — the import header of ``variables.py`` (what a snippet may
   reference without importing it: ``pl``, ``np``, ``pd``, ``ibis``, ``helpers``, ``utils``,
   ``logger``, ``__``, ``comorbidity``, ``partial``, …), the fields of ``VariableContext``
   (``var.var_name``, ``var.dynamic``, ``var.time_window``, ``var.required_vars``,
   ``var.data``, ``var.files``) and ``Cohort``'s public surface. All read from upstream, so
   adding a field upstream is all it takes to have it completed here.
3. *polars and pandas* — introspected from the **installed** packages (`dir` +
   `inspect.signature` + the first docstring line), because that is the only source of truth
   for the version a snippet actually runs against. Every lookup is guarded: plenty of members
   raise on `getattr` (deprecation shims) or have no retrievable signature (C extensions).

**The shape it writes** (the frontend consumes this; keep it stable)::

    {
      "generated_at": "2026-07-27T10:00:00Z",
      "source": "cub_hdp",                  # which source's snippets this describes
      "globals": [Member, ...],             # names usable bare inside a snippet
      "modules": {                          # `<alias>`: what `<alias>.` completes to
        "pl": {
          "origin": "package" | "corr_vars",
          "module": "polars",               # dotted module path it came from
          "doc": "first docstring line or null",
          "functions": [Member, ...],       # module-level callables
          "types": {"DataFrame": {"doc": ..., "members": [Member, ...]}, ...}
        }, ...
      },
      "context": {                          # the two arguments every snippet is handed
        "var":    {"doc": ..., "members": [Member, ...]},
        "cohort": {"doc": ..., "members": [Member, ...]}
      }
    }

    Member = {
      "name": "read_csv",
      "kind": "function" | "attribute",
      "signature": "(source, *, has_header=True)" | null,   # null = not retrievable
      "returns": "pl.DataFrame" | null,                     # annotation as written, if any
      "doc": "first line of the docstring" | null
    }

`signature` is the parameter list only, parentheses included, so a client can render
``name(params)`` without re-parsing. Anything unknown is ``null``, never an empty string or a
guess — a client showing "no signature available" is better than one showing a wrong one.
"""
from __future__ import annotations

import ast
import inspect
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

log = logging.getLogger("vars-sync.pyapi")

PYAPI_NAME = "pyapi.json"

# Packages introspected live, with the types whose members a snippet chains onto. The aliases
# are the ones variables.py imports them under, so `modules` is keyed the way a snippet writes
# them. Anything not installed is skipped with a warning rather than faked.
INTROSPECTED = {
    "pl": ("polars", ["DataFrame", "LazyFrame", "Expr", "Series"]),
    "pd": ("pandas", ["DataFrame", "Series"]),
}

# The dataclass a snippet receives as `var`, and the class it receives as `cohort`.
CONTEXT_CLASS = "VariableContext"
COHORT_CLASS = "Cohort"

_ARG_LINE = re.compile(r"^(?P<name>\w+)\s*(?:\((?P<type>[^)]*)\))?\s*:\s*(?P<doc>.*)$")


# --- shared helpers -------------------------------------------------------------------------


def _first_line(doc: str | None) -> str | None:
    """The summary line of a docstring. One line is what fits in a completion popup; the rest
    is reference material the editor has no room for."""
    if not doc:
        return None
    for line in inspect.cleandoc(doc).splitlines():
        if line.strip():
            return line.strip()
    return None


def _member(name, kind, signature=None, returns=None, doc=None) -> dict:
    return {
        "name": name,
        "kind": kind,
        "signature": signature,
        "returns": returns,
        "doc": doc,
    }


# --- (1) corr_vars modules, read as source --------------------------------------------------


def _signature_of(node: ast.FunctionDef | ast.AsyncFunctionDef, *, drop_self: bool) -> str:
    """The parameter list as written upstream, defaults and annotations included.

    `ast.unparse` on the arguments node gives exactly the source form, which is what a reader
    wants to see — normalizing it would only lose the author's spelling of a default.
    """
    args = node.args
    if drop_self and args.posonlyargs + args.args:
        args = ast.arguments(
            posonlyargs=args.posonlyargs[1:] if args.posonlyargs else [],
            args=args.args if args.posonlyargs else args.args[1:],
            vararg=args.vararg,
            kwonlyargs=args.kwonlyargs,
            kw_defaults=args.kw_defaults,
            kwarg=args.kwarg,
            defaults=args.defaults,
        )
    return f"({ast.unparse(args)})"


def _function_member(
    node: ast.FunctionDef | ast.AsyncFunctionDef, *, drop_self: bool = False
) -> dict:
    return _member(
        node.name,
        "function",
        signature=_signature_of(node, drop_self=drop_self),
        returns=ast.unparse(node.returns) if node.returns else None,
        doc=_first_line(ast.get_docstring(node)),
    )


def scan_source_module(source: str, *, module: str, origin: str = "corr_vars") -> dict:
    """Every public top-level function of one module, from its source text."""
    tree = ast.parse(source)
    return {
        "origin": origin,
        "module": module,
        "doc": _first_line(ast.get_docstring(tree)),
        "functions": [
            _function_member(n)
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not n.name.startswith("_")
        ],
        "types": {},
    }


def star_imports(source: str) -> list[str]:
    """Sibling modules this one re-exports wholesale (``from .frames import *``).

    A package's ``__init__`` defines nothing itself but is what a snippet writes
    (``utils.merge_consecutive``), so the names it re-exports have to be folded into it or
    ``utils.`` completes to nothing at all.
    """
    return [
        node.module
        for node in ast.parse(source).body
        if isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module
        and any(a.name == "*" for a in node.names)
    ]


def scan_class(source: str, class_name: str) -> dict | None:
    """A class's public surface: methods (with `self` dropped) and annotated fields.

    Used for both halves of `context`. A dataclass field carries its type but no docstring of
    its own, so the per-field prose is lifted out of the class docstring's ``Args:`` block —
    which is where upstream documents them, and the only place that description exists.
    """
    tree = ast.parse(source)
    node = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == class_name),
        None,
    )
    if node is None:
        return None

    docstring = ast.get_docstring(node)
    field_docs = _args_section(docstring)
    members: list[dict] = []
    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name.startswith("_"):
                continue
            is_property = any(
                isinstance(d, ast.Name) and d.id == "property" for d in item.decorator_list
            )
            if is_property:
                members.append(
                    _member(
                        item.name,
                        "attribute",
                        returns=ast.unparse(item.returns) if item.returns else None,
                        doc=_first_line(ast.get_docstring(item)),
                    )
                )
            else:
                members.append(_function_member(item, drop_self=True))
        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
            name = item.target.id
            if name.startswith("_"):
                continue
            members.append(
                _member(
                    name,
                    "attribute",
                    returns=ast.unparse(item.annotation),
                    doc=field_docs.get(name),
                )
            )
    # A property and its setter share a name; keep the first (the getter carries the doc).
    seen: set[str] = set()
    unique = [m for m in members if not (m["name"] in seen or seen.add(m["name"]))]
    return {"doc": _first_line(docstring), "members": unique}


def _args_section(docstring: str | None) -> dict[str, str]:
    """``{field: description}`` from a Google-style ``Args:`` block."""
    if not docstring:
        return {}
    out: dict[str, str] = {}
    in_args = False
    current: str | None = None
    for raw in inspect.cleandoc(docstring).splitlines():
        line = raw.strip()
        if line.rstrip(":") in ("Args", "Arguments", "Attributes") and line.endswith(":"):
            in_args = True
            continue
        if not in_args:
            continue
        if line.endswith(":") and not _ARG_LINE.match(line) and line.rstrip(":").isalpha():
            break  # the next section (Returns:, Examples:, …)
        match = _ARG_LINE.match(line)
        if match:
            current = match["name"]
            out[current] = match["doc"].strip()
        elif current and line:
            out[current] = f"{out[current]} {line}".strip()
    return out


# --- (2) what a snippet may reference without importing it ----------------------------------


def scan_globals(variables_py: str) -> list[dict]:
    """The names variables.py's import header puts in scope for every snippet.

    Only real module-level imports count: a name imported under ``if TYPE_CHECKING`` does not
    exist at run time, so completing it would be an invitation to a NameError.
    """
    tree = ast.parse(variables_py)
    out: list[dict] = []
    for node in tree.body:  # module level only — skips the TYPE_CHECKING block's body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue  # a compiler directive, not a name anyone can call
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                out.append(_member(name, "attribute", returns=alias.name, doc=f"module {alias.name}"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                out.append(
                    _member(
                        name,
                        "attribute",
                        returns=f"{node.module}.{alias.name}",
                        doc=f"from {node.module}",
                    )
                )
    seen: set[str] = set()
    return [g for g in out if not (g["name"] in seen or seen.add(g["name"]))]


# --- (3) the installed packages --------------------------------------------------------------


def _live_member(owner, name: str) -> dict | None:
    """One introspected member, or None if it can't be looked at.

    Every step is guarded on purpose. `getattr` runs descriptors and deprecation shims that
    raise; `inspect.signature` raises for most C-implemented callables; `getdoc` can hit a
    property that computes. None of that is worth failing a generation run over — the member
    is simply reported with whatever could be read.
    """
    try:
        obj = getattr(owner, name)
    except Exception:  # noqa: BLE001 — a member that raises on access is just not completable
        return None
    kind = "function" if callable(obj) else "attribute"
    signature = None
    if kind == "function":
        try:
            signature = str(inspect.signature(obj))
        except (TypeError, ValueError):
            signature = None
        except Exception:  # noqa: BLE001
            signature = None
    try:
        doc = _first_line(inspect.getdoc(obj))
    except Exception:  # noqa: BLE001
        doc = None
    return _member(name, kind, signature=signature, doc=doc)


def introspect_package(module_name: str, type_names: list[str]) -> dict | None:
    """The installed package's top-level surface plus the members of its main types."""
    try:
        module = __import__(module_name)
    except Exception as exc:  # noqa: BLE001
        log.warning("%s is not installed (%s); its completions will be missing", module_name, exc)
        return None

    functions = []
    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        member = _live_member(module, name)
        if member is not None:
            functions.append(member)

    types: dict[str, dict] = {}
    for type_name in type_names:
        klass = getattr(module, type_name, None)
        if klass is None:
            log.warning("%s has no %s; skipping its members", module_name, type_name)
            continue
        members = []
        for name in sorted(dir(klass)):
            if name.startswith("_"):
                continue
            member = _live_member(klass, name)
            if member is not None:
                members.append(member)
        types[type_name] = {"doc": _first_line(inspect.getdoc(klass)), "members": members}

    return {
        "origin": "package",
        "module": module_name,
        "doc": _first_line(inspect.getdoc(module)),
        "functions": functions,
        "types": types,
    }


# --- assembly --------------------------------------------------------------------------------


def build(
    *,
    source_key: str,
    variables_py: str,
    helpers: dict[str, str],
    typing_py: str | None = None,
    cohort_py: str | None = None,
) -> dict:
    """Assemble the document. `helpers` maps the alias a snippet uses (``helpers``,
    ``utils.time``, …) to that module's source text."""
    modules: dict[str, dict] = {}
    stars: dict[str, list[str]] = {}
    for alias, source in helpers.items():
        try:
            modules[alias] = scan_source_module(source, module=alias)
            stars[alias] = star_imports(source)
        except SyntaxError as exc:
            log.warning("could not parse %s (%s); skipping it", alias, exc)

    # Fold a package's star re-exports into the package alias: `utils.merge_consecutive` is
    # what a snippet writes, even though the function is defined in `utils.frames`.
    for alias, submodules in stars.items():
        for sub in submodules:
            source_module = modules.get(f"{alias}.{sub}")
            if source_module is None:
                log.warning("%s re-exports %s, which was not fetched", alias, sub)
                continue
            modules[alias]["functions"].extend(source_module["functions"])
        modules[alias]["functions"].sort(key=lambda m: m["name"])

    for alias, (package, type_names) in INTROSPECTED.items():
        introspected = introspect_package(package, type_names)
        if introspected is not None:
            modules[alias] = introspected

    context: dict[str, dict] = {}
    if typing_py:
        var = scan_class(typing_py, CONTEXT_CLASS)
        if var is None:
            log.warning("%s not found upstream; `var.` completions will be missing", CONTEXT_CLASS)
        else:
            context["var"] = var
    if cohort_py:
        cohort = scan_class(cohort_py, COHORT_CLASS)
        if cohort is None:
            log.warning("%s not found upstream; `cohort.` completions will be missing", COHORT_CLASS)
        else:
            context["cohort"] = cohort

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "source": source_key,
        "globals": scan_globals(variables_py),
        "modules": modules,
        "context": context,
    }


def write(target_dir: Path, document: dict) -> Path:
    """Write pyapi.json into the reference dir the API serves it from."""
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / PYAPI_NAME
    path.write_text(json.dumps(document, indent=1, sort_keys=True))
    log.info(
        "wrote %s: %d global(s), %d module(s), context %s",
        PYAPI_NAME,
        len(document["globals"]),
        len(document["modules"]),
        ", ".join(document["context"]) or "(none)",
    )
    return path


def alias_for(repo_path: str, utils_dir: str) -> str:
    """The name a snippet reaches a corr_vars module by: ``helpers`` for the source's
    helpers.py, ``utils`` for the utils package, ``utils.time`` for a module inside it —
    matching how variables.py imports them."""
    stem = PurePosixPath(repo_path).stem
    if repo_path.startswith(f"{utils_dir}/"):
        return "utils" if stem == "__init__" else f"utils.{stem}"
    return stem
