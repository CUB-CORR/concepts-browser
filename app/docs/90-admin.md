---
title: Administration
summary: "Admin-only: user management, granting capabilities, projects, their study context and licences, and the audit log."
icon: settings
admin_only: true
---

:::alert[Admin-only chapter]{icon=shield}
Everything below requires `can_admin`, which you hold — the pages linked from here will open. This chapter is hidden from everyone else, so nothing in it is a safe place to explain something a reader without the capability needs to know.
:::

## User management {#users}

[Users](/users) — :cap[can_admin] — is the whole of access control. It lists every account with its capabilities as checkboxes and an active/inactive switch. There is no save button: every tick and every flick of the switch is written immediately, and a spinner beside the switch marks the moment it is in flight. If the server refuses the change, the control springs back and a message says why. Accounts with no capabilities are highlighted: those are people waiting on the approval-pending page.

Granting `can_read` is what turns a pending account into a user. Tick the **highest** capability the person needs: most capabilities form a chain (`can_read < can_read_detail < can_edit < can_publish`) in which the stronger entails every lesser one, so the boxes to its left tick themselves and lock — greyed, not editable, because unticking one of them would take nothing away. Untick the strongest and they are released, editable again. `create_api_key` and `add_project` sit outside the chain and must be granted explicitly — nobody gets to mint API keys by being able to publish. `can_admin` is the blanket flag: ticking it ticks and locks every other box on the row, since it implies them all, and unticking it hands them back. See [Capabilities](/docs/capabilities).

Deactivating an account disables its capabilities as a block rather than revoking them one by one — and it takes effect for that user's API keys too, since a key's effective capabilities are recomputed from its owner on every request.

Two guardrails: an administrator cannot remove their own `can_admin`, and cannot deactivate themselves. There is no way to lock the last door from the inside.

**Adding a user before their first login.** Where the deployment is backed by a directory, **Add user** searches it by username or name and provisions someone with a chosen set of capabilities, so they can work the moment they first sign in rather than landing on the pending page.

Clicking a name opens their profile: account state, capabilities, and — for a directory account — the full set of directory attributes the repository holds on them.

## What a user has actually read {#usage}

Every profile page carries an **API usage** panel: when the person was last active, how many distinct concepts they have read, the total number of reads, and a table of the concepts themselves with a per-concept read count and the first and last time each was read. Concept names link straight through.

Anyone may see their own; seeing someone else's is :cap[can_admin]. It answers the questions the audit log answers only laboriously — who is actually using this, and what have they pulled — without paging through [the log](/audit) itself.

Two things to know before drawing conclusions from it:

- It is a rollup *of the audit log*, counting successful API reads that resolved to a single concept. Browsing this app is not counted — those reads are made by the app on the person's behalf, and are attributed to it, not to them — and a read of a name that resolves to a group of concepts is not attributed to any one of them.
- **Last active** is broader than the table: it is their last API call of any kind, not their last concept read. So a person can be recently active with no new rows. It ignores app traffic on the same grounds the counts do, so somebody who is in this app every day but has never called the API themselves reads as never active.

## The audit log {#audit}

[Audit](/audit) — :cap[can_admin] — records three kinds of event, one per tab:

- **Logins** — every attempt, successful or not, with the source address. A failed attempt records the username that was tried.
- **API calls** — every request an authenticated client made, with its project, the concept it read and the version actually *served*. External clients are shown by default; the app's own traffic can be included.
- **Emails** — every message the system sent, or tried to send, or deliberately did not, with the reason in plain words.

Filters — date range, user, project, concept, client type, free text — all live in the URL, so a filtered view is a link you can send to someone. **Details** on a row opens the full record: for a concept read, both what the client *asked* for (a version, a date, a draft, or nothing) and what was served. That pairing is the point of the log — it is what lets you reconstruct, months later, exactly what a study saw.

## Projects and the licence {#projects}

