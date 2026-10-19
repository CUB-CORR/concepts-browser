---
title: Capabilities
summary: The capability chain, what each one grants, why code is gated apart from definitions, and how to get one you are missing.
icon: shield
---

## How access works {#model}

Your account carries a set of **capabilities**. Most of them form a single **chain**, weakest to strongest — each one is a superset of the one before it, so holding a stronger capability entails every lesser one:

::capability-chain

An editor can read what they edit; a publisher can review what they release. So `can_publish` alone is a complete grant for a maintainer — there is no need to tick the boxes to its left, and an account holding only `can_publish` browses, reads code and edits perfectly well.

Two capabilities sit **outside** the chain, because they are orthogonal rather than stronger: `create_api_key` and `add_project`. Nobody gets to mint API keys by being able to publish; those have to be granted explicitly. And `can_admin` is the one blanket flag — it implies every capability, in the chain and out of it.

Entailment is resolved when a request is evaluated, never written into your account. Your profile shows what was actually granted, so an account granted `can_publish` lists exactly that one word while being able to do all four things.

You can see your own at any time: open the user menu in the top right — your capabilities are listed under your name — or follow *Profile* in that menu to your profile page, which shows them as labelled badges alongside your account state and, for a directory account, your directory attributes.

The app hides what you cannot do: a control you do not have the capability for is simply not rendered, and a page you cannot open redirects you back to [the concept list](/concepts). The API enforces the same rules authoritatively, so hiding a button is a courtesy, not the security boundary — a request made by hand is refused just the same.

:::alert[New accounts start with nothing]{icon=shield}
Signing in creates your account but grants no capabilities. Until an administrator grants `can_read`, you see only the approval-pending page. If you are stuck there, ask an administrator — the app cannot approve you.
:::

## The capabilities {#table}

::capability-table

## can_read and can_read_detail {#read-detail}

The chain's first step is the one people meet most often, so it is worth stating plainly. `can_read` browses what a concept *declares*: the list, search, the JSON definition, version history, documentation, the data-file libraries with every file's path, size, digest, versions and the concepts that read it.

`can_read_detail` adds what a concept *computes*: the Python snippets, and the bytes of the data files those snippets read. Everything else about a file — that it exists, what it is called, which versions it has, who read it — stays at `can_read`. Only the contents are withheld.

:::alert[What "locked" looks like]{icon=lock}
A concept whose definition has a snippet you may not see shows a lock and a note naming the missing capability — rather than an empty box, which would read as "there is no code here". File rows lose their download link and say why. Machine clients are told the same thing explicitly; see [Connecting clients](/docs/clients#locked).
:::

The split exists because a definition's JSON says what a concept *is* while its snippet is working code against a live data source. Cataloguing the first for a wide audience does not have to mean handing out the second.

## Why edit and publish are separate {#separation}

`can_edit` writes a draft; `can_publish` turns it into a version other people's analyses will resolve to. Splitting them is the whole point of the review step: a domain expert can propose a change to a definition without being able to silently change what every running study reads.

The same reasoning puts a file upload behind `can_publish` rather than `can_edit`: uploading a new version of a data file publishes a new version of every concept that reads it, which is publishing by another route. See [the cascade](/docs/files#cascade).

## Capabilities and API keys {#keys}

An API key carries *scopes*, drawn from the same list, and `create_api_key` is never among them — a key cannot mint further keys.

What a key may actually do is worked out per request, by expanding the chain on **both** sides and intersecting: the key's scopes entail their lesser capabilities, the owner's capabilities entail theirs, and the key gets whatever both cover. Two consequences follow, and both are intended:

- A key can never exceed its owner. Narrow the person and every key they hold narrows with them, immediately.
- A key scoped `can_publish` reads code, because the chain says so — while a key scoped `can_read` does not, no matter how privileged its owner is. The scope is a real ceiling, not a hint.

In practice an ordinary key is read-only — reading code too when its owner may — and is raised automatically when its owner is promoted. Only an administrator can issue one with more, or change an existing key's scopes. See [Connecting clients](/docs/clients#keys).

## Getting a capability you are missing {#getting}

Only an administrator can grant one, on the [user management page](/users). If you cannot open a page this guide describes, that is the reason — nothing in the app grants you access to itself. See [Administration](/docs/admin) for what that looks like from the other side.
