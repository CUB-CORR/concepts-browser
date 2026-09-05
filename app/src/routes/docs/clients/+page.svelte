<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import Cap from "$lib/components/docs/Cap.svelte";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import * as Alert from "$lib/components/ui/alert";
	import * as Table from "$lib/components/ui/table";
	import { brand } from "$lib/brand";
	import KeyRoundIcon from "@lucide/svelte/icons/key-round";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LockIcon from "@lucide/svelte/icons/lock";

	// Every example below is written against the endpoints the app itself calls
	// (see app/src/lib/server/api.ts and api/routers/*). Keep them in step.
	const curlRead = `# A read needs two things: a key in the Authorization header, and ?project=
API=https://your-deployment.example.org/api
KEY=cak_xxxxxxxxxxxxxxxxxxxx

curl -s "$API/concept/corr_v1/any_dialysis?project=my-project" \\
  -H "authorization: Bearer $KEY"`;

	const curlSelectors = `# The same concept, pinned three different ways
curl -s "$API/concept/corr_v1/any_dialysis?project=my-project&v=3"      -H "authorization: Bearer $KEY"
curl -s "$API/concept/corr_v1/any_dialysis?project=my-project&date=2026-05-01T05:00Z" -H "authorization: Bearer $KEY"
curl -s "$API/concept/corr_v1/any_dialysis?project=my-project&draft=42" -H "authorization: Bearer $KEY"

# History of one concept, and a data file a config pins
curl -s "$API/concept/id/17/history?project=my-project"                 -H "authorization: Bearer $KEY"
curl -s "$API/concept/id/17/files/<uuid>?project=my-project" -o mapping.csv -H "authorization: Bearer $KEY"`;

	// Shows the locked shape a client without can_read_detail gets back — a 200, not a refusal.
	const curlLocked = `# -D- prints the response headers, which is where the lock is announced
curl -s -D- "$API/concept/corr_v1/any_dialysis?project=my-project" \\
  -H "authorization: Bearer $KEY"

# HTTP/1.1 200 OK
# X-Concepts-Locked: can_read_detail
#
# [{"id": 17, "version": 4, "sources": {"cub_hdp": {
#     "json": { ... },              <- always present
#     "py": null, "py_locked": true, <- a snippet exists, and was withheld
#     "files": [ ... ]              <- manifest present; the bytes are not downloadable
# }}}]`;

</script>