[Projects](/projects) is not admin-only — every signed-in user can see the register — but it is where external access is governed, so it belongs here too.

Creating a project needs :cap[add_project]. A project has a name (the exact string external clients pass as `?project=`), a description, an optional ethics-approval reference, and one or more **leads**. Editing a project is governed by lead membership, not by a capability: its leads, and administrators, may edit it.

**The licence gate.** A project must accept the current licence version before it can be created, and re-accept it whenever a new version is issued. Until it does, its API reads are refused — which is why a client that worked last week can start returning 403 without anything about the key having changed. The project page shows the licence state and gives a lead the button to accept it.

Deleting a project is a soft delete: it disappears from the register and external clients naming it are rejected, but nothing in the audit log is lost.

Each project page also charts its API activity over the last day, week and month — built from the audit log, which is what makes the `?project=` parameter worth insisting on. It also carries the project's [study context](#study-context), below.

## Study context {#study-context}

Below the project's details sits a **Study context** card: the research frame of the study the project *is*, as opposed to the definitions it reads.

- **PICO** — *Population* (who the study is about), *Intervention* (what is done or measured), *Comparison* (what it is contrasted with) and *Outcome* (what is observed). Free text, each element optional.
- **Study team** *(Projektteilnehmer)* — who is behind the study.

The pencil opens all five fields at once. No capability is involved: study context follows the same rule as the rest of the project, so a **lead** or an administrator may edit it and nobody else — and, like every other project edit, not on a deleted project. Clearing a field and saving empties it.

The card is **hidden entirely while it is empty**, unless you can edit it — in which case you get an empty card inviting you to fill it in. So a reader never meets a row of blank labels. Nothing outside the app ever writes these fields: no import fills them in and no reimport overwrites them, so what a lead types stays until somebody edits it again.

## Exporting the catalogue {#export}

:cap[can_admin] adds an **Export** button to [the concept list](/concepts). It writes the current filtered selection as CSV or Excel — one row per concept, with its name in every taxonomy, its documentation and its configured sources — and optionally the latest published JSON and Python of each source as extra columns. The as-of date applies, so you can export the catalogue as it stood on any date.

## Reference-data reimports {#reimport}

Where a deployment imports its concepts from an upstream dataset, that import re-runs periodically and can also be triggered by an operator on the server. It is not a control in this app — there is no button — but its effects are visible here, so it is worth knowing what it does:

- A definition that moved upstream gets a **new version**, marked as a sync rather than as somebody's edit. An identical one is compared and skipped, and a definition that disappeared upstream is reported but never removed.
- A definition somebody **published in this app** is never overwritten. If upstream later changes that variable too, the import leaves the app's version in place and reports the conflict in its log, for a person to reconcile.
- A manual reimport **pulls the documentation export first** and only then runs the upsert — so the two always land together, and if the documentation pull fails nothing is imported at all rather than half of it.
- Documentation fields the export carries are **overwritten** for every concept it names. A concept the export does not mention keeps what it has.

## API keys, from the admin side {#keys}

Ordinary users mint read-only keys. Only an administrator can issue a key with wider scopes, and no key can ever carry `create_api_key` — a key must not be able to mint further keys. A key's effective capabilities are its scopes intersected with its owner's current capabilities, recomputed per request, so revoking a person's capability immediately narrows every key they hold. See [Connecting clients](/docs/clients#keys).

A key an ordinary user mints reads as far as they can: `can_read_detail` when they hold it, `can_read` otherwise. Promoting the user raises those keys with them — a reader promoted to read code does not have to mint a new key before corr-vars works.

Every user's keys are listed on their profile page (reached from the user management table), with when each was last used. From there you can **revoke** a key, or change its **scopes** in place, so its holder keeps the same secret. Choosing scopes pins the key: a later promotion leaves it exactly as you set it. *Reset to default* unpins it and makes it follow its owner again. Keys you mint for yourself with chosen scopes are pinned the same way. A key's scopes can never exceed its owner's capabilities.
