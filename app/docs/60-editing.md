---
title: Editing and publishing
summary: Drafts, the editor, validation, the review queue, publishing a version, naming, renaming and retiring.
icon: pencil
---

## The shape of the workflow {#flow}

Nothing goes live in one step. A change moves through four stages:

1. **The concept exists** — a name registered in a taxonomy, pointing at a concept. :cap[can_edit]
2. **A draft is written** for one source: a JSON definition, optionally a Python snippet. Invisible to readers. :cap[can_edit]
3. **It is reviewed** — the draft appears in [the review queue](/review). :cap[can_publish]
4. **It is published** — assigned the next version number and made the active definition. :cap[can_publish]

Once published, a version is immutable. Correcting it means publishing another one; the history keeps both.

## Creating a concept {#new}

[Add a concept](/concepts/new) — :cap[can_edit] — offers two paths, and choosing the right one matters:

- **New concept** — a name, an optional display name, a description and a taxonomy. Names are lowercase_snake_case, used in code and URLs.
- **Alias** — when what you want to add is another *name* for something already defined. Find the concept by whatever it is already called, then register the new identifier against it. A name that means something already defined belongs on that concept, not on a second one. Both names then resolve to the same concept, and retiring either one leaves the other working.

:::alert[Groups are never accidental]{icon=info}
If the identifier you chose already names another concept, the app refuses and shows you which — because a shared name creates a *group*, where one name resolves to several concepts. That is allowed and sometimes correct, but you have to confirm it explicitly with **Create the group anyway**; your typed values are kept.
:::

A concept must exist before any definition can be added to it, so this is always the first step. Creating one lands you on its (empty) concept page.

## Drafts {#drafts}

On a concept page, with :cap[can_edit], there are two ways to start a draft:

- **New draft from v&lt;n&gt;**, below an existing source's definition — copies the current published JSON, snippet and type as a starting point. This is the normal path for improving a definition.
- **The “+ add source” tab** — for a source this concept has no definition for yet. Pick the source and the config type; the editor opens seeded from that type's schema. This is also the only way to change a definition's type, since a copied draft keeps the type it copied.

A draft belongs to one `(concept, source)` pair. It is listed at the top of that source's history in amber, is reachable at `?draft=<id>`, and can be discarded at any time — discarding never touches published versions. Auto-generated definitions refuse drafts entirely: they are derived, not authored.

## The editor {#editor}

The draft editor has two halves.

**The definition** is edited as a schema-driven form for schema-governed sources — each field labelled and validated as you type, with a running count of validation issues and a "schema valid" indicator when it is clean. Sources that are not schema-governed get a raw JSON textarea instead. The API re-validates on save and, if it refuses, lists the offending paths.

**The snippet** is a full code editor with Python completion. A new config is seeded with this shape:

::py-template{variable=serum_creatinine}

The signature line and the closing `return` are locked — only the body is editable — so a definition always has the shape the extractor expects. Completion knows the names, signatures and docstrings the source publishes, plus `var`, `cohort` and the usual data libraries. It deliberately does not guess at the type of a chained expression rather than complete something wrong.

**Insert file** opens a picker over the current source's file library and writes `getfile("<uuid>")` at the cursor, so you never type a uuid. Uuids that name no file in the library are underlined as errors as you type. See [Data files](/docs/files#getfile).

Every draft carries a **message** — what changed and why — and a **change type**: *improvement* for an ordinary revision, *critical* when the previous version was wrong in a way that matters. A critical publication is surfaced on the versions it supersedes, so somebody reading an old version is told it was corrected.

## Two warnings the editor raises {#warnings}

**Unresolved file references.** A `getfile("…")` naming no file in this source's library. Fine while drafting, fatal at publish: the publish is refused and the offending uuids named, because a definition that cannot find its data is not a definition.

