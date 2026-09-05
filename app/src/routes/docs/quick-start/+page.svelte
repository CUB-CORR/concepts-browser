<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AdminChapterLink from "$lib/components/docs/AdminChapterLink.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import Cap from "$lib/components/docs/Cap.svelte";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import * as Alert from "$lib/components/ui/alert";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";

	const quickStartEnv = `export CORR_CONCEPTS_API_KEY="cak_xxxxxxxxxxxxxxxxxxxx"`;

	const quickStartInstall = `uv init --bare && uv add git+https://github.com/cub-corr/corr-vars.git`;

	const quickStartCohort = `from corr_vars import Cohort

cohort = Cohort(
    obs_level="icu_stay",
    sources={"cub_hdp": {"database": "db_my_study_prepared"}}, # Select database
    project="my-project",        # the project name you picked in step 2
    load_default_vars=False,
)

cohort.add_variable("blood_sodium")

print(cohort.obsm["blood_sodium"])    # the resolved time series
print(cohort.concept_versions)        # what that name resolved to`;
</script>

<DocPage slug="quick-start">
	<p>
		Four steps from a fresh account to a variable in a data frame. Each one links to the chapter
		that explains it properly; nothing here is repeated there.
	</p>

	<DocSection id="key" title="1. Create an API key">
		<p>
			Mint one on your own <AppLink href="/api-keys">API keys page</AppLink>, also reachable from
			the user menu under your name. Press <strong>New key</strong>, name it, pick an expiry.
			<Cap cap="create_api_key" />
		</p>
		<p>
			Scope it <code>can_read_detail</code>. A key scoped only <code>can_read</code> gets JSON
			definitions with the Python snippets withheld and cannot download data files, so corr-vars
			will not be able to resolve anything with code behind it. See
			<a href="/docs/clients#keys" class="text-primary underline-offset-4 hover:underline"
				>Connecting clients</a
			>
			for scopes and
			<a href="/docs/capabilities#read-detail" class="text-primary underline-offset-4 hover:underline"
				>Capabilities</a
			> for what the word buys you.
		</p>
		<Alert.Root variant="destructive">
			<TriangleAlertIcon />
			<Alert.Title>Copy the secret now</Alert.Title>
			<Alert.Description>
				The plaintext key is shown once and is never retrievable again.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="project" title="2. Pick a project">
		<p>
			Every read names the project it is for, so you need one before the first request. Look for
			yours in the <AppLink href="/projects">project register</AppLink>, or create it there
			(<Cap cap="add_project" />). What you need from the page is the project's <strong>name</strong>
			— the short, space-free identifier — and a licence state that says accepted; until it does,
			reads are refused. Details in
			<a href="/docs/clients#project" class="text-primary underline-offset-4 hover:underline"
				>Connecting clients</a
			>
			and
			<AdminChapterLink href="/docs/admin#projects">Administration</AdminChapterLink>.
		</p>
	</DocSection>

	<DocSection id="environment" title="3. Put the key in your environment">
		<p>corr-vars reads exactly this variable name:</p>
		<CodeBlock code={quickStartEnv} language="shell" />
		<p>
			That is the only environment variable you need. The endpoint is not one — it ships inside the
			package as a routing table, and the only way to point elsewhere is
			<code>Cohort(concepts_api_url=...)</code>. The key can likewise be passed as
			<code>api_key=</code> instead.
		</p>
	</DocSection>

	<DocSection id="go" title="4. Fetch your first variable">
		<!-- <CodeBlock code={quickStartInstall} language="shell" /> -->
		<CodeBlock code={quickStartCohort} language="python" />
		<p>
			<code>Cohort(...)</code> checks the key and the project before it loads any data, so a
			misconfiguration fails immediately rather than halfway through an extraction.
		</p>
		<p>
			From here:
			<a href="/docs/corr-vars" class="text-primary underline-offset-4 hover:underline">CORR Vars</a
			>
			covers pinning a whole cohort to a date, addressing concepts through LOINC or SNOMED, and using
			the client without a database.
		</p>
	</DocSection>
</DocPage>
