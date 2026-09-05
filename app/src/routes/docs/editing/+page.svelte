<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import Cap from "$lib/components/docs/Cap.svelte";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import * as Alert from "$lib/components/ui/alert";
	import InfoIcon from "@lucide/svelte/icons/info";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import { pyTemplate } from "$lib/editor/template";

	// The literal starter the editor seeds a new config with — imported rather than retyped, so
	// this page cannot drift from the editor.
	const template = pyTemplate("serum_creatinine");

	// The draft overlay, from the consuming side. Mirrors `Cohort.add_variable` in corr-vars
	// (src/corr_vars/core/cohort.py) — the `::draftNNNN` suffix and the `use_cache` flag.
	const draftOverlay = `from corr_vars import Cohort

cohort = Cohort(
    obs_level="icu_stay",
    sources={"cub_hdp": {"database": "db_my_study_prepared"}},
    project="my-project",
    load_default_vars=False,
)

# The id is the one in ?draft=<id> on the concept page.
cohort.add_variable("serum_creatinine::draft1042")

print(cohort.obsm["serum_creatinine"])

# After each save in the editor, re-extract instead of reusing the cached copy.
cohort.add_variable("serum_creatinine::draft1042", use_cache=False)`;
</script>

<DocPage slug="editing">
	<DocSection id="flow" title="The shape of the workflow">
		<p>Nothing goes live in one step. A change moves through four stages:</p>
		<ol class="ml-4 flex list-decimal flex-col gap-1.5">
			<li>
				<strong>The concept exists</strong> — a name registered in a taxonomy, pointing at a concept.
				<Cap cap="can_edit" />
			</li>
			<li>
				<strong>A draft is written</strong> for one source: a JSON definition, optionally a Python snippet.
				Invisible to readers. <Cap cap="can_edit" />
			</li>
			<li>
				<strong>It is reviewed</strong> — the draft appears in
				<AppLink href="/review">the review queue</AppLink>. <Cap cap="can_publish" />
			</li>
			<li>
				<strong>It is published</strong> — assigned the next version number and made the active definition.
				<Cap cap="can_publish" />
			</li>
		</ol>
		<p>
			Once published, a version is immutable. Correcting it means publishing another one; the history
			keeps both.
		</p>
	</DocSection>

	<DocSection id="new" title="Creating a concept">
		<p>
			<AppLink href="/concepts/new">Add a concept</AppLink> — <Cap cap="can_edit" /> — offers two paths,
			and choosing the right one matters:
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>New concept</strong> — a name, an optional display name, a description and a
				taxonomy. Names are lowercase_snake_case, used in code and URLs.
			</li>
			<li>
				<strong>Alias</strong> — when what you want to add is another <em>name</em> for something
				already defined. Find the concept by whatever it is already called, then register the new
				identifier against it. A name that means something already defined belongs on that concept,
				not on a second one. Both names then resolve to the same concept, and retiring either one
				leaves the other working.
			</li>
		</ul>
		<Alert.Root>
			<InfoIcon />
			<Alert.Title>Groups are never accidental</Alert.Title>
			<Alert.Description>
				If the identifier you chose already names another concept, the app refuses and shows you
				which — because a shared name creates a <em>group</em>, where one name resolves to several
				concepts. That is allowed and sometimes correct, but you have to confirm it explicitly with
				<strong>Create the group anyway</strong>; your typed values are kept.
			</Alert.Description>
		</Alert.Root>
		<p>
			A concept must exist before any definition can be added to it, so this is always the first
			step. Creating one lands you on its (empty) concept page.
		</p>
	</DocSection>

	<DocSection id="drafts" title="Drafts">
		<p>On a concept page, with <Cap cap="can_edit" />, there are two ways to start a draft:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>New draft from v&lt;n&gt;</strong>, below an existing source's definition — copies the
				current published JSON, snippet and type as a starting point. This is the normal path for improving
				a definition.
			</li>
			<li>
				<strong>The “+ add source” tab</strong> — for a source this concept has no definition for
				yet. Pick the source and the config type; the editor opens seeded from that type's schema.
				This is also the only way to change a definition's type, since a copied draft keeps the type
				it copied.
			</li>
		</ul>
		<p>
			A draft belongs to one <code>(concept, source)</code> pair. It is listed at the top of that
			source's history in amber, is reachable at <code>?draft=&lt;id&gt;</code>, and can be discarded
			at any time — discarding never touches published versions. Auto-generated definitions refuse
			drafts entirely: they are derived, not authored.
		</p>
	</DocSection>

	<DocSection id="editor" title="The editor">
		<p>The draft editor has two halves.</p>
		<p>
			<strong>The definition</strong> is edited as a schema-driven form for schema-governed sources —
			each field labelled and validated as you type, with a running count of validation issues and a
			"schema valid" indicator when it is clean. Sources that are not schema-governed get a raw JSON
			textarea instead. The API re-validates on save and, if it refuses, lists the offending paths.
		</p>
		<p>
			<strong>The snippet</strong> is a full code editor with Python completion. A new config is
			seeded with this shape:
		</p>
		<CodeBlock code={template} language="python" />
		<p>
			The signature line and the closing <code>return</code> are locked — only the body is editable —
			so a definition always has the shape the extractor expects. Completion knows the names,
			signatures and docstrings the source publishes, plus <code>var</code>, <code>cohort</code> and the
			usual data libraries. It deliberately does not guess at the type of a chained expression rather
			than complete something wrong.
		</p>
		<p>
			<strong>Insert file</strong> opens a picker over the current source's file library and writes
			<code>getfile("&lt;uuid&gt;")</code> at the cursor, so you never type a uuid. Uuids that name no
			file in the library are underlined as errors as you type. See
			<a href="/docs/files#getfile" class="text-primary underline-offset-4 hover:underline"
				>Data files</a
			>.
		</p>
		<p>
			Every draft carries a <strong>message</strong> — what changed and why — and a
			<strong>change type</strong>: <em>improvement</em> for an ordinary revision,
			<em>critical</em> when the previous version was wrong in a way that matters. A critical
			publication is surfaced on the versions it supersedes, so somebody reading an old version is
			told it was corrected.
		</p>
	</DocSection>

	<DocSection id="warnings" title="Two warnings the editor raises">
		<p>
			<strong>Unresolved file references.</strong> A <code>getfile("…")</code> naming no file in this source's
			library. Fine while drafting, fatal at publish: the publish is refused and the offending uuids named,
			because a definition that cannot find its data is not a definition.
		</p>
		<p>
			<strong>A pinned file has a newer version.</strong> Drafts are deliberately never cascaded into
			— unlike published definitions, which are re-published when a file they read changes. So the
			editor tells you instead: "pinned v2, now v3". Publishing the draft pins the current version.
			See
			<a href="/docs/files#cascade" class="text-primary underline-offset-4 hover:underline"
				>the cascade</a
			>.
		</p>
	</DocSection>

	<DocSection id="testing" title="Testing a draft before it is published">
		<p>
			A draft is servable, so you can run one against real data before asking anybody to review
			it. Pin a variable to it with a <code>::draft&lt;id&gt;</code> suffix — the id is the number
			in <code>?draft=&lt;id&gt;</code> on the concept page, the one the amber banner reads back as
			<em>draft #1042</em>, and the one <em>Open draft</em> in the queue navigates to.
		</p>
		<CodeBlock code={draftOverlay} language="python" />
		<p>
			The draft is an <strong>overlay</strong>, not a whole cohort: it replaces the published
			config of its own <code>(concept, source)</code> pair and leaves every other source on its
			published definition, so what you are testing is exactly the one change. The pin applies to
			that variable alone — a draft belongs to one concept, so pinning a whole cohort to a draft id
			is not a useful thing to do, and a name that resolves to a group of concepts refuses a draft
			pin outright.
		</p>
		<p>
			corr-vars caches an extract, so pass <code>use_cache=False</code> after each save or you will
			keep reading the previous attempt. Reading a draft needs no special capability beyond the
			<Cap cap="can_read_detail" /> any corr-vars key needs — the snippet is code, and code is what
			that capability unlocks. See
			<a href="/docs/corr-vars" class="text-primary underline-offset-4 hover:underline">CORR Vars</a
			>.
		</p>
	</DocSection>

	<DocSection id="review" title="The review queue">
		<p>
			<AppLink href="/review">Review</AppLink> collects everything waiting for a decision in one
			place — otherwise it sits on individual concept pages, which is how work goes unnoticed. Two
			sections:
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>Drafts awaiting review</strong> — every open draft across every concept, with its
				source, change type, message, author and age. <em>Open draft</em> takes you straight into the
				editor with the draft loaded on the right concept and source.
			</li>
			<li>
				<strong>Deprecation requests</strong> — names, or the concepts behind them, somebody asked to
				retire, each badged with which of the two approving it would cost; filterable by
				<em>Pending</em>, <em>Approved</em>, <em>Rejected</em> or <em>All</em> (the filter is in the URL).
			</li>
		</ul>
		<p>
			The <strong>Review</strong> count in the top bar is these two lists added together — open
			drafts plus deprecation requests still pending. A request that has been approved or
			rejected has been decided, so it stops counting.
		</p>
		<p>
			<strong>Watching and answering are one capability.</strong> <Cap cap="can_publish" /> opens the
			queue and puts the decision buttons on it — whoever reviews is whoever publishes. There is no
			separate look-but-don't-touch grant, because a reviewer who cannot act on what they see is a
			bottleneck rather than a safeguard.
		</p>
	</DocSection>

	<DocSection id="publish" title="Publishing">
		<p>
			<strong>Publish</strong> — <Cap cap="can_publish" /> — is in the draft editor, behind a confirmation
			that spells out what it does: assign the next version number and make this the active definition
			for that source. Publish uses the last <em>saved</em> draft, so save before publishing.
		</p>
		<p>
			The confirmation also carries <strong>Notify users and project leads by email</strong>, which
			emails everyone who has used this concept and the leads of projects it was used in. It is ticked for you when
			the change type is <em>critical</em> and left clear for an <em>improvement</em> — a default, not
			a rule: tick or untick it before confirming.
		</p>
		<p>On publish, the repository:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>assigns the next version number in the concept's sequence, across all its sources;</li>
			<li>
				records who approved it and when, alongside who wrote it — the two are separate for a
				reason;
			</li>
			<li>
				pins the current version of every data file the snippet reads, freezing this definition
				against exactly those bytes;
			</li>
			<li>
				forces the change type of a source's very first published definition to <em>initial</em>.
			</li>
		</ul>
		<Alert.Root variant="destructive">
			<TriangleAlertIcon />
			<Alert.Title>Publishing is immediately visible</Alert.Title>
			<Alert.Description>
				Every client asking for "latest" gets the new version from that moment. Clients that pinned a
				version are unaffected — which is why pinning is the recommended practice for a running
				study.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="renaming" title="Renaming a concept">
		<p>
			<strong>Rename in &lt;taxonomy&gt;</strong> — <Cap cap="can_edit" /> — on the concept page. It is
			not an edit of the old name: the new name is registered first, then the old one is retired. The
			old name keeps resolving to the same concept, so links and pinned versions stay valid, and the concept
			page explains the old name rather than 404ing on it.
		</p>
		<p>
			If the new name already names another concept, you are told, and continuing creates a group —
			an explicit choice, never a silent one.
		</p>
	</DocSection>

	<DocSection id="names" title="Naming a concept in another taxonomy">
		<p>
			A concept is one identity with a name per naming system, and it need not have one
			everywhere. On its page, the taxonomy selector greys out the taxonomies it has no live name
			in — picking one opens <strong>Name &lt;concept&gt; in &lt;taxonomy&gt;</strong> —
			<Cap cap="can_edit" /> — which asks for the identifier that taxonomy uses (and an optional display
			name), registers it, and takes you to the concept's new page there.
		</p>
		<p>
			It is one write and it adds only: no other name is touched, no version is created, and the
			concept keeps its id. If the identifier already names another concept you are told, and
			continuing creates a group — the same explicit choice a rename asks for. A name typed in here
			belongs to you, not to the reference import: a later import will not retire it.
		</p>
		<p>
			Without <Cap cap="can_edit" /> the greyed-out entries still explain themselves — they just do not
			offer the form.
		</p>
	</DocSection>

	<DocSection id="deprecation" title="Retiring a name, or a concept">
		<p>
			An editor <em>requests</em>; a reviewer <em>decides</em>. <strong>Request deprecation</strong> —
			<Cap cap="can_edit" /> — asks for a reason and, optionally, the concept clients should follow instead.
			That is all it does: it files a request.
		</p>
		<p>
			The request is about the name you filed it from, and how much that costs depends on how many
			names the concept has. Retiring an alias from a concept that answers to other names retires
			<em>only that name</em>: it stops listing, the concept stays live under the rest, keeps taking
			new versions, and its successor is left alone. Retiring a concept's <em>last</em> name is
			retiring the concept. The review queue says which of the two an approval will do before you
			decide.
		</p>
		<p>
			The request lands in <AppLink href="/review">the review queue</AppLink>, where
			<Cap cap="can_publish" /> approves or rejects it. Approving a concept-level request marks the
			concept retired and records the successor; the reviewer can override the suggested successor.
			Nothing is deleted, no version is renumbered, and retired names keep resolving — the concept
			simply takes no new versions, and readers are pointed at the replacement.
		</p>
	</DocSection>
</DocPage>
