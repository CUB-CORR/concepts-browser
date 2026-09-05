<script lang="ts">
	import DocPage from "$lib/components/docs/DocPage.svelte";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import AdminChapterLink from "$lib/components/docs/AdminChapterLink.svelte";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import * as Table from "$lib/components/ui/table";
	import * as Alert from "$lib/components/ui/alert";
	import { Badge } from "$lib/components/ui/badge";
	import ShieldIcon from "@lucide/svelte/icons/shield";
	import LockIcon from "@lucide/svelte/icons/lock";
	import { ALL_CAPABILITIES } from "$lib/types";
	import { CAPABILITY_CHAIN } from "$lib/caps";

	// Mirrors api/security.ALL_CAPABILITIES (and $lib/types.ALL_CAPABILITIES, which is iterated
	// below so a capability can never be added to the app without appearing in this table).
	// `CAPABILITY_CHAIN` is imported rather than restated so the "entails" column cannot drift
	// from the rule $lib/caps.hasCapability actually applies.
	const described: Record<string, { grants: string; where: string }> = {
		can_read: {
			grants:
				"Browse the repository: the concept list, search, a concept's JSON definition, its version history, its documentation, the data-file libraries, projects — and this guide. The entry ticket; without it you land on the approval-pending page.",
			where: "/concepts, /files, /projects, /docs",
		},
		can_read_detail: {
			grants:
				"Read what a concept *computes*, not just what it declares: the Python snippets, and the bytes of the data files those snippets read. Everything can_read sees, plus the code behind it.",
			where: "concept pages, /files",
		},
		can_edit: {
			grants:
				"Create concepts, write and update drafts, edit documentation, rename concepts, manage taxonomy names and request that a concept be retired. Nothing an editor does is visible to readers until it is published.",
			where: "/concepts/new, the editor on a concept page",
		},
		can_publish: {
			grants:
				"Turn a draft into a published version, work the review queue and decide deprecation requests, set a concept's documentation status, and upload a new version of a data file — which cascades a new published version into every concept that reads it.",
			where: "/review, concept pages, /files",
		},
		create_api_key: {
			grants:
				"Mint and revoke personal API keys for programmatic access. Ordinary keys are read-only; only an administrator can widen a key's scopes.",
			where: "/api-keys",
		},
		add_project: {
			grants: "Register a new project, which is what an API client names on every read.",
			where: "/projects/new",
		},
		can_admin: {
			grants:
				"Everything above, implicitly — plus user management, granting and revoking capabilities, and the audit log. Administrators are the only ones who can widen an API key's scopes.",
			where: "/users, /audit",
		},
	};

	/** The lesser chain capabilities a chain member entails, for the table's third column. */
	function entails(cap: string): readonly string[] {
		const rank = (CAPABILITY_CHAIN as readonly string[]).indexOf(cap);
		return rank <= 0 ? [] : (CAPABILITY_CHAIN as readonly string[]).slice(0, rank);
	}

	const routeHref: Record<string, string> = {
		"/concepts": "/concepts",
		"/files": "/files",
		"/projects": "/projects",
		"/docs": "/docs",
		"/concepts/new": "/concepts/new",
		"/review": "/review",
		"/api-keys": "/api-keys",
		"/projects/new": "/projects/new",
		"/users": "/users",
		"/audit": "/audit",
	};
</script>

