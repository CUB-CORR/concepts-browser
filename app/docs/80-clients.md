---
title: Connecting clients
summary: "Programmatic access: API keys, the required project slug, curl requests and locked content."
icon: plug
---

<!-- Every example below is written against the endpoints the app itself calls
     (see app/src/lib/server/api.ts and api/routers/*). Keep them in step. -->

:::alert[Two things are always required]{icon=key-round}
An **API key** (sent as a bearer token) and a **project slug** (sent as `?project=` on every read). A request missing either is refused.
:::

## Getting an API key {#keys}

Keys are minted and managed by you, on your own [API keys page](/api-keys) — it is also in the user menu in the top right, under your name. The page is gated: :cap[create_api_key]. If you do not see the entry, ask an administrator to grant it (see [Capabilities](/docs/capabilities)).

To create one, press **New key**, give it a name, and pick an expiry — 30 days, 90 days, a year, or never. Keys begin with the prefix `cak_`, which is how the API tells a key from a session token.

:::alert[The secret is shown once]{variant=destructive}
The plaintext key comes back in the create response and is never retrievable again. Copy it straight into your secret store. Afterwards the page only lists the key's name, prefix, scopes, creation and expiry dates, and when it was last used.
:::

**Scopes.** An ordinary key is read-only, reading as far as you may: `can_read_detail` if you hold it, `can_read` otherwise. If an administrator later promotes you, your existing keys are raised along with you — no need to mint new ones. Only an administrator can mint a key with wider scopes or change an existing key's scopes, and `create_api_key` is never itself a scope — a key can never mint further keys. Revoking a key takes effect immediately: the next request using it is rejected. Administrators can see and revoke your keys too.

What a key may actually do is recomputed on every request, from both sides of the [capability chain](/docs/capabilities#model): the key's scopes are expanded to include the capabilities they entail, the owner's capabilities likewise, and the key gets the intersection. So a key can never exceed its owner — narrowing the person narrows every key they hold, at once — and the scope is a real ceiling even for an administrator's key.

:::alert[Scope your key for what it has to read]{icon=lock}
A key scoped `can_read` can browse concepts and their JSON but **cannot** read Python snippets or download data files, whoever owns it. Since the chain runs `can_read < can_read_detail < can_edit < can_publish`, a key needs at least `can_read_detail` to see code — which is what a corr-vars key normally needs. See [Locked content](#locked).
:::

## Locked content {#locked}

Reading a concept's *declared* definition and reading the *code* behind it are two different permissions — see [can_read and can_read_detail](/docs/capabilities#read-detail). A client without `can_read_detail` is not refused; it is answered with less, and told so explicitly. That distinction matters for machine consumers, because a withheld snippet must never be mistaken for a definition that has no code.

Concretely, on a concept read:

- The response is a normal **200** with the full JSON definition, names, history and the complete file manifest — uuids, paths, versions, sizes, digests. Only the code is missing.
- Each affected source block has `"py": null` and `"py_locked": true`. The flag is set *only* when a snippet exists and was withheld — a definition that genuinely has no Python stays `"py": null, "py_locked": false`. That is the pair to test, not `py === null` alone.
- The response carries the header `X-Concepts-Locked: can_read_detail`, naming the capability that would unlock it. It appears only when something was actually withheld, so its presence is a reliable signal for a client that would rather fail loudly than silently compute on a missing definition.

```shell
# -D- prints the response headers, which is where the lock is announced
curl -s -D- "$API/concept/corr_v1/any_dialysis?project=my-project" \
  -H "authorization: Bearer $KEY"

# HTTP/1.1 200 OK
# X-Concepts-Locked: can_read_detail
#
# [{"id": 17, "version": 4, "sources": {"cub_hdp": {
#     "json": { ... },              <- always present
#     "py": null, "py_locked": true, <- a snippet exists, and was withheld
#     "files": [ ... ]              <- manifest present; the bytes are not downloadable
# }}}]
```

File **downloads** behave differently, because there is no partial answer to give: they refuse with **403** and the body `{"detail": "Missing capability: can_read_detail"}`. File *metadata* — listings, version histories, which concepts reference a file — stays at `can_read`.

The concept list, search, history and export are unaffected: they never carried snippets or file bytes in the first place.

## The project slug {#project}

Every concept read through the API names the project it is for. It is a query parameter, `?project=<slug>` — not a path segment and not a header — and the value is the project's registered **name** (the short, space-free identifier), not its internal id. The name is recorded against the request in the audit log, which is the point: the repository can answer "which study used this definition, at which version, when".

Projects are registered in the app under [Projects](/projects), where you can also see a project's leads, its licence approval state and its recent API activity — the per-project activity chart is fed by exactly these `project=` values. For an external client the name is checked against that register on every read, so it must exist, must not have been deleted, and must have accepted the current licence version. A project lead re-accepts the licence on the project's own page.

`project` is required on the concept reads — `/concepts`, `/concepts/search`, `/concept/…`, their history, and file downloads. It is not required on reference lookups such as `/sources` or `/taxonomies`.

## Talking to the API directly {#curl}

Authentication is a bearer token in the `authorization` header — the same header the web app uses with its session token, so an API key is a drop-in substitute for a script.

```shell
# A read needs two things: a key in the Authorization header, and ?project=
API=https://your-deployment.example.org/api
KEY=cak_xxxxxxxxxxxxxxxxxxxx

curl -s "$API/concept/corr_v1/any_dialysis?project=my-project" \
  -H "authorization: Bearer $KEY"
```

A name may point at more than one concept, so `/concept/{taxonomy}/{name}` always answers with a *list*. Pick the member you meant by its `id`.

Which version you get is chosen by a selector. Pass **at most one** of `v`, `date` and `draft` — passing two is a 400. With none, you get the latest published version:

| Parameter | Meaning |
| --- | --- |
| `(none)` | The latest published version. |
| `v=3` | Exactly version 3 — the reproducible pin. |
| `date=…` | Whatever was current at that timestamp. |
| `draft=42` | An unpublished draft, for testing before it is published. |

```shell
# The same concept, pinned three different ways
curl -s "$API/concept/corr_v1/any_dialysis?project=my-project&v=3"      -H "authorization: Bearer $KEY"
curl -s "$API/concept/corr_v1/any_dialysis?project=my-project&date=2026-05-01T05:00Z" -H "authorization: Bearer $KEY"
curl -s "$API/concept/corr_v1/any_dialysis?project=my-project&draft=42" -H "authorization: Bearer $KEY"

# History of one concept, and a data file a config pins
curl -s "$API/concept/id/17/history?project=my-project"                 -H "authorization: Bearer $KEY"
curl -s "$API/concept/id/17/files/<uuid>?project=my-project" -o mapping.csv -H "authorization: Bearer $KEY"
```

:::if{link=api}
This is the shape of it, not the whole surface. For every endpoint, parameter and response schema, use the :external[generated API reference]{id=api}, which is produced from the running API and is therefore always current.
:::

## Configuring corr-vars {#corr-vars}

The Python library that evaluates these definitions has a chapter of its own: [CORR Vars](/docs/corr-vars).

## When a request is refused {#troubleshooting}

| Status | What to check |
| --- | --- |
| `401` | Missing, malformed, expired or revoked key. Check the header is `authorization: Bearer <key>` and that the key is still listed as active on your [API keys page](/api-keys). |
| `403` | The key is valid but its scopes do not cover the request — or the project has not accepted the current licence version, which [Projects](/projects) shows per project. A body of `{"detail": "Missing capability: can_read_detail"}` on a file download means the key is scoped too narrowly; see [Locked content](#locked). |
| `404` | No concept of that name in that taxonomy — or not at the version/date you asked for. Check the taxonomy: the default is `corr_v1`. |
| `422` | A required parameter is missing — most often `project`. |
