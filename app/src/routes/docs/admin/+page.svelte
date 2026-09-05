<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import Cap from "$lib/components/docs/Cap.svelte";
	import * as Alert from "$lib/components/ui/alert";
	import ShieldIcon from "@lucide/svelte/icons/shield";
</script>

<DocPage slug="admin">
	<Alert.Root>
		<ShieldIcon />
		<Alert.Title>Admin-only chapter</Alert.Title>
		<Alert.Description>
			Everything below requires <code>can_admin</code>, which you hold — the pages linked from here
			will open. This chapter is hidden from everyone else, so nothing in it is a safe place to
			explain something a reader without the capability needs to know.
		</Alert.Description>
	</Alert.Root>

	<DocSection id="users" title="User management">
		<p>
			<AppLink href="/users">Users</AppLink> — <Cap cap="can_admin" /> — is the whole of access
			control. It lists every account with its capabilities as checkboxes and an active/inactive
			switch. There is no save button: every tick and every flick of the switch is written
			immediately, and a spinner beside the switch marks the moment it is in flight. If the server
			refuses the change, the control springs back and a message says why. Accounts with no
			capabilities are highlighted: those are people waiting on the approval-pending page.
		</p>
		<p>
			Granting <code>can_read</code> is what turns a pending account into a user. Tick the
			<strong>highest</strong> capability the person needs: most capabilities form a chain
			(<code>can_read &lt; can_read_detail &lt; can_edit &lt; can_publish</code>) in which the
			stronger entails every lesser one, so the boxes to its left tick themselves and lock —
			greyed, not editable, because unticking one of them would take nothing away. Untick the
			strongest and they are released, editable again. <code>create_api_key</code> and
			<code>add_project</code> sit outside the chain and must be granted explicitly — nobody gets to
			mint API keys by being able to publish. <code>can_admin</code> is the blanket flag: ticking it
			ticks and locks every other box on the row, since it implies them all, and unticking it hands
			them back. See
			<a href="/docs/capabilities" class="text-primary underline-offset-4 hover:underline"
				>Capabilities</a
			>.
		</p>
		<p>
			Deactivating an account disables its capabilities as a block rather than revoking them one by
			one — and it takes effect for that user's API keys too, since a key's effective capabilities
			are recomputed from its owner on every request.
		</p>
		<p>
			Two guardrails: an administrator cannot remove their own <code>can_admin</code>, and cannot
			deactivate themselves. There is no way to lock the last door from the inside.
		</p>
		<p>
			<strong>Adding a user before their first login.</strong> Where the deployment is backed by a directory,
			<strong>Add user</strong> searches it by username or name and provisions someone with a chosen
			set of capabilities, so they can work the moment they first sign in rather than landing on the
			pending page.
		</p>
		<p>
			Clicking a name opens their profile: account state, capabilities, and — for a directory
			account — the full set of directory attributes the repository holds on them.
		</p>
	</DocSection>

	<DocSection id="usage" title="What a user has actually read">
		<p>
			Every profile page carries an <strong>API usage</strong> panel: when the person was last
			active, how many distinct concepts they have read, the total number of reads, and a table of
			the concepts themselves with a per-concept read count and the first and last time each was
			read. Concept names link straight through.
		</p>
		<p>
			Anyone may see their own; seeing someone else's is <Cap cap="can_admin" />. It answers the
			questions the audit log answers only laboriously — who is actually using this, and what have
			they pulled — without paging through
			<AppLink href="/audit">the log</AppLink> itself.
		</p>
		<p>Two things to know before drawing conclusions from it:</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				It is a rollup <em>of the audit log</em>, counting successful API reads that resolved to a
				single concept. Browsing this app is not counted — those reads are made by the app on the
				person's behalf, and are attributed to it, not to them — and a read of a name that
				resolves to a group of concepts is not attributed to any one of them.
			</li>
			<li>
				<strong>Last active</strong> is broader than the table: it is their last API call of any
				kind, not their last concept read. So a person can be recently active with no new rows.
				It ignores app traffic on the same grounds the counts do, so somebody who is in this app
				every day but has never called the API themselves reads as never active.
			</li>
		</ul>
	</DocSection>

	<DocSection id="audit" title="The audit log">
		<p>
			<AppLink href="/audit">Audit</AppLink> — <Cap cap="can_admin" /> — records three kinds of event,
			one per tab:
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>Logins</strong> — every attempt, successful or not, with the source address. A failed
				attempt records the username that was tried.
			</li>
			<li>
				<strong>API calls</strong> — every request an authenticated client made, with its project,
				the concept it read and the version actually <em>served</em>. External clients are shown by
				default; the app's own traffic can be included.
			</li>
			<li>
				<strong>Emails</strong> — every message the system sent, or tried to send, or deliberately
				did not, with the reason in plain words.
			</li>
		</ul>
		<p>
			Filters — date range, user, project, concept, client type, free text — all live in the URL, so
			a filtered view is a link you can send to someone. <strong>Details</strong> on a row opens the
			full record: for a concept read, both what the client <em>asked</em> for (a version, a date, a draft,
			or nothing) and what was served. That pairing is the point of the log — it is what lets you reconstruct,
			months later, exactly what a study saw.
		</p>
	</DocSection>

	<DocSection id="projects" title="Projects and the licence">
		<p>
			<AppLink href="/projects">Projects</AppLink> is not admin-only — every signed-in user can see
			the register — but it is where external access is governed, so it belongs here too.
		</p>
		<p>
			Creating a project needs <Cap cap="add_project" />. A project has a name (the exact string
			external clients pass as <code>?project=</code>), a description, an optional ethics-approval
			reference, and one or more <strong>leads</strong>. Editing a project is governed by lead
			membership, not by a capability: its leads, and administrators, may edit it.
		</p>
		<p>
			<strong>The licence gate.</strong> A project must accept the current licence version before it
			can be created, and re-accept it whenever a new version is issued. Until it does, its API reads
			are refused — which is why a client that worked last week can start returning 403 without
			anything about the key having changed. The project page shows the licence state and gives a
			lead the button to accept it.
		</p>
		<p>
			Deleting a project is a soft delete: it disappears from the register and external clients
			naming it are rejected, but nothing in the audit log is lost.
		</p>
		<p>
			Each project page also charts its API activity over the last day, week and month — built from
			the audit log, which is what makes the <code>?project=</code> parameter worth insisting on.
			It also carries the project's
			<a href="#study-context" class="text-primary underline-offset-4 hover:underline"
				>study context</a
			>, below.
		</p>
	</DocSection>

	<DocSection id="study-context" title="Study context">
		<p>
			Below the project's details sits a <strong>Study context</strong> card: the research frame of
			the study the project <em>is</em>, as opposed to the definitions it reads.
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				<strong>PICO</strong> — <em>Population</em> (who the study is about),
				<em>Intervention</em> (what is done or measured), <em>Comparison</em> (what it is contrasted
				with) and <em>Outcome</em> (what is observed). Free text, each element optional.
			</li>
			<li>
				<strong>Study team</strong> <span class="italic">(Projektteilnehmer)</span> — who is behind
				the study.
			</li>
		</ul>
		<p>
			The pencil opens all five fields at once. No capability is involved: study context follows
			the same rule as the rest of the project, so a <strong>lead</strong> or an administrator may
			edit it and nobody else — and, like every other project edit, not on a deleted project.
			Clearing a field and saving empties it.
		</p>
		<p>
			The card is <strong>hidden entirely while it is empty</strong>, unless you can edit it — in
			which case you get an empty card inviting you to fill it in. So a reader never meets a row of
			blank labels. Nothing outside the app ever writes these fields: no import fills them in and
			no reimport overwrites them, so what a lead types stays until somebody edits it again.
		</p>
	</DocSection>

	<DocSection id="export" title="Exporting the catalogue">
		<p>
			<Cap cap="can_admin" /> adds an <strong>Export</strong> button to
			<AppLink href="/concepts">the concept list</AppLink>. It writes the current filtered selection
			as CSV or Excel — one row per concept, with its name in every taxonomy, its documentation and
			its configured sources — and optionally the latest published JSON and Python of each source as
			extra columns. The as-of date applies, so you can export the catalogue as it stood on any date.
		</p>
	</DocSection>

	<DocSection id="reimport" title="Reference-data reimports">
		<p>
			Where a deployment imports its concepts from an upstream dataset, that import re-runs
			periodically and can also be triggered by an operator on the server. It is not a control in
			this app — there is no button — but its effects are visible here, so it is worth knowing what
			it does:
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				A definition that moved upstream gets a <strong>new version</strong>, marked as a sync rather
				than as somebody's edit. An identical one is compared and skipped, and a definition that
				disappeared upstream is reported but never removed.
			</li>
			<li>
				A manual reimport <strong>pulls the documentation export first</strong> and only then runs
				the upsert — so the two always land together, and if the documentation pull fails nothing is
				imported at all rather than half of it.
			</li>
			<li>
				Documentation fields the export carries are <strong>overwritten</strong> for every concept it
				names. A concept the export does not mention keeps what it has.
			</li>
		</ul>
	</DocSection>

	<DocSection id="keys" title="API keys, from the admin side">
		<p>
			Ordinary users mint read-only keys. Only an administrator can issue a key with wider scopes,
			and no key can ever carry <code>create_api_key</code> — a key must not be able to mint further
			keys. A key's effective capabilities are its scopes intersected with its owner's current
			capabilities, recomputed per request, so revoking a person's capability immediately narrows
			every key they hold. See
			<a href="/docs/clients#keys" class="text-primary underline-offset-4 hover:underline"
				>Connecting clients</a
			>.
		</p>
	</DocSection>
</DocPage>