<DocPage slug="clients">
	<Alert.Root>
		<KeyRoundIcon />
		<Alert.Title>Two things are always required</Alert.Title>
		<Alert.Description>
			An <strong>API key</strong> (sent as a bearer token) and a
			<strong>project slug</strong> (sent as <code>?project=</code> on every read). A request
			missing either is refused.
		</Alert.Description>
	</Alert.Root>

	<DocSection id="keys" title="Getting an API key">
		<p>
			Keys are minted and managed by you, on your own
			<AppLink href="/api-keys">API keys page</AppLink> — it is also in the user menu in the top
			right, under your name. The page is gated: <Cap cap="create_api_key" />. If you do not see the
			entry, ask an administrator to grant it (see
			<a href="/docs/capabilities" class="text-primary underline-offset-4 hover:underline"
				>Capabilities</a
			>).
		</p>
		<p>
			To create one, press <strong>New key</strong>, give it a name, and pick an expiry — 30 days, 90
			days, a year, or never. Keys begin with the prefix <code>cak_</code>, which is how the API tells
			a key from a session token.
		</p>
		<Alert.Root variant="destructive">
			<TriangleAlertIcon />
			<Alert.Title>The secret is shown once</Alert.Title>
			<Alert.Description>
				The plaintext key comes back in the create response and is never retrievable again. Copy it
				straight into your secret store. Afterwards the page only lists the key's name, prefix,
				scopes, creation and expiry dates, and when it was last used.
			</Alert.Description>
		</Alert.Root>
		<p>
			<strong>Scopes.</strong> An ordinary key is read-only. Only an administrator can mint a key with
			wider scopes, and <code>create_api_key</code> is never itself a scope — a key can never mint further
			keys. Revoking a key takes effect immediately: the next request using it is rejected.
		</p>
		<p>
			What a key may actually do is recomputed on every request, from both sides of the
			<a href="/docs/capabilities#model" class="text-primary underline-offset-4 hover:underline"
				>capability chain</a
			>: the key's scopes are expanded to include the capabilities they entail, the owner's
			capabilities likewise, and the key gets the intersection. So a key can never exceed its owner
			— narrowing the person narrows every key they hold, at once — and the scope is a real ceiling
			even for an administrator's key.
		</p>
		<Alert.Root>
			<LockIcon />
			<Alert.Title>Scope your key for what it has to read</Alert.Title>
			<Alert.Description>
				A key scoped <code>can_read</code> can browse concepts and their JSON but
				<strong>cannot</strong> read Python snippets or download data files, whoever owns it. Since
				the chain runs <code>can_read &lt; can_read_detail &lt; can_edit &lt; can_publish</code>, a
				key needs at least <code>can_read_detail</code> to see code — which is what a corr-vars key
				normally needs. See <a href="#locked" class="underline underline-offset-4">Locked content</a
				>.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="locked" title="Locked content">
		<p>
			Reading a concept's <em>declared</em> definition and reading the <em>code</em> behind it are
			two different permissions — see
			<a
				href="/docs/capabilities#read-detail"
				class="text-primary underline-offset-4 hover:underline">can_read and can_read_detail</a
			>. A client without <code>can_read_detail</code> is not refused; it is answered with less, and
			told so explicitly. That distinction matters for machine consumers, because a withheld snippet
			must never be mistaken for a definition that has no code.
		</p>
		<p>Concretely, on a concept read:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				The response is a normal <strong>200</strong> with the full JSON definition, names, history
				and the complete file manifest — uuids, paths, versions, sizes, digests. Only the code is
				missing.
			</li>
			<li>
				Each affected source block has <code>"py": null</code> and
				<code>"py_locked": true</code>. The flag is set <em>only</em> when a snippet exists and was
				withheld — a definition that genuinely has no Python stays
				<code>"py": null, "py_locked": false</code>. That is the pair to test, not
				<code>py === null</code> alone.
			</li>
			<li>
				The response carries the header
				<code>X-Concepts-Locked: can_read_detail</code>, naming the capability that would unlock it.
				It appears only when something was actually withheld, so its presence is a reliable signal
				for a client that would rather fail loudly than silently compute on a missing definition.
			</li>
		</ul>
		<CodeBlock code={curlLocked} language="shell" />
		<p>
			File <strong>downloads</strong> behave differently, because there is no partial answer to give:
			they refuse with <strong>403</strong> and the body
			<code>&#123;"detail": "Missing capability: can_read_detail"&#125;</code>. File
			<em>metadata</em> — listings, version histories, which concepts reference a file — stays at
			<code>can_read</code>.
		</p>
		<p>
			The concept list, search, history and export are unaffected: they never carried snippets or
			file bytes in the first place.
		</p>
	</DocSection>

	<DocSection id="project" title="The project slug">
		<p>
			Every concept read through the API names the project it is for. It is a query parameter,
			<code>?project=&lt;slug&gt;</code> — not a path segment and not a header — and the value is the
			project's registered <strong>name</strong> (the short, space-free identifier), not its internal
			id. The name is recorded against the request in the audit log, which is the point: the
			repository can answer "which study used this definition, at which version, when".
		</p>
		<p>
			Projects are registered in the app under
			<AppLink href="/projects">Projects</AppLink>, where you can also see a project's leads, its
			licence approval state and its recent API activity — the per-project activity chart is fed by
			exactly these <code>project=</code> values. For an external client the name is checked against
			that register on every read, so it must exist, must not have been deleted, and must have
			accepted the current licence version. A project lead re-accepts the licence on the project's
			own page.
		</p>
		<p>
			<code>project</code> is required on the concept reads — <code>/concepts</code>,
			<code>/concepts/search</code>, <code>/concept/…</code>, their history, and file downloads. It
			is not required on reference lookups such as <code>/sources</code> or
			<code>/taxonomies</code>.
		</p>
	</DocSection>

	<DocSection id="curl" title="Talking to the API directly">
		<p>
			Authentication is a bearer token in the <code>authorization</code> header — the same header the
			web app uses with its session token, so an API key is a drop-in substitute for a script.
		</p>
		<CodeBlock code={curlRead} language="shell" />
		<p>
			A name may point at more than one concept, so <code>/concept/&#123;taxonomy&#125;/&#123;name&#125;</code>
			always answers with a <em>list</em>. Pick the member you meant by its <code>id</code>.
		</p>
		<p>
			Which version you get is chosen by a selector. Pass <strong>at most one</strong> of
			<code>v</code>, <code>date</code> and <code>draft</code> — passing two is a 400. With none, you
			get the latest published version:
		</p>
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-40">Parameter</Table.Head>
					<Table.Head>Meaning</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">(none)</Table.Cell>
					<Table.Cell>The latest published version.</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">v=3</Table.Cell>
					<Table.Cell>Exactly version 3 — the reproducible pin.</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">date=…</Table.Cell>
					<Table.Cell>Whatever was current at that timestamp.</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">draft=42</Table.Cell>
					<Table.Cell>An unpublished draft, for testing before it is published.</Table.Cell>
				</Table.Row>
			</Table.Body>
		</Table.Root>
		<CodeBlock code={curlSelectors} language="shell" />
		{#if brand.apiDocsUrl}
			<p>
				This is the shape of it, not the whole surface. For every endpoint, parameter and response
				schema, use the
				<a
					href={brand.apiDocsUrl}
					target="_blank"
					rel="noopener noreferrer"
					class="text-primary underline-offset-4 hover:underline">generated API reference</a
				>, which is produced from the running API and is therefore always current.
			</p>
		{/if}
	</DocSection>

	<DocSection id="corr-vars" title="Configuring corr-vars">
		<p>
			The Python library that evaluates these definitions has a chapter of its own:
			<a href="/docs/corr-vars" class="text-primary underline-offset-4 hover:underline">CORR Vars</a>.
		</p>
	</DocSection>

	<DocSection id="troubleshooting" title="When a request is refused">
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-24">Status</Table.Head>
					<Table.Head>What to check</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">401</Table.Cell>
					<Table.Cell>
						Missing, malformed, expired or revoked key. Check the header is
						<code>authorization: Bearer &lt;key&gt;</code> and that the key is still listed as
						active on your <AppLink href="/api-keys">API keys page</AppLink>.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">403</Table.Cell>
					<Table.Cell>
						The key is valid but its scopes do not cover the request — or the project has not
						accepted the current licence version, which
						<AppLink href="/projects">Projects</AppLink> shows per project. A body of
						<code>&#123;"detail": "Missing capability: can_read_detail"&#125;</code> on a file
						download means the key is scoped too narrowly; see
						<a href="#locked" class="text-primary underline-offset-4 hover:underline"
							>Locked content</a
						>.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">404</Table.Cell>
					<Table.Cell>
						No concept of that name in that taxonomy — or not at the version/date you asked for.
						Check the taxonomy: the default is <code>corr_v1</code>.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="font-mono text-xs">422</Table.Cell>
					<Table.Cell>
						A required parameter is missing — most often <code>project</code>.
					</Table.Cell>
				</Table.Row>
			</Table.Body>
		</Table.Root>
	</DocSection>
</DocPage>
