---
title: Quick start
summary: "From a fresh account to a variable in a data frame: a key, a project, one environment variable and a corr-vars snippet."
icon: rocket
---

Four steps from a fresh account to a variable in a data frame. Each one links to the chapter that explains it properly; nothing here is repeated there.

## 1. Create an API key {#key}

Mint one on your own [API keys page](/api-keys), also reachable from the user menu under your name. Press **New key**, name it, pick an expiry. :cap[create_api_key]

Scope it `can_read_detail`. A key scoped only `can_read` gets JSON definitions with the Python snippets withheld and cannot download data files, so corr-vars will not be able to resolve anything with code behind it. See [Connecting clients](/docs/clients#keys) for scopes and [Capabilities](/docs/capabilities#read-detail) for what the word buys you.

:::alert[Copy the secret now]{variant=destructive}
The plaintext key is shown once and is never retrievable again.
:::

## 2. Pick a project {#project}

Every read names the project it is for, so you need one before the first request. Look for yours in the [project register](/projects), or create it there (:cap[add_project]). What you need from the page is the project's **name** — the short, space-free identifier — and a licence state that says accepted; until it does, reads are refused. Details in [Connecting clients](/docs/clients#project) and [Administration](/docs/admin#projects).

## 3. Put the key in your environment {#environment}

corr-vars reads exactly this variable name:

```shell
export CORR_CONCEPTS_API_KEY="cak_xxxxxxxxxxxxxxxxxxxx"
```

That is the only environment variable you need. The endpoint is not one — it ships inside the package as a routing table, and the only way to point elsewhere is `Cohort(concepts_api_url=...)`. The key can likewise be passed as `api_key=` instead.

## 4. Fetch your first variable {#go}

<!--
```shell
uv init --bare && uv add git+https://github.com/cub-corr/corr-vars.git
```
-->

```python
from corr_vars import Cohort

cohort = Cohort(
    obs_level="icu_stay",
    sources={"cub_hdp": {"database": "db_my_study_prepared"}}, # Select database
    project="my-project",        # the project name you picked in step 2
    load_default_vars=False,
)

cohort.add_variable("blood_sodium")

print(cohort.obsm["blood_sodium"])    # the resolved time series
print(cohort.concept_versions)        # what that name resolved to
```

`Cohort(...)` checks the key and the project before it loads any data, so a misconfiguration fails immediately rather than halfway through an extraction.

From here: [CORR Vars](/docs/corr-vars) covers pinning a whole cohort to a date, addressing concepts through LOINC or SNOMED, and using the client without a database.
