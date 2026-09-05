"""Which data files a ``py`` snippet reads, read out of the snippet itself.

A snippet names a file by the **uuid** it has in its source's library:

    mapping = pd.read_csv(getfile("6f1e0c2a-…"))

That call is the only form there is. The file's *path* never appears in the snippet, which is
what lets a file be renamed without touching a single definition, and what lets a config pin a
file **version** rather than a path whose contents may since have been replaced.

Reading the uuids out is an AST walk rather than a regex: ``getfile`` inside a string literal
or a comment is not a reference, and a call whose argument is computed at run time
(``getfile(key)``) is not one either. The second kind is not "no reference" — it is a reference
this cannot resolve — so it comes back separately, as prose, for a draft to warn about. It is
never a publish blocker: nothing here can prove such a call is wrong, only that it is opaque.

An earlier model let a snippet reach a file by writing out ``Path(__file__).parent / "x.csv"``
and had the API work out what that resolved to. That is gone: the uuid call is the whole
contract, and there is deliberately no second way to say the same thing.
"""
from __future__ import annotations

import ast

# The name a snippet calls to reach a file. Also what the app's editor completes and what its
# file picker inserts, so changing it is a change to every stored snippet.
GETFILE = "getfile"


def _describe(node: ast.Call) -> str:
    """A one-line account of a `getfile(...)` call whose argument is not a string constant."""
    try:
        rendered = ast.unparse(node)
    except Exception:  # noqa: BLE001 — a description is never worth an exception
        rendered = f"{GETFILE}(...)"
    return f"line {node.lineno}: {rendered} does not name a file uuid directly"


def referenced_uuids(py: str | None) -> tuple[set[str], list[str]]:
    """``({uuid, …}, [warning, …])`` for one snippet.

    The set is every uuid the snippet reads a file by. The list describes the calls that could
    not be read: a ``getfile`` whose argument is not a string constant, and — one entry — a
    snippet that does not parse at all, since a syntax error means the answer is *unknown*
    rather than empty.

    An empty snippet (or ``None``) references nothing, which is the common case: most
    definitions are pure JSON and carry no Python at all.
    """
    if not py or not py.strip():
        return set(), []

    try:
        tree = ast.parse(py)
    except SyntaxError as exc:
        return set(), [f"the snippet does not parse ({exc.msg} on line {exc.lineno})"]

    uuids: set[str] = set()
    warnings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # `getfile(...)` as a bare name only. An attribute access (`mod.getfile`) is a
        # different function that happens to share a name — the snippet namespace binds
        # exactly one `getfile`, and it is not on any object.
        if not (isinstance(node.func, ast.Name) and node.func.id == GETFILE):
            continue
        arg = node.args[0] if node.args else None
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            uuids.add(arg.value)
        else:
            warnings.append(_describe(node))
    return uuids, warnings
