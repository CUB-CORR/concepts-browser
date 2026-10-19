---
title: Browsing concepts
summary: The concept list, the detail page, source tabs, version history, documentation and retired concepts.
icon: book-open
---

## The concept table {#list}

[All concepts](/concepts) is the app's front door. It is a table with one row per *name* registered in the active taxonomy — not one per concept — which is what lets a concept known by several names be found under any of them.

It opens sorted by **most used first**, and where two concepts are read equally often, by **most documentation first**. That default is deliberate: the two questions it answers together are "what does everyone here actually work with" and "which of these has somebody written down properly". Used means pulled through the API by a study — opening a concept in this app is not a read of it. Search instead, and relevance takes over the order — see below.

The taxonomy holds thousands of names, so the sorting, the filtering and the search all happen on the server — a page sorted in your browser would only sort that page. Everything you set is a query parameter, which means a link to a particular view is a link to exactly that view, and the browser's back button walks your filters backwards.

The table itself has no page controls: it loads the next fifty names as you scroll toward the bottom, and the count above it says how many matched altogether. How far you have scrolled is the one piece of table state deliberately *not* in the URL — a scroll position is not something you share.

The controls all live in a column to the left of the table, top to bottom. On a narrow screen there is no room for a column beside a table worth reading, so they fold into a **Filters and columns** disclosure above it, with the search box left out in the open.

