---
title: CORR Vars
summary: "The Python library that evaluates these definitions: installing it, configuring it, and resolving concepts into a cohort."
icon: package
---

## What corr-vars is {#corr-vars}

[corr-vars](https://github.com/CUB-CORR/corr_vars) is the Python library that *evaluates* what this repository stores. This service holds the JSON definition and the Python snippet; corr-vars fetches them by name, runs them against your data source, and hands you a cohort table. It is the intended way to consume concepts — you rarely need raw HTTP.

:::alert[A corr-vars key needs can_read_detail]{icon=lock}
corr-vars *runs* the definitions, so it needs the Python snippets and the bytes of the data files they read. A key scoped only `can_read` gets JSON definitions with `py: null` and cannot download the files — corr-vars will not be able to resolve anything that has code behind it. Scope the key `can_read_detail` (or higher). Keys are minted on the [Connecting clients](/docs/clients#keys) page.
:::

```shell
uv init --bare && uv add git+https://github.com/cub-corr/corr-vars.git
```

Drop the `uv init --bare` if you are adding corr-vars to a project that already has a `pyproject.toml`.

## Configuration {#configuration}

corr-vars has no user config file. The endpoint it talks to is a routing table shipped inside the package, and the only supported overrides are keyword arguments to `Cohort(...)`. Two environment variables exist:

```shell
# The API key. corr-vars reads exactly this variable name.
export CORR_CONCEPTS_API_KEY="cak_xxxxxxxxxxxxxxxxxxxx"

# Optional: where materialised data files are cached
# (default: $XDG_CACHE_HOME/corr_vars/concepts, else ~/.cache/corr_vars/concepts)
export CORR_VARS_CACHE_DIR="$HOME/.cache/corr_vars/concepts"
```

The API key may also be passed as `api_key=`; it is deliberately excluded from a saved cohort, so a pickled cohort never carries your credential. Point at a different deployment with `concepts_api_url=`.

## Resolving concepts into a cohort {#cohort}

```python
from corr_vars import Cohort

cohort = Cohort(
    obs_level="icu_stay",
    sources={"cub_hdp": {"database": "db_my_study_prepared"}},
    project="my-project",        # required — every API read carries it
    # api_key="cak_...",        # optional; defaults to $CORR_CONCEPTS_API_KEY
    # concepts_api_url="https://your-deployment.example.org/api",
    load_default_vars=False,
)

# Resolve a concept the corr-vars way: by name, from this repository.
cohort.add_variable("any_dialysis")          # latest published version
cohort.add_variable("blood_sodium::v3")      # pinned to version 3

print(cohort.obsm["blood_sodium"])           # the resolved time series
print(cohort.concept_versions)               # provenance: what each name resolved to
```

A variable reference is `[taxonomy/]name[::version]`, where the version is `latest`, `vN`, a `YYYY-MM-DD` date or `draftNNNN`. Passing `date=` to `Cohort(...)` pins *every* variable to that date instead — the programmatic twin of the [as-of date lens](/docs/search#date) in the app. `date=` and `version=` are mutually exclusive.

```python
# Every variable — and every requires dependency behind it — resolves to the
# definition that was current on this day.
cohort = Cohort(
    obs_level="icu_stay",
    sources={"cub_hdp": {"database": "db_my_study_prepared"}},
    project="my-project",
    date="2025-06-30",           # or datetime.date(2025, 6, 30)
    load_default_vars=False,
)

cohort.add_variable("any_dialysis")          # as of 2025-06-30
cohort.add_variable("blood_sodium::v3")      # a per-variable pin still wins

# Or pin a single variable to a date, leaving the rest of the cohort at latest.
cohort.add_variable("blood_sodium::2025-06-30")
```

An as-of date is the only way to freeze a whole dependency graph: a `::vN` pin binds that one variable, while its `requires` dependencies keep resolving at the cohort default. Pin the cohort to the day you ran an analysis and it rebuilds from the same definitions months later.

The taxonomy in front of the name is the second half of a reference. A concept published as `corr_v1/blood_sodium` is reachable through every taxonomy it carries a pointer in — `LOINC/2951-2` and `SNOMED/25197003` land on the same concept and the same definition. Only the addressing changes, so pass `save_as=` if you would rather not have a column called `2951-2`.

```python
# Address the same concept through a pointer taxonomy instead of corr_v1.
cohort.add_variable("LOINC/2951-2", save_as="blood_sodium")
cohort.add_variable("SNOMED/25197003", save_as="blood_sodium")

# Taxonomy, name and version compose in one reference.
cohort.add_variable("LOINC/2951-2::2025-06-30", save_as="blood_sodium")

# Make a taxonomy the cohort default, so bare names are read in it.
cohort = Cohort(
    obs_level="icu_stay",
    sources={"cub_hdp": {"database": "db_my_study_prepared"}},
    project="my-project",
    taxonomy="LOINC",
    load_default_vars=False,
)
```

Unqualified names use the cohort's default taxonomy, which is `corr_v1` unless `taxonomy=` says otherwise. A per-variable prefix always overrides it.

Credentials are checked eagerly: `Cohort(...)` verifies the key and project before it loads any data, so a misconfiguration fails immediately rather than halfway through an extraction.

**Under the hood**, corr-vars sends exactly what the [curl examples](/docs/clients#curl) send — `Authorization: Bearer <key>` plus `project=<slug>` merged onto every request — and retries transient failures (408, 425, 429, 5xx) with exponential backoff. Data files a definition pins are downloaded by uuid and cached content-addressed under the cache directory, so the same pinned version is never fetched twice.

## Using the client directly {#client}

If you only want the stored definition, without a database, use the client directly:

```python
from corr_vars.concepts.client import ConceptsApiClient
from corr_vars.concepts.spec import parse_version_selector

client = ConceptsApiClient(
    "https://your-deployment.example.org/api",
    project="my-project",
    api_key="cak_xxxxxxxxxxxxxxxxxxxx",   # or leave out and set CORR_CONCEPTS_API_KEY
)

# A name may point at more than one concept, so this always returns a list.
for concept in client.get_concepts("corr_v1", "any_dialysis", parse_version_selector("latest")):
    print(concept.id, concept.version, list(concept.sources))
    print(concept.sources["cub_hdp"].json)

client.close()
```
