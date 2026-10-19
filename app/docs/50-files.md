---
title: Data files
summary: The per-source file libraries, uuids and versions, which concepts read a file, and what an upload cascades into.
icon: database
---

## What a data file is {#what}

Some definitions cannot be expressed in JSON and code alone: they need a lookup table, a mapping of codes to categories, a fitted model. Those are **data files**. They live in the repository next to the definitions that read them, versioned the same way, so a published concept version stays reproducible even after the table behind it is corrected.

A file belongs to **one source**. There is no global file list — picking the source is the first step, not a filter, which is why [the files area](/files) opens on a card per source rather than on a table of files.

## A source's library {#library}

Opening a source card takes you to that source's library, `/files/<source>`. Each row is a file as it stands now: its path, its size, its current version number, when and by whom it was last updated, and — the number that matters most — how many concepts' *current published* definitions read it.

Opening a file, `/files/<source>/<uuid>`, gives you its full version history (each version with its own path, digest, size, author and message), the list of concepts that reference it, and a download for any version.

:::alert[Metadata and bytes are gated differently]{icon=lock}
Everything *about* a file — that it exists, its path, size, digest, its versions, who changed it, which concepts read it — is :cap[can_read]. The **contents** are :cap[can_read_detail]. Without it the libraries and histories read exactly as they do for anyone else, but the download controls are replaced by a lock saying "Download requires read-detail access" rather than offering a link that would fail.
:::

## Uuids, paths and versions {#uuids}

Three identifiers do three different jobs, and conflating them is the usual mistake:

| Thing | What it is |
| --- | --- |
| uuid | The file's permanent identity. It never changes — not when the file is renamed, not when its contents are replaced. This is what a snippet references. |
| path | The name the file is known by *in this source*, which a new version may change. A path is unique within a source at any one time, so a rename onto a name another file holds is refused and the page tells you which file is in the way. |
| version | A per-file counter starting at 1. A concept version does not reference "the file", it references *this uuid at this version* — the pin that keeps it reproducible. |

:::alert[Uuids are derived, not random]{icon=info}
A file's uuid is computed from its source key and the path it was first created under, by a rule corr-vars shares. That is what lets a definition be written with the right `getfile("…")` call before the file has ever been uploaded here.
:::

## Reading a file from a snippet {#getfile}

A Python snippet reaches its data through `getfile("<uuid>")`, which resolves to the bytes of the version this definition is pinned to. It is the only way in — a snippet never opens a path, and there is no relative-path mechanism.

```python
import pandas as pd

def postcode_region(var, cohort):
    # getfile() takes the file's uuid — never its path. The uuid is stable across
    # renames, which is what keeps an old published version reproducible.
    mapping = pd.read_csv(getfile("6f1e0c2a-1111-5222-8333-444455556666"))
    var.data = var.data.merge(mapping, on="postcode", how="left")
    return var.data
```

You do not have to type uuids. The [editor](/docs/editing#editor) has a file picker: it lists the current source's library and inserts the `getfile("…")` call for the file you choose. Which is also why reading a source's file list only needs :cap[can_read] — everyone who can read a definition can see what it reads.

The references are found by parsing the snippet, not by pattern-matching text: the word `getfile` inside a string or a comment is not a reference, and a call whose argument is computed rather than a literal is reported as something the repository cannot resolve for you (a warning, never a blocker). A `getfile("…")` naming no file in the source's library *is* a blocker — publishing is refused until it resolves.

On a concept page, everything the current definition pins is listed alongside it with its version, and each entry links into the file library and offers the exact bytes that version was published against.

## Uploading a new version {#upload}

On a source's library page you can add a file; on a file's own page you can replace it. Both ask for a path, the bytes, and an optional message describing the change. Both require :cap[can_publish] — see [the cascade](#cascade) for why an upload is a publish and not an edit.

When the upload would replace an existing file, the dialog will not let you commit straight away: it first offers **Review impact**, which fetches and shows exactly which concepts read the file today. Only then does the button become **Upload new version**. Afterwards the toast tells you what actually happened — a version number, a rename, or nothing at all.

Two conveniences worth knowing:

- **Identical bytes do nothing.** If what you upload matches the current version exactly, no version is minted and nothing is cascaded; the page reports it as unchanged. Re-running an import is therefore safe.
- **A new version may rename the file.** Replacing a file while giving it a different path moves the path and keeps the uuid — so every snippet that references it keeps working, and every old version keeps the name it was uploaded under.

Uploads are bounded: there is a maximum size and an allowed set of file types (tabular and serialised-data formats — CSV, TSV, Parquet, JSON, XLSX, pickles, plain text). Paths must be relative and well-formed; absolute paths, backslashes and `..` segments are refused.

## The cascade — what an upload does downstream {#cascade}

This is the part to understand before you upload anything. A concept version pins a file version. If the file moves on and nothing else happens, every published definition would keep reading the old bytes forever — correct, but not what you wanted when you fixed a mapping table.

So an upload **cascades**. For every concept whose current published definition reads the file, the repository publishes a *new version of that concept*: same JSON, same snippet, same type, only the pin moved to the new file version. The change is recorded with its own change type so history shows plainly that the definition itself did not change — its data did.

:::alert[An upload publishes]{variant=destructive}
Uploading one file can mint versions of many concepts at once, visible immediately to every client that asks for "latest". The dialog tells you how many concepts read the file before you commit, and the result tells you exactly which ones were bumped. Read that number.
:::

What the cascade deliberately does *not* touch:

- **Older concept versions.** They keep their original pin. A study that pinned `v3` a year ago still resolves to the same bytes. That is the whole point.
- **Drafts.** An unpublished draft is never cascaded into. Instead the drift is shown to you: the draft says which files it pinned have since moved on, and publishing it pins the current versions.
- **Retired concepts** and auto-generated definitions, which are not versioned here.
- **A concept already on the newest pin** — cascading is idempotent, so nothing is double-versioned.

## Retiring a file {#retire}

A file can be retired from its own page — :cap[can_publish]. It is always a soft retirement: nothing is deleted, and every version stays downloadable at the pins that reference it, because an old concept version must keep resolving.

While any current published definition still reads the file, retiring it is refused and the page names the concepts standing in the way, so you know what to change first. Uploading again to a retired file's path brings it back.
