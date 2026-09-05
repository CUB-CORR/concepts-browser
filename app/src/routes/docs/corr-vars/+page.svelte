<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import * as Alert from "$lib/components/ui/alert";
	import LockIcon from "@lucide/svelte/icons/lock";

	const corrVarsInstall = `uv init --bare && uv add git+https://github.com/cub-corr/corr-vars.git`;

	const corrVarsEnv = `# The API key. corr-vars reads exactly this variable name.
export CORR_CONCEPTS_API_KEY="cak_xxxxxxxxxxxxxxxxxxxx"

# Optional: where materialised data files are cached
# (default: $XDG_CACHE_HOME/corr_vars/concepts, else ~/.cache/corr_vars/concepts)
export CORR_VARS_CACHE_DIR="$HOME/.cache/corr_vars/concepts"`;

	const corrVarsCohort = `from corr_vars import Cohort

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
print(cohort.concept_versions)               # provenance: what each name resolved to`;

	const corrVarsDate = `# Every variable — and every requires dependency behind it — resolves to the
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
cohort.add_variable("blood_sodium::2025-06-30")`;

	const corrVarsTaxonomy = `# Address the same concept through a pointer taxonomy instead of corr_v1.
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
)`;

	const corrVarsClient = `from corr_vars.concepts.client import ConceptsApiClient
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

client.close()`;
</script>

<DocPage slug="corr-vars">
	<DocSection id="corr-vars" title="What corr-vars is">
		<p>
			<a
				href="https://github.com/CUB-CORR/corr-vars"
				target="_blank"
				rel="noopener noreferrer"
				class="text-primary underline-offset-4 hover:underline">corr-vars</a
			>
			is the Python library that <em>evaluates</em> what this repository stores. This service holds the
			JSON definition and the Python snippet; corr-vars fetches them by name, runs them against your
			data source, and hands you a cohort table. It is the intended way to consume concepts — you rarely
			need raw HTTP.
		</p>
		<Alert.Root>
			<LockIcon />
			<Alert.Title>A corr-vars key needs can_read_detail</Alert.Title>
			<Alert.Description>
				corr-vars <em>runs</em> the definitions, so it needs the Python snippets and the bytes of the
				data files they read. A key scoped only <code>can_read</code> gets JSON definitions with
				<code>py: null</code> and cannot download the files — corr-vars will not be able to resolve
				anything that has code behind it. Scope the key
				<code>can_read_detail</code> (or higher). Keys are minted on the
				<a href="/docs/clients#keys" class="text-primary underline-offset-4 hover:underline"
					>Connecting clients</a
				> page.
			</Alert.Description>
		</Alert.Root>
		<CodeBlock code={corrVarsInstall} language="shell" />
		<p>
			Drop the <code>uv init --bare</code> if you are adding corr-vars to a project that already has
			a <code>pyproject.toml</code>.
		</p>
	</DocSection>

	<DocSection id="configuration" title="Configuration">
		<p>
			corr-vars has no user config file. The endpoint it talks to is a routing table shipped inside
			the package, and the only supported overrides are keyword arguments to
			<code>Cohort(...)</code>. Two environment variables exist:
		</p>
		<CodeBlock code={corrVarsEnv} language="shell" />
		<p>
			The API key may also be passed as <code>api_key=</code>; it is deliberately excluded from a
			saved cohort, so a pickled cohort never carries your credential. Point at a different
			deployment with <code>concepts_api_url=</code>.
		</p>
	</DocSection>

	<DocSection id="cohort" title="Resolving concepts into a cohort">
		<CodeBlock code={corrVarsCohort} language="python" />
		<p>
			A variable reference is <code>[taxonomy/]name[::version]</code>, where the version is
			<code>latest</code>, <code>vN</code>, a <code>YYYY-MM-DD</code> date or
			<code>draftNNNN</code>. Passing <code>date=</code> to <code>Cohort(...)</code> pins
			<em>every</em> variable to that date instead — the programmatic twin of the
			<a href="/docs/search#date" class="text-primary underline-offset-4 hover:underline"
				>as-of date lens</a
			>
			in the app. <code>date=</code> and <code>version=</code> are mutually exclusive.
		</p>
		<CodeBlock code={corrVarsDate} language="python" />
		<p>
			An as-of date is the only way to freeze a whole dependency graph: a <code>::vN</code> pin
			binds that one variable, while its <code>requires</code> dependencies keep resolving at the
			cohort default. Pin the cohort to the day you ran an analysis and it rebuilds from the same
			definitions months later.
		</p>
		<p>
			The taxonomy in front of the name is the second half of a reference. A concept published as
			<code>corr_v1/blood_sodium</code> is reachable through every taxonomy it carries a pointer in
			— <code>LOINC/2951-2</code> and <code>SNOMED/25197003</code> land on the same concept and the
			same definition. Only the addressing changes, so pass <code>save_as=</code> if you would
			rather not have a column called <code>2951-2</code>.
		</p>
		<CodeBlock code={corrVarsTaxonomy} language="python" />
		<p>
			Unqualified names use the cohort's default taxonomy, which is <code>corr_v1</code> unless
			<code>taxonomy=</code> says otherwise. A per-variable prefix always overrides it.
		</p>
		<p>
			Credentials are checked eagerly: <code>Cohort(...)</code> verifies the key and project before it
			loads any data, so a misconfiguration fails immediately rather than halfway through an extraction.
		</p>
		<p>
			<strong>Under the hood</strong>, corr-vars sends exactly what the
			<a href="/docs/clients#curl" class="text-primary underline-offset-4 hover:underline"
				>curl examples</a
			>
			send —
			<code>Authorization: Bearer &lt;key&gt;</code> plus <code>project=&lt;slug&gt;</code> merged
			onto every request — and retries transient failures (408, 425, 429, 5xx) with exponential
			backoff. Data files a definition pins are downloaded by uuid and cached content-addressed under
			the cache directory, so the same pinned version is never fetched twice.
		</p>
	</DocSection>

	<DocSection id="client" title="Using the client directly">
		<p>If you only want the stored definition, without a database, use the client directly:</p>
		<CodeBlock code={corrVarsClient} language="python" />
	</DocSection>
</DocPage>
