---
title: Search and navigation
summary: Finding a concept by any of its names, the taxonomy selector, the as-of date lens and stable links.
icon: search
---

## Finding a concept {#finding}

There are three ways in, and they answer different questions:

- **The search box on [the concept list](/concepts)** filters what is already loaded, by name, label and description, within the active taxonomy. Fast, and the right tool when you roughly know what you are looking for.
- **The concept picker** — used wherever you have to point at another concept (adding a name to an existing concept, naming a successor when requesting a deprecation) — searches the whole repository across *every* taxonomy as you type, and shows each hit with all of its matching names, so you can tell two similarly named concepts apart before choosing one.
- **The URL**, when you already know the identity. See [stable links](#links) below.

## The taxonomy selector {#taxonomy}

A taxonomy is a naming system. The selector in the bar above the concept list chooses which one you are working in: it decides which names the list shows and which name a concept is presented under.

It is a **durable preference** — your choice is remembered between visits, so you stay in your own vocabulary without re-picking it. It also appears in the URL as `?taxonomy=<key>`, which is how you send someone a link that opens in a specific one.

Switching taxonomies does not change what exists, only what things are called. A concept with no name in the taxonomy you selected simply does not appear in that list — it is still there, reachable by id or under another of its names.

On a **concept page** the selector stays on the concept: switching takes you to the same concept's page under the name it carries in the taxonomy you picked, keeping the date lens and the open source tab. Taxonomies the concept has no live name in are shown greyed out; picking one offers to [register a name for it there](/docs/editing#names) rather than navigating away.

## The as-of date lens {#date}

**“View as of…”** next to the taxonomy selector rewinds the entire repository to a chosen date. It is not a filter on a column; it moves the whole lens — which names were registered then, and which version of each definition was current then. A calendar popover picks the date, capped at today.

:::alert[You are always told]{icon=history}
While a date is active, an amber strip sits under the top bar: "Viewing historical state as of …", with **Back to current** to clear it. The same clear is available as a small × beside the date button.
:::

Unlike the taxonomy, the date is **never persisted**. It lives only in the URL (`?date=YYYY-MM-DD`, or the short `?d=`), which means it is shareable, clearable, and gone the next time you open the app fresh. Links you follow inside the app carry it along, so the lens stays applied while you navigate.

The programmatic equivalent is the `date` parameter on an API read — see [Connecting clients](/docs/clients#curl). Use it to reconstruct exactly what an analysis saw on the day it ran.

## Stable links {#links}

Almost everything you can look at has a URL you can paste into a ticket or a paper. The ones worth knowing:

| URL | Opens |
| --- | --- |
| `/concepts/tax/<tax>/<name>` | The concept under one of its names. |
| `…?cid=42` | Pins which member of a group you mean — the unambiguous form. |
| `…?source=<key>&v=3` | One source's definition at exactly version 3. |
| `…?source=<key>&draft=17` | An open draft, overlaid on the published definition. |
| `/concepts/id/42` | The concept by its permanent id; redirects to whatever it is currently called. The safest link of all — it survives every rename. |
| `/files/<source>/<uuid>` | A data file's history and the concepts that read it. |
| `/review?status=pending` | The review queue, filtered. |

On a concept's history, the copy button beside a version copies an API reference pinned to that version, ready to paste into code. That, not a screenshot of the JSON, is how you cite a definition.