<DocPage slug="capabilities">
	<DocSection id="model" title="How access works">
		<p>
			Your account carries a set of <strong>capabilities</strong>. Most of them form a single
			<strong>chain</strong>, weakest to strongest — each one is a superset of the one before it, so
			holding a stronger capability entails every lesser one:
		</p>
		<div class="flex flex-wrap items-center gap-1.5 py-1">
			{#each CAPABILITY_CHAIN as cap, i (cap)}
				{#if i > 0}<span class="text-muted-foreground text-xs">&lt;</span>{/if}
				<Badge variant="outline" class="font-mono">{cap}</Badge>
			{/each}
		</div>
		<p>
			An editor can read what they edit; a publisher can review what they release. So
			<code>can_publish</code> alone is a complete grant for a maintainer — there is no need to tick
			the boxes to its left, and an account holding only <code>can_publish</code> browses, reads code
			and edits perfectly well.
		</p>
		<p>
			Two capabilities sit <strong>outside</strong> the chain, because they are orthogonal rather
			than stronger: <code>create_api_key</code> and <code>add_project</code>. Nobody gets to mint
			API keys by being able to publish; those have to be granted explicitly. And
			<code>can_admin</code> is the one blanket flag — it implies every capability, in the chain and
			out of it.
		</p>
		<p>
			Entailment is resolved when a request is evaluated, never written into your account. Your
			profile shows what was actually granted, so an account granted <code>can_publish</code> lists
			exactly that one word while being able to do all four things.
		</p>
		<p>
			You can see your own at any time: open the user menu in the top right — your capabilities are
			listed under your name — or follow <em>Profile</em> in that menu to your profile page, which
			shows them as labelled badges alongside your account state and, for a directory account, your
			directory attributes.
		</p>
		<p>
			The app hides what you cannot do: a control you do not have the capability for is simply not
			rendered, and a page you cannot open redirects you back to
			<AppLink href="/concepts">the concept list</AppLink>. The API enforces the same rules
			authoritatively, so hiding a button is a courtesy, not the security boundary — a request made
			by hand is refused just the same.
		</p>
		<Alert.Root>
			<ShieldIcon />
			<Alert.Title>New accounts start with nothing</Alert.Title>
			<Alert.Description>
				Signing in creates your account but grants no capabilities. Until an administrator grants
				<code>can_read</code>, you see only the approval-pending page. If you are stuck there, ask
				an administrator — the app cannot approve you.
			</Alert.Description>
		</Alert.Root>
	</DocSection>

	<DocSection id="table" title="The capabilities">
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-40">Capability</Table.Head>
					<Table.Head>What it allows</Table.Head>
					<Table.Head class="w-44">Mainly seen on</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				{#each ALL_CAPABILITIES as cap (cap)}
					<Table.Row>
						<Table.Cell class="align-top">
							<div class="flex flex-col gap-1">
								<Badge variant="outline" class="font-mono">{cap}</Badge>
								{#if entails(cap).length}
									<span class="text-muted-foreground text-[11px]">
										also grants {entails(cap).join(", ")}
									</span>
								{:else if cap === "can_admin"}
									<span class="text-muted-foreground text-[11px]">grants everything</span>
								{/if}
							</div>
						</Table.Cell>
						<Table.Cell class="text-muted-foreground align-top text-sm">
							{described[cap]?.grants}
						</Table.Cell>
						<Table.Cell class="align-top text-sm">
							{#each (described[cap]?.where ?? "").split(", ") as route, i (route)}
								{#if i > 0},&nbsp;{/if}
								{#if routeHref[route]}
									<a
										href={routeHref[route]}
										class="text-primary font-mono text-xs underline-offset-4 hover:underline"
										>{route}</a
									>
								{:else}
									<span class="font-mono text-xs">{route}</span>
								{/if}
							{/each}
						</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	</DocSection>

	<DocSection id="read-detail" title="can_read and can_read_detail">
		<p>
			The chain's first step is the one people meet most often, so it is worth stating plainly.
			<code>can_read</code> browses what a concept <em>declares</em>: the list, search, the JSON
			definition, version history, documentation, the data-file libraries with every file's path,
			size, digest, versions and the concepts that read it.
		</p>
		<p>
			<code>can_read_detail</code> adds what a concept <em>computes</em>: the Python snippets, and
			the bytes of the data files those snippets read. Everything else about a file — that it
			exists, what it is called, which versions it has, who read it — stays at
			<code>can_read</code>. Only the contents are withheld.
		</p>
		<Alert.Root>
			<LockIcon />
			<Alert.Title>What "locked" looks like</Alert.Title>
			<Alert.Description>
				A concept whose definition has a snippet you may not see shows a lock and a note naming the
				missing capability — rather than an empty box, which would read as "there is no code here".
				File rows lose their download link and say why. Machine clients are told the same thing
				explicitly; see
				<a href="/docs/clients#locked" class="underline underline-offset-4">Connecting clients</a>.
			</Alert.Description>
		</Alert.Root>
		<p>
			The split exists because a definition's JSON says what a concept <em>is</em> while its snippet
			is working code against a live data source. Cataloguing the first for a wide audience does not
			have to mean handing out the second.
		</p>
	</DocSection>

	<DocSection id="separation" title="Why edit and publish are separate">
		<p>
			<code>can_edit</code> writes a draft; <code>can_publish</code> turns it into a version other
			people's analyses will resolve to. Splitting them is the whole point of the review step: a
			domain expert can propose a change to a definition without being able to silently change what
			every running study reads.
		</p>
		<p>
			The same reasoning puts a file upload behind <code>can_publish</code> rather than
			<code>can_edit</code>: uploading a new version of a data file publishes a new version of every
			concept that reads it, which is publishing by another route. See
			<a href="/docs/files#cascade" class="text-primary underline-offset-4 hover:underline"
				>the cascade</a
			>.
		</p>
	</DocSection>

	<DocSection id="keys" title="Capabilities and API keys">
		<p>
			An API key carries <em>scopes</em>, drawn from the same list, and
			<code>create_api_key</code> is never among them — a key cannot mint further keys.
		</p>
		<p>
			What a key may actually do is worked out per request, by expanding the chain on
			<strong>both</strong> sides and intersecting: the key's scopes entail their lesser capabilities,
			the owner's capabilities entail theirs, and the key gets whatever both cover. Two consequences
			follow, and both are intended:
		</p>
		<ul class="ml-4 flex list-disc flex-col gap-1.5">
			<li>
				A key can never exceed its owner. Narrow the person and every key they hold narrows with
				them, immediately.
			</li>
			<li>
				A key scoped <code>can_publish</code> reads code, because the chain says so — while a key
				scoped <code>can_read</code> does not, no matter how privileged its owner is. The scope is a
				real ceiling, not a hint.
			</li>
		</ul>
		<p>
			In practice an ordinary key is read-only; only an administrator can issue one with more. See
			<a href="/docs/clients#keys" class="text-primary underline-offset-4 hover:underline"
				>Connecting clients</a
			>.
		</p>
	</DocSection>

	<DocSection id="getting" title="Getting a capability you are missing">
		<p>
			Only an administrator can grant one, on the
			<AppLink href="/users">user management page</AppLink>. If you cannot open a page this guide
			describes, that is the reason — nothing in the app grants you access to itself. See
			<AdminChapterLink>Administration</AdminChapterLink> for what that looks like from the other side.
		</p>
	</DocSection>
</DocPage>
