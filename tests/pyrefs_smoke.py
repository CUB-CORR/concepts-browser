"""Reading `getfile("<uuid>")` out of a snippet. Run: uv run python tests/pyrefs_smoke.py

`api/pyrefs.py` is the only thing that decides which files a definition reads, so what it does
*not* match matters as much as what it does: a regex over the text would find `getfile` in a
docstring, in a comment, and in the string `'getfile("x")'`, and would have no way to tell a
literal argument from a computed one.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.pyrefs import referenced_uuids  # noqa: E402

A = "6f1e0c2a-0000-0000-0000-000000000001"
B = "6f1e0c2a-0000-0000-0000-000000000002"


def uuids(py: str | None) -> set[str]:
    return referenced_uuids(py)[0]


def warnings(py: str | None) -> list[str]:
    return referenced_uuids(py)[1]


# --- what counts ------------------------------------------------------------------------------
assert uuids(f'x = getfile("{A}")') == {A}
assert uuids(f"x = getfile('{A}')") == {A}           # either quote style
assert uuids(f'x = getfile(\n    "{A}",\n)') == {A}  # and however it is laid out
# Several references, anywhere in the module: a nested function, a comprehension, a default.
assert uuids(
    f'''
def outer(var, cohort):
    def inner():
        return read(getfile("{A}"))
    return [read(getfile("{B}")) for _ in range(1)]
'''
) == {A, B}
# The same file twice is one reference — the answer is a set of files, not of call sites.
assert uuids(f'a = getfile("{A}")\nb = getfile("{A}")') == {A}

# --- what does not ----------------------------------------------------------------------------
assert uuids(None) == set() and uuids("") == set() and uuids("   \n") == set()
assert uuids("def f():\n    return 1") == set()
# In a string, in a docstring, in a comment: text that mentions the call is not the call.
assert uuids(f'"""reads getfile(\\"{A}\\")"""\nx = 1') == set()
assert uuids(f'x = \'getfile("{A}")\'') == set()
assert uuids(f'# getfile("{A}")\nx = 1') == set()
# A `getfile` on an object is a different function that happens to share a name.
assert uuids(f'x = helpers.getfile("{A}")') == set()

# --- what is neither: a call this cannot read --------------------------------------------------
# Not "no reference" — a reference whose target is only known at run time. It is reported as
# prose so a draft can warn, and it never blocks a publish: nothing here can prove it wrong.
found, notes = referenced_uuids(f'k = "{A}"\nx = getfile(k)')
assert found == set(), found
assert len(notes) == 1 and "getfile(k)" in notes[0] and "line 2" in notes[0], notes

found, notes = referenced_uuids(f'x = getfile(f"{{prefix}}-{A}")')
assert found == set() and len(notes) == 1, (found, notes)

found, notes = referenced_uuids("x = getfile()")
assert found == set() and len(notes) == 1, (found, notes)

# A resolvable call alongside an unresolvable one yields both answers.
found, notes = referenced_uuids(f'a = getfile("{A}")\nb = getfile(key)')
assert found == {A} and len(notes) == 1, (found, notes)

# --- a snippet that does not parse --------------------------------------------------------------
# The answer is *unknown*, not empty, and saying so is the whole point: silently reporting no
# references would let a broken draft publish as one that reads nothing.
found, notes = referenced_uuids("def f(:\n    pass")
assert found == set(), found
assert len(notes) == 1 and "does not parse" in notes[0], notes

print("PYREFS SMOKE OK")