**A pinned file has a newer version.** Drafts are deliberately never cascaded into — unlike published definitions, which are re-published when a file they read changes. So the editor tells you instead: "pinned v2, now v3". Publishing the draft pins the current version. See [the cascade](/docs/files#cascade).

## Testing a draft before it is published {#testing}

A draft is servable, so you can run one against real data before asking anybody to review it. Pin a variable to it with a `::draft<id>` suffix — the id is the number in `?draft=<id>` on the concept page, the one the amber banner reads back as *draft #1042*, and the one *Open draft* in the queue navigates to.

```python
from corr_vars import Cohort

cohort = Cohort(
    obs_level="icu_stay",
    sources={"cub_hdp": {"database": "db_my_study_prepared"}},
    project="my-project",
    load_default_vars=False,
)

# The id is the one in ?draft=<id> on the concept page.
cohort.add_variable("serum_creatinine::draft1042")

print(cohort.obsm["serum_creatinine"])

# After each save in the editor, re-extract instead of reusing the cached copy.
cohort.add_variable("serum_creatinine::draft1042", use_cache=False)
```

The draft is an **overlay**, not a whole cohort: it replaces the published config of its own `(concept, source)` pair and leaves every other source on its published definition, so what you are testing is exactly the one change. The pin applies to that variable alone — a draft belongs to one concept, so pinning a whole cohort to a draft id is not a useful thing to do, and a name that resolves to a group of concepts refuses a draft pin outright.

corr-vars caches an extract, so pass `use_cache=False` after each save or you will keep reading the previous attempt. Reading a draft needs no special capability beyond the :cap[can_read_detail] any corr-vars key needs — the snippet is code, and code is what that capability unlocks. See [CORR Vars](/docs/corr-vars).

## The review queue {#review}

[Review](/review) collects everything waiting for a decision in one place — otherwise it sits on individual concept pages, which is how work goes unnoticed. Two sections:

- **Drafts awaiting review** — every open draft across every concept, with its source, change type, message, author and age. *Open draft* takes you straight into the editor with the draft loaded on the right concept and source.
- **Deprecation requests** — names, or the concepts behind them, somebody asked to retire, each badged with which of the two approving it would cost; filterable by *Pending*, *Approved*, *Rejected* or *All* (the filter is in the URL).

The **Review** count in the top bar is these two lists added together — open drafts plus deprecation requests still pending. A request that has been approved or rejected has been decided, so it stops counting.

**Watching and answering are one capability.** :cap[can_publish] opens the queue and puts the decision buttons on it — whoever reviews is whoever publishes. There is no separate look-but-don't-touch grant, because a reviewer who cannot act on what they see is a bottleneck rather than a safeguard.

## Publishing {#publish}

**Publish** — :cap[can_publish] — is in the draft editor, behind a confirmation that spells out what it does: assign the next version number and make this the active definition for that source. Publish uses the last *saved* draft, so save before publishing.

The confirmation also carries **Notify users and project leads by email**, which emails everyone who has used this concept and the leads of projects it was used in. It is ticked for you when the change type is *critical* and left clear for an *improvement* — a default, not a rule: tick or untick it before confirming.

On publish, the repository:

- assigns the next version number in the concept's sequence, across all its sources;
- records who approved it and when, alongside who wrote it — the two are separate for a reason;
- pins the current version of every data file the snippet reads, freezing this definition against exactly those bytes;
- forces the change type of a source's very first published definition to *initial*.

:::alert[Publishing is immediately visible]{variant=destructive}
Every client asking for "latest" gets the new version from that moment. Clients that pinned a version are unaffected — which is why pinning is the recommended practice for a running study.
:::

## Renaming a concept {#renaming}

**Rename in &lt;taxonomy&gt;** — :cap[can_edit] — on the concept page. It is not an edit of the old name: the new name is registered first, then the old one is retired. The old name keeps resolving to the same concept, so links and pinned versions stay valid, and the concept page explains the old name rather than 404ing on it.

If the new name already names another concept, you are told, and continuing creates a group — an explicit choice, never a silent one.

## Naming a concept in another taxonomy {#names}

A concept is one identity with a name per naming system, and it need not have one everywhere. On its page, the taxonomy selector greys out the taxonomies it has no live name in — picking one opens **Name &lt;concept&gt; in &lt;taxonomy&gt;** — :cap[can_edit] — which asks for the identifier that taxonomy uses (and an optional display name), registers it, and takes you to the concept's new page there.

It is one write and it adds only: no other name is touched, no version is created, and the concept keeps its id. If the identifier already names another concept you are told, and continuing creates a group — the same explicit choice a rename asks for. A name typed in here belongs to you, not to the reference import: a later import will not retire it.

Without :cap[can_edit] the greyed-out entries still explain themselves — they just do not offer the form.

## Retiring a name, or a concept {#deprecation}

An editor *requests*; a reviewer *decides*. **Request deprecation** — :cap[can_edit] — asks for a reason and, optionally, the concept clients should follow instead. That is all it does: it files a request.

The request is about the name you filed it from, and how much that costs depends on how many names the concept has. Retiring an alias from a concept that answers to other names retires *only that name*: it stops listing, the concept stays live under the rest, keeps taking new versions, and its successor is left alone. Retiring a concept's *last* name is retiring the concept. The review queue says which of the two an approval will do before you decide.

The request lands in [the review queue](/review), where :cap[can_publish] approves or rejects it. Approving a concept-level request marks the concept retired and records the successor; the reviewer can override the suggested successor. Nothing is deleted, no version is renumbered, and retired names keep resolving — the concept simply takes no new versions, and readers are pointed at the replacement.
