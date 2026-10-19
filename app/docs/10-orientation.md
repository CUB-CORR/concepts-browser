---
title: Orientation
summary: What this repository is, how a concept is put together, and what every part of the chrome around it does.
icon: compass
---

## What this application is {#what}

:app-name stores **clinical concept definitions**. A concept — "any dialysis", "serum creatinine", "invasive ventilation" — is a clinical idea; a **definition** is the machine-readable recipe for extracting it from a particular data source: a schema-conformant JSON configuration, optionally a Python snippet, optionally data files the snippet reads.

Three properties make it a repository rather than a folder of scripts:

- **Versioning.** Published versions are immutable. Superseding a definition appends a new version; nothing is rewritten, renumbered or deleted, so a study that pinned version 3 resolves to the same bytes forever.
- **Review.** Writing a definition and releasing it are separate acts, held by separate capabilities. Work in progress lives as a draft and is invisible to readers until somebody publishes it.
- **Provenance.** Every read is attributed to a project, and every version carries its author, timestamp, change type and message. The repository can say who used which definition, at which version, when.

This service *stores and serves* definitions. It does not evaluate them — that is [corr-vars](/docs/corr-vars), which fetches a definition from here and runs it against your data.

## Anatomy of a concept {#anatomy}

| Term | Meaning |
| --- | --- |
| Concept | The thing itself, identified by a stable numeric id. It has a description, documentation, and one definition per source. |
| Taxonomy | A naming system. The same concept can be named differently in different taxonomies — a house name, a coding standard, a project's own vocabulary. |
| Name / pointer | An identifier registered in a taxonomy, pointing at a concept over a time window. One concept may hold several names (aliases); one name may point at several concepts (a group). |
| Source | A data system a definition is written against. The same concept is defined once per source, because the extraction differs. |
| Version | A published definition. The counter runs per concept and is shared by all its sources, so `v4` identifies a point in the concept's history, not one source's. |
| Draft | An unpublished definition in progress. Readers never see one unless they ask for it by id. |
| Data file | A mapping table or model a snippet reads, versioned in its source's library. See [Data files](/docs/files). |
| Project | The study an API read is attributed to. Every programmatic read names one — see [Connecting clients](/docs/clients#project). |

Those terms stack into three layers — names point at concepts, concepts carry the versioned definitions — which is easier to see drawn than described:

::data-model

## The top bar {#topbar}

Everything the app offers hangs off the bar at the top of every page:

- **The logo and product name** return you to [the concept list](/concepts), which is also where the app opens.
- **Concepts** — the word itself is a link straight to [All concepts](/concepts); the little chevron beside it opens a menu with that and [Data files](/files). So the common case is one click, and the menu is there when you want the other page. Files sit under Concepts rather than beside them because a file exists only to be read by a definition.
- **Projects** — [the project register](/projects), which scopes external API access and records licence acceptance. A project's own page charts the requests made under it and lists the concepts they read, with the versions served.
- **Docs** — this guide, the corr-vars repository, and the generated API reference.
- **Review** — [the queue](/review) of everything waiting for a decision. Shown only if you hold :cap[can_publish].
- **Users** and **Audit**, behind a separator — admin only, see [Administration](/docs/admin).

**Review** and **Users** carry a count when something is waiting: the number of open drafts plus undecided deprecation requests on Review, and the number of people awaiting approval on Users. No number means nothing is waiting. The count is what the page itself would show you, so it follows the same capability — you are never told the size of a queue you cannot open.

On the right: a **theme toggle** (light and dark are both first-class; the whole app, including the code editor, follows it) and your **user menu**. The menu lists your current capabilities under your name — the quickest answer to "why can I not see that button" — and links to your profile page (*Profile*) and, with :cap[create_api_key], your [API keys](/api-keys).

**Your profile** shows your account state, your granted capabilities as labelled badges, and — for a directory-backed account — the directory attributes the repository holds on you. Below that sits **API usage**: when you were last active, how many distinct concepts you have read, how many reads that was in total, and the concepts themselves, each linked, stamped with when you last read it and with the versions of it you have been served. It counts the reads you made against the API yourself — with an API key or a client of your own — and not the ones this app makes for you as you click through concept pages, so browsing here never moves any of those numbers. You can always see your own; seeing somebody else's needs :cap[can_admin].

At the very bottom of every page, a deployment may show the short git hash of the build that is running — hover it for the full one. It is the quickest way to tell which release you are looking at when reporting a problem.

## Two controls that scope everything {#scoping}

Inside the concepts area a second bar carries the two lenses that change what every page shows. Both are covered in detail in [Search and navigation](/docs/search):

- **The taxonomy selector** chooses which naming system you are working in. It is a durable preference — it is remembered between visits.
- **“View as of…”** rewinds the whole repository to a past date: which names were registered then, and which versions existed. It is deliberately *not* remembered — it lives only in the URL, so it is shareable and never resurrects on a fresh visit.

:::alert[The amber historical banner]{icon=history}
Whenever a date is active, an amber strip under the top bar says so — "Viewing historical state as of …" — with a **Back to current** link. If a page looks out of date, that banner is the first thing to check.
:::

## Signing in and getting access {#access}

Sign-in is at [the login page](/login). Depending on the deployment, credentials are your institution's directory account or a local account; the hint under the heading names which.

:::alert["Approval pending"]{icon=clock}
Signing in for the first time creates your account with *no* capabilities, and you land on the approval-pending page. An administrator has to grant you `can_read` before you can browse. You may need to sign in again afterwards.
:::

Once you can read, most of the app is still capability-gated. Which button belongs to which capability is spelled out throughout this guide with a :cap[can_edit] marker, and collected in [Capabilities](/docs/capabilities).
