<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AdminChapterLink from "$lib/components/docs/AdminChapterLink.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import Cap from "$lib/components/docs/Cap.svelte";
	import * as Table from "$lib/components/ui/table";
	import * as Alert from "$lib/components/ui/alert";
	import { Badge } from "$lib/components/ui/badge";
	import { brand } from "$lib/brand";
	import InfoIcon from "@lucide/svelte/icons/info";
</script>

<DocPage slug="concepts">
	<DocSection id="list" title="The concept table">
		<p>
			<AppLink href="/concepts">All concepts</AppLink> is the app's front door. It is a table with one
			row per <em>name</em> registered in the active taxonomy — not one per concept — which is what lets
			a concept known by several names be found under any of them.
		</p>
		<p>
			It opens sorted by <strong>most used first</strong>, and where two concepts are read equally
			often, by <strong>most documentation first</strong>. That default is deliberate: the two
			questions it answers together are "what does everyone here actually work with" and "which of
			these has somebody written down properly". Used means pulled through the API by a study —
			opening a concept in this app is not a read of it. Search instead, and relevance takes over
			the order — see below.
		</p>
		<p>
			The taxonomy holds thousands of names, so the sorting, the filtering and the search all
			happen on the server — a page sorted in your browser would only sort that page.
			Everything you set is a query parameter, which means a link to a particular view is a link to
			exactly that view, and the browser's back button walks your filters backwards.
		</p>
		<p>
			The table itself has no page controls: it loads the next fifty names as you scroll toward the
			bottom, and the count above it says how many matched altogether. How far you have scrolled is
			the one piece of table state deliberately <em>not</em> in the URL — a scroll position is not
			something you share.
		</p>
		<p>
			The controls all live in a column to the left of the table, top to bottom. On a narrow screen
			there is no room for a column beside a table worth reading, so they fold into a
			<strong>Filters and columns</strong> disclosure above it, with the search box left out in the
			open.
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>Search</strong> over the name, the label, the description <em>and</em> the concept's
				clinical, implementation and caveats documentation, answering as you type. Underscores need
				not be typed — <em>blood sodium</em> finds <code>lab_blood_sodium</code> — and from three
				characters up a small typo is forgiven too. Results come back <strong>best match first</strong>:
				a hit in the <em>name</em> always outranks one that appears only in the documentation, and
				among names an exact match beats a prefix, which beats a substring, which beats a typo.
				Sorting a column yourself overrides that — relevance then only breaks ties inside your sort.
				For a repository-wide search across every taxonomy see
				<a href="/docs/search" class="text-primary underline-offset-4 hover:underline"
					>Search and navigation</a
				>.
			</li>
			<li>
				<strong>Status</strong> — the documentation workflow label, as a multi-select with a count
				beside each value. <em>(none)</em> selects the concepts carrying no status at all. The counts
				are computed ignoring the status filter itself, so ticking one value never hides the others.
			</li>
			<li>
				<strong>Sources</strong> and <strong>Types</strong> — the same idea for the sources a concept
				is defined for and the config types those definitions use, plus a selector for whether it has
				a definition at all (<em>All concepts</em> / <em>Configured only</em> / <em>Unconfigured
				only</em>).
			</li>
			<li>
				<strong>Columns</strong> — which columns are shown. See below.
			</li>
			<li>
				<strong>Export</strong> — <Cap cap="can_admin" />. Downloads the filtered list as CSV or
				Excel, optionally with each source's latest published JSON and Python as extra columns. It
				exports everything your filters match, not just the rows you have scrolled to.
			</li>
			<li>
				<strong>New concept</strong> — <Cap cap="can_edit" />. Covered in
				<a href="/docs/editing#new" class="text-primary underline-offset-4 hover:underline"
					>Editing and publishing</a
				>.
			</li>
			<li>
				<strong>Show retired names</strong> — a switch that adds retired names back into the table
				(<code>?include_deprecated=true</code>).
			</li>
		</ul>
	</DocSection>

	<DocSection id="columns" title="Columns">
		<p>
			Click a column heading to sort by it; click it again to reverse. Whatever you sort by, the
			default order stays underneath as the tiebreaker, so equal values fall back to the
			better-documented concept rather than to an arbitrary one — and the order never shuffles a row
			from one slice of the scroll into another.
		</p>
		<p>
			Out of the box the table shows <strong>Name</strong>, <strong>Status</strong>,
			<strong>Types</strong>, <strong>Sources</strong>, <strong>Version</strong>,
			<strong>Description</strong> and <strong>Reads</strong>, in that order — what the concept is
			called, how far along it is, how it is defined, and only then what it means and how much it is
			used.
		</p>
		<p>
			<strong>Columns</strong> in the sidebar shows or hides the rest. Name is always there; the rest
			are yours to choose, and your choice rides in the URL along with everything else — so a link you
			share carries the columns you picked, and a link without them opens the default set.
		</p>
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-40">Column</Table.Head>
					<Table.Head>What it says</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Name</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The identifier, its badges and the concept's <code>#id</code>. Always shown; the link
						carries the as-of date with it.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Description</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The opening of the concept's <em>clinical</em> documentation — the first 120 characters or
						so, on one line, with the rest on hover. Shown by default. Only the excerpt is sent to your
						browser; the full prose lives on the concept page.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Label, Summary</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The name's display name, and the concept's own one-line <code>description</code> field —
						a different thing from the <em>Description</em> column above, which is documentation, so
						the two are named apart. Both off by default.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Docs</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						How much documentation the concept carries, as <Badge variant="secondary"
							class="font-mono text-xs">S</Badge
						>
						/
						<Badge variant="secondary" class="font-mono text-xs">M</Badge>
						/
						<Badge variant="secondary" class="font-mono text-xs">L</Badge>, over the combined length
						of the clinical, implementation and caveats text — under 400 characters is S, under 1500
						is M, above that L, and a dash means nothing has been written. Sorting the column sorts by
						the underlying length, not by the letter. The character count itself is deliberately not
						a column: it is a measurement, not an answer to whether a concept is documented well
						enough.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Reads, My reads</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						How often the concept has been pulled through the API, and how much of that is yours.
						Opening it here is not a read: the count measures what studies actually query, so it
						cannot be moved by clicking around. The totals say how often something is read, never
						by whom — see
						<AdminChapterLink>Administration</AdminChapterLink>.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Sources, Types, Version</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The sources the concept has a published definition for, the config types those use, and
						its current published version.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Status</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The documentation workflow label (e.g. <em>In Production</em>), the same value the
						Status filter selects on. Shown by default.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Last edited, Last edited by</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						When the concept's latest version was published, and who published it. Imported
						definitions have no author and show a dash.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top font-medium">Names</Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						How many names the concept holds across all taxonomies — a quick read on how many
						vocabularies already point at it.
					</Table.Cell>
				</Table.Row>
			</Table.Body>
		</Table.Root>
		<Alert.Root>
			<InfoIcon />
			<Alert.Title>Under the as-of date</Alert.Title>
			<Alert.Description>
				The date lens moves the versioned columns — version, sources, types and <em>Last edited</em>
				are all computed as of that moment. Reads, documentation and status are concept-level and
				carry no history, so they can only ever show today's values; the table says so above itself
				rather than letting a historical row imply the past was measured.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="badges" title="Reading the badges">
		<p>A row's badges tell you what kind of name you are looking at:</p>
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-40">Badge</Table.Head>
					<Table.Head>Meaning</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				<Table.Row>
					<Table.Cell class="align-top"><Badge variant="outline">group of N</Badge></Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						This one name points at several concepts. Each member is its own row, so their reads
						and documentation can be told apart; the name itself opens a picker for the member you
						meant.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top"><Badge variant="outline">alias</Badge></Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						Another name of a concept the table lists elsewhere — a secondary name, not a second
						concept.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top"><Badge variant="outline">retired name</Badge></Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The name was retired but still resolves — old links and old pins keep working. Shown
						only with <em>Show retired names</em> on; the whole row is dimmed.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top"><Badge variant="outline">deprecated</Badge></Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The <em>concept</em> itself was retired. See
						<a href="#deprecation" class="text-primary underline-offset-4 hover:underline"
							>Retired concepts</a
						>.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top"><Badge variant="outline">auto</Badge></Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						An auto-generated definition. Read-only: it is derived rather than authored, and is not
						versioned or editable here.
					</Table.Cell>
				</Table.Row>
				<Table.Row>
					<Table.Cell class="align-top"><Badge variant="outline">v3</Badge></Table.Cell>
					<Table.Cell class="text-muted-foreground align-top text-sm">
						The concept's current published version in the <em>Version</em> column, or a dash when
						nothing has been published yet. The <code>#id</code> after the name is the concept's
						permanent identifier.
					</Table.Cell>
				</Table.Row>
			</Table.Body>
		</Table.Root>
	</DocSection>

	<DocSection id="detail" title="The concept page">
		<p>
			Clicking a row anywhere opens <code>/concepts/tax/&lt;taxonomy&gt;/&lt;name&gt;</code>, and a
			middle- or modifier-click opens it in a new tab. The header carries the
			name, the display name, the current version, the taxonomy, and the concept id — click it to
			copy it. Underneath, <strong>Also known as</strong> lists every other name the concept holds, in
			every taxonomy, with retired ones struck through and explained rather than hidden.
		</p>
		<p>
			If the name is a group, an amber banner says so and offers a <strong>Member</strong> selector; the
			member you are looking at is pinned in the URL as
			<code>?cid=&lt;id&gt;</code>, which is what makes a link to one member of a group
			unambiguous.
		</p>
	</DocSection>

	<DocSection id="sources" title="Definitions, per source">
		<p>
			The left column is a tab per source the concept is defined for. Each tab shows that source's
			current published definition:
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>Version metadata</strong> — the version number, the config type, the change type
				(<em>initial</em>, <em>improvement</em>, <em>critical</em>), the author and timestamp, and
				the message describing what changed. A definition superseded by a critical correction says
				so in red, naming the version that fixes it.
			</li>
			<li>
				<strong>Definition</strong> — the JSON configuration, viewable either as a readable field
				view driven by the source's schema or as raw JSON; a toggle switches between them.
			</li>
			<li>
				<strong>Python</strong> — <Cap cap="can_read_detail" /> — the snippet, syntax-highlighted,
				with a copy button; and above it the data files this version pins, each with its version,
				size, a download, a link to the file's history, and a button that copies the
				<code>getfile("…")</code> accessor. See
				<a href="/docs/files" class="text-primary underline-offset-4 hover:underline">Data files</a>.
				Without that capability the section still lists what is pinned — which file, at which
				version — but shows a lock in place of the code and the downloads, and names the capability
				you would need.
			</li>
			<li>
				<strong>History</strong> — every published version of this source's definition, newest
				first, the current one badged. Clicking one loads it; a copy button beside it copies a
				ready-made API reference pinned to that exact version, which is what you paste into a study's
				code.
			</li>
		</ul>
		<Alert.Root>
			<InfoIcon />
			<Alert.Title>Version numbers are per concept</Alert.Title>
			<Alert.Description>
				A concept's version counter is shared by all its sources. So one source's history can jump
				from <code>v2</code> to <code>v5</code> — the numbers in between belong to its siblings, and
				<code>v5</code> still identifies one point in the concept's history.
			</Alert.Description>
		</Alert.Root>
		<p>
			Pinning a version puts <code>?v=</code> in the URL and shows a blue banner saying you are not
			looking at the latest, with a <strong>Back to latest</strong> link. Opening a draft does the same
			with <code>?draft=</code>.
		</p>
	</DocSection>

	<DocSection id="documentation" title="Documentation">
		<p>
			The right column carries the human-readable half: a <strong>Documentation</strong> card with a
			status badge, a caveats callout, and clinical and implementation descriptions. Where a
			deployment syncs documentation from an external source, an <em>Open in Notion</em> button links
			to the page it came from.
		</p>
		<p>
			Editing the text needs <Cap cap="can_edit" />; changing the <em>status</em> needs
			<Cap cap="can_publish" />, so the two controls can appear separately. Unlike a definition,
			documentation is not versioned — it describes the concept, not a particular release of it.
		</p>
		<Alert.Root>
			<InfoIcon />
			<Alert.Title>Synced documentation is overwritten on reimport</Alert.Title>
			<Alert.Description>
				Where a deployment syncs documentation from an upstream export, the reimport is the
				authority: the clinical and implementation descriptions, the caveats and the status are
				replaced from upstream for every concept the export names — an in-app edit to those fields
				is a stopgap, not a permanent record. Concepts the export does not mention keep what they
				have.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="deprecation" title="Retired concepts and retired names">
		<p>Two different things get retired, and the distinction matters:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>A name</strong> is retired when a concept is renamed. The old name keeps resolving to
				the same concept forever — old links and old code do not break — and the concept page
				explains what it is now called.
			</li>
			<li>
				<strong>A concept</strong> is retired when it should no longer be used at all. A red banner
				says so, nothing is deleted, no version is renumbered, its names keep resolving, and it takes
				no new versions. Where a replacement was recorded, a button takes you straight to the
				successor.
			</li>
		</ul>
		<p>
			Retiring a concept is not something you do directly: anyone with <Cap cap="can_edit" /> can
			<em>request</em> it, and a reviewer decides. See
			<a href="/docs/editing#deprecation" class="text-primary underline-offset-4 hover:underline"
				>Editing and publishing</a
			>.
		</p>
	</DocSection>

	<DocSection id="issues" title="Reporting a problem with a definition">
		<p>
			When this deployment has configured an issue tracker, every concept page carries a
			<strong>Report issue</strong> button. It opens the tracker in a new tab with the concept's
			taxonomy and name already filled into the report, so you do not have to describe which
			definition you mean.
		</p>
		{#if brand.issueUrlTemplate}
			<p>
				This deployment has one configured, so the button is present on every concept page. It needs
				no capability beyond being able to read the concept.
			</p>
		{:else}
			<p class="italic">
				This deployment has not configured a tracker, so the button is not shown. Report problems
				through whatever channel your team uses.
			</p>
		{/if}
	</DocSection>
</DocPage>
