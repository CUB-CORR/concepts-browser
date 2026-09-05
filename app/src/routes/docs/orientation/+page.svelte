<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AdminChapterLink from "$lib/components/docs/AdminChapterLink.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import Cap from "$lib/components/docs/Cap.svelte";
	import DataModelDiagram from "$lib/components/docs/DataModelDiagram.svelte";
	import * as Table from "$lib/components/ui/table";
	import * as Alert from "$lib/components/ui/alert";
	import { brand } from "$lib/brand";
	import HistoryIcon from "@lucide/svelte/icons/history";
	import ClockIcon from "@lucide/svelte/icons/clock";
</script>

<DocPage slug="orientation">
	<DocSection id="what" title="What this application is">
		<p>
			{brand.appName} stores <strong>clinical concept definitions</strong>. A concept — "any
			dialysis", "serum creatinine", "invasive ventilation" — is a clinical idea; a
			<strong>definition</strong> is the machine-readable recipe for extracting it from a particular data
			source: a schema-conformant JSON configuration, optionally a Python snippet, optionally data files
			the snippet reads.
		</p>
		<p>Three properties make it a repository rather than a folder of scripts:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>Versioning.</strong> Published versions are immutable. Superseding a definition appends
				a new version; nothing is rewritten, renumbered or deleted, so a study that pinned version 3
				resolves to the same bytes forever.
			</li>
			<li>
				<strong>Review.</strong> Writing a definition and releasing it are separate acts, held by separate
				capabilities. Work in progress lives as a draft and is invisible to readers until somebody publishes
				it.
			</li>
			<li>
				<strong>Provenance.</strong> Every read is attributed to a project, and every version carries
				its author, timestamp, change type and message. The repository can say who used which definition,
				at which version, when.
			</li>
		</ul>
		<p>
			This service <em>stores and serves</em> definitions. It does not evaluate them — that is
			<a href="/docs/corr-vars" class="text-primary underline-offset-4 hover:underline"
				>corr-vars</a
			>, which fetches a definition from here and runs it against your data.
		</p>
	</DocSection>

	<DocSection id="anatomy" title="Anatomy of a concept">
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-40">Term</Table.Head>
					<Table.Head>Meaning</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Concept</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The thing itself, identified by a stable numeric id. It has a description, documentation,
						and one definition per source.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Taxonomy</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						A naming system. The same concept can be named differently in different taxonomies —
						a house name, a coding standard, a project's own vocabulary.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Name / pointer</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						An identifier registered in a taxonomy, pointing at a concept over a time window. One
						concept may hold several names (aliases); one name may point at several concepts (a
						group).
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Source</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						A data system a definition is written against. The same concept is defined once per
						source, because the extraction differs.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Version</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						A published definition. The counter runs per concept and is shared by all its sources,
						so <code>v4</code> identifies a point in the concept's history, not one source's.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Draft</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						An unpublished definition in progress. Readers never see one unless they ask for it by
						id.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Data file</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						A mapping table or model a snippet reads, versioned in its source's library. See
						<a href="/docs/files" class="text-primary underline-offset-4 hover:underline">Data files</a
						>.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Project</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The study an API read is attributed to. Every programmatic read names one — see
						<a href="/docs/clients#project" class="text-primary underline-offset-4 hover:underline"
							>Connecting clients</a
						>.
					</Table.Cell>
				</Table.Row>
			</Table.Body>
		</Table.Root>
		<p>
			Those terms stack into three layers — names point at concepts, concepts carry the
			versioned definitions — which is easier to see drawn than described:
		</p>
		<DataModelDiagram />
	</DocSection>

	<DocSection id="topbar" title="The top bar">
		<p>Everything the app offers hangs off the bar at the top of every page:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>The logo and product name</strong> return you to
				<AppLink href="/concepts">the concept list</AppLink>, which is also where the app opens.
			</li>
			<li>
				<strong>Concepts</strong> — the word itself is a link straight to
				<AppLink href="/concepts">All concepts</AppLink>; the little chevron beside it opens a menu
				with that and <AppLink href="/files">Data files</AppLink>. So the common case is one click,
				and the menu is there when you want the other page. Files sit under Concepts rather than
				beside them because a file exists only to be read by a definition.
			</li>
			<li>
				<strong>Projects</strong> — <AppLink href="/projects">the project register</AppLink>, which
				scopes external API access and records licence acceptance. A project's own page charts
				the requests made under it and lists the concepts they read, with the versions served.
			</li>
			<li>
				<strong>Docs</strong> — this guide, the corr-vars repository, and
				{#if brand.apiDocsUrl}the generated API reference{:else}the API reference, when a
					deployment configures one{/if}.
			</li>
			<li>
				<strong>Review</strong> — <AppLink href="/review">the queue</AppLink> of everything waiting
				for a decision. Shown only if you hold <Cap cap="can_publish" />.
			</li>
			<li>
				<strong>Users</strong> and <strong>Audit</strong>, behind a separator — admin only, see
				<AdminChapterLink>Administration</AdminChapterLink>.
			</li>
		</ul>
		<p>
			<strong>Review</strong> and <strong>Users</strong> carry a count when something is waiting: the
			number of open drafts plus undecided deprecation requests on Review, and the number of people
			awaiting approval on Users. No number means nothing is waiting. The count is what the page
			itself would show you, so it follows the same capability — you are never told the size of a
			queue you cannot open.
		</p>
		<p>
			On the right: a <strong>theme toggle</strong> (light and dark are both first-class; the whole app,
			including the code editor, follows it) and your <strong>user menu</strong>. The menu lists your
			current capabilities under your name — the quickest answer to "why can I not see that button" —
			and links to your profile page (<em>Profile</em>) and, with
			<Cap cap="create_api_key" />, your <AppLink href="/api-keys">API keys</AppLink>.
		</p>
		<p>
			<strong>Your profile</strong> shows your account state, your granted capabilities as labelled
			badges, and — for a directory-backed account — the directory attributes the repository holds
			on you. Below that sits <strong>API usage</strong>: when you were last active, how many
			distinct concepts you have read, how many reads that was in total, and the concepts
			themselves, each linked, stamped with when you last read it and with the versions of it you
			have been served. It counts the
			reads you made against the API yourself — with an API key or a client of your own — and not
			the ones this app makes for you as you click through concept pages, so browsing here never
			moves any of those numbers. You can always see your own; seeing somebody else's needs
			<Cap cap="can_admin" />.
		</p>
		<p>
			At the very bottom of every page, a deployment may show the short git hash of the build that
			is running — hover it for the full one. It is the quickest way to tell which release you are
			looking at when reporting a problem.
		</p>
	</DocSection>

	<DocSection id="scoping" title="Two controls that scope everything">
		<p>
			Inside the concepts area a second bar carries the two lenses that change what every page
			shows. Both are covered in detail in
			<a href="/docs/search" class="text-primary underline-offset-4 hover:underline"
				>Search and navigation</a
			>:
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>The taxonomy selector</strong> chooses which naming system you are working in. It is
				a durable preference — it is remembered between visits.
			</li>
			<li>
				<strong>“View as of…”</strong> rewinds the whole repository to a past date: which names were
				registered then, and which versions existed. It is deliberately <em>not</em> remembered — it
				lives only in the URL, so it is shareable and never resurrects on a fresh visit.
			</li>
		</ul>
		<Alert.Root>
			<HistoryIcon />
			<Alert.Title>The amber historical banner</Alert.Title>
			<Alert.Description>
				Whenever a date is active, an amber strip under the top bar says so — "Viewing historical
				state as of …" — with a <strong>Back to current</strong> link. If a page looks out of date, that
				banner is the first thing to check.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="access" title="Signing in and getting access">
		<p>
			Sign-in is at <AppLink href="/login">the login page</AppLink>. Depending on the deployment,
			credentials are your institution's directory account or a local account; the hint under the
			heading names which.
		</p>
		<Alert.Root>
			<ClockIcon />
			<Alert.Title>"Approval pending"</Alert.Title>
			<Alert.Description>
				Signing in for the first time creates your account with <em>no</em> capabilities, and you land
				on the approval-pending page. An administrator has to grant you <code>can_read</code> before
				you can browse. You may need to sign in again afterwards.
			</Alert.Description>
		</Alert.Root>
		<p>
			Once you can read, most of the app is still capability-gated. Which button belongs to which
			capability is spelled out throughout this guide with a
			<Cap cap="can_edit" /> marker, and collected in
			<a href="/docs/capabilities" class="text-primary underline-offset-4 hover:underline"
				>Capabilities</a
			>.
		</p>
	</DocSection>
</DocPage>