- **Search** over the name, the label, the description *and* the concept's clinical, implementation and caveats documentation, answering as you type. Underscores need not be typed — *blood sodium* finds `lab_blood_sodium` — and from three characters up a small typo is forgiven too. Results come back **best match first**: a hit in the *name* always outranks one that appears only in the documentation, and among names an exact match beats a prefix, which beats a substring, which beats a typo. Sorting a column yourself overrides that — relevance then only breaks ties inside your sort. For a repository-wide search across every taxonomy see [Search and navigation](/docs/search).
- **Status** — the documentation workflow label, as a multi-select with a count beside each value. *(none)* selects the concepts carrying no status at all. The counts are computed ignoring the status filter itself, so ticking one value never hides the others.
- **Sources** and **Types** — the same idea for the sources a concept is defined for and the config types those definitions use, plus a selector for whether it has a definition at all (*All concepts* / *Configured only* / *Unconfigured only*).
- **Columns** — which columns are shown. See below.
- **Export** — :cap[can_admin]. Downloads the filtered list as CSV or Excel, optionally with each source's latest published JSON and Python as extra columns. It exports everything your filters match, not just the rows you have scrolled to.
- **New concept** — :cap[can_edit]. Covered in [Editing and publishing](/docs/editing#new).
- **Show retired names** — a switch that adds retired names back into the table (`?include_deprecated=true`).

## Columns {#columns}

Click a column heading to sort by it; click it again to reverse. Whatever you sort by, the default order stays underneath as the tiebreaker, so equal values fall back to the better-documented concept rather than to an arbitrary one — and the order never shuffles a row from one slice of the scroll into another.

Out of the box the table shows **Name**, **Status**, **Types**, **Sources**, **Version**, **Description** and **Reads**, in that order — what the concept is called, how far along it is, how it is defined, and only then what it means and how much it is used.

**Columns** in the sidebar shows or hides the rest. Name is always there; the rest are yours to choose, and your choice rides in the URL along with everything else — so a link you share carries the columns you picked, and a link without them opens the default set.

| Column | What it says |
| --- | --- |
| Name | The identifier, its badges and the concept's `#id`. Always shown; the link carries the as-of date with it. |
| Description | The opening of the concept's *clinical* documentation — the first 120 characters or so, on one line, with the rest on hover. Shown by default. Only the excerpt is sent to your browser; the full prose lives on the concept page. |
| Label, Summary | The name's display name, and the concept's own one-line `description` field — a different thing from the *Description* column above, which is documentation, so the two are named apart. Both off by default. |
| Docs | How much documentation the concept carries, as :badge[S]{variant=secondary mono} / :badge[M]{variant=secondary mono} / :badge[L]{variant=secondary mono}, over the combined length of the clinical, implementation and caveats text — under 400 characters is S, under 1500 is M, above that L, and a dash means nothing has been written. Sorting the column sorts by the underlying length, not by the letter. The character count itself is deliberately not a column: it is a measurement, not an answer to whether a concept is documented well enough. |
| Reads, My reads | How often the concept has been pulled through the API, and how much of that is yours. Opening it here is not a read: the count measures what studies actually query, so it cannot be moved by clicking around. The totals say how often something is read, never by whom — see [Administration](/docs/admin). |
| Sources, Types, Version | The sources the concept has a published definition for, the config types those use, and its current published version. |
| Status | The documentation workflow label (e.g. *In Production*), the same value the Status filter selects on. Shown by default. |
| Last edited, Last edited by | When the concept's latest version was published, and who published it. Imported definitions have no author and show a dash. |
| Names | How many names the concept holds across all taxonomies — a quick read on how many vocabularies already point at it. |

:::alert[Under the as-of date]{icon=info}
The date lens moves the versioned columns — version, sources, types and *Last edited* are all computed as of that moment. Reads, documentation and status are concept-level and carry no history, so they can only ever show today's values; the table says so above itself rather than letting a historical row imply the past was measured.
:::

## Reading the badges {#badges}

A row's badges tell you what kind of name you are looking at:

| Badge | Meaning |
| --- | --- |
| :badge[group of N] | This one name points at several concepts. Each member is its own row, so their reads and documentation can be told apart; the name itself opens a picker for the member you meant. |
| :badge[alias] | Another name of a concept the table lists elsewhere — a secondary name, not a second concept. |
| :badge[retired name] | The name was retired but still resolves — old links and old pins keep working. Shown only with *Show retired names* on; the whole row is dimmed. |
| :badge[deprecated] | The *concept* itself was retired. See [Retired concepts](#deprecation). |
| :badge[auto] | An auto-generated definition. Read-only: it is derived rather than authored, and is not versioned or editable here. |
| :badge[v3] | The concept's current published version in the *Version* column, or a dash when nothing has been published yet. The `#id` after the name is the concept's permanent identifier. |

## The concept page {#detail}

Clicking a row anywhere opens `/concepts/tax/<taxonomy>/<name>`, and a middle- or modifier-click opens it in a new tab. The header carries the name, the display name, the current version, the taxonomy, and the concept id — click it to copy it. Underneath, **Also known as** lists every other name the concept holds, in every taxonomy, with retired ones struck through and explained rather than hidden.

If the name is a group, an amber banner says so and offers a **Member** selector; the member you are looking at is pinned in the URL as `?cid=<id>`, which is what makes a link to one member of a group unambiguous.

## Definitions, per source {#sources}

The left column is a tab per source the concept is defined for. Each tab shows that source's current published definition:

- **Version metadata** — the version number, the config type, the change type (*initial*, *improvement*, *critical*), the author and timestamp, and the message describing what changed. A definition superseded by a critical correction says so in red, naming the version that fixes it.
- **Definition** — the JSON configuration, viewable either as a readable field view driven by the source's schema or as raw JSON; a toggle switches between them.
- **Python** — :cap[can_read_detail] — the snippet, syntax-highlighted, with a copy button; and above it the data files this version pins, each with its version, size, a download, a link to the file's history, and a button that copies the `getfile("…")` accessor. See [Data files](/docs/files). Without that capability the section still lists what is pinned — which file, at which version — but shows a lock in place of the code and the downloads, and names the capability you would need.
- **History** — every published version of this source's definition, newest first, the current one badged. Clicking one loads it; a copy button beside it copies a ready-made API reference pinned to that exact version, which is what you paste into a study's code.

:::alert[Version numbers are per concept]{icon=info}
A concept's version counter is shared by all its sources. So one source's history can jump from `v2` to `v5` — the numbers in between belong to its siblings, and `v5` still identifies one point in the concept's history.
:::

Pinning a version puts `?v=` in the URL and shows a blue banner saying you are not looking at the latest, with a **Back to latest** link. Opening a draft does the same with `?draft=`.

## Documentation {#documentation}

The right column carries the human-readable half: a **Documentation** card with a status badge, a caveats callout, and clinical and implementation descriptions. Where a deployment syncs documentation from an external source, an *Open in Notion* button links to the page it came from.

Editing the text needs :cap[can_edit]; changing the *status* needs :cap[can_publish], so the two controls can appear separately. Unlike a definition, documentation is not versioned — it describes the concept, not a particular release of it.

:::alert[Synced documentation is overwritten on reimport]{icon=info}
Where a deployment syncs documentation from an upstream export, the reimport is the authority: the clinical and implementation descriptions, the caveats and the status are replaced from upstream for every concept the export names — an in-app edit to those fields is a stopgap, not a permanent record. Concepts the export does not mention keep what they have.
:::

## Retired concepts and retired names {#deprecation}

Two different things get retired, and the distinction matters:

- **A name** is retired when a concept is renamed. The old name keeps resolving to the same concept forever — old links and old code do not break — and the concept page explains what it is now called.
- **A concept** is retired when it should no longer be used at all. A red banner says so, nothing is deleted, no version is renumbered, its names keep resolving, and it takes no new versions. Where a replacement was recorded, a button takes you straight to the successor.

Retiring a concept is not something you do directly: anyone with :cap[can_edit] can *request* it, and a reviewer decides. See [Editing and publishing](/docs/editing#deprecation).

## Reporting a problem with a definition {#issues}

When this deployment has configured an issue tracker, every concept page carries a **Report issue** button. It opens the tracker in a new tab with the concept's taxonomy and name already filled into the report, so you do not have to describe which definition you mean.

:::if{feature=issue-tracker}
This deployment has one configured, so the button is present on every concept page. It needs no capability beyond being able to read the concept.
:::

:::unless{feature=issue-tracker}
*This deployment has not configured a tracker, so the button is not shown. Report problems through whatever channel your team uses.*
:::
