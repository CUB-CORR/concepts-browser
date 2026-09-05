<script lang="ts">
	import { goto } from "$app/navigation";
	import { page } from "$app/state";
	import * as Table from "$lib/components/ui/table";
	import * as Select from "$lib/components/ui/select";
	import * as Tabs from "$lib/components/ui/tabs";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import AuditDetailDialog from "$lib/components/AuditDetailDialog.svelte";
	import SearchIcon from "@lucide/svelte/icons/search";
	import ChevronLeftIcon from "@lucide/svelte/icons/chevron-left";
	import ChevronRightIcon from "@lucide/svelte/icons/chevron-right";
	import type { AuditEvent } from "$lib/types";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	// The row whose full request is open in the dialog.
	let selected = $state<AuditEvent | null>(null);

	const isLogins = $derived(data.filters.tab === "login");
	const isCalls = $derived(data.filters.tab === "api_call");
	const isEmails = $derived(data.filters.tab === "email");
	const { items, total, limit, offset } = $derived(data.events);
	const lastPage = $derived(Math.max(1, Math.ceil(total / limit)));

	/** Filters live in the URL. Changing one always returns to page 1 — otherwise you can land
	 *  on page 7 of a 2-page result and see nothing. `null` clears a param. */
	function setParams(next: Record<string, string | number | null>) {
		const url = new URL(page.url);
		for (const [k, v] of Object.entries(next)) {
			if (v === null || v === "") url.searchParams.delete(k);
			else url.searchParams.set(k, String(v));
		}
		if (!("page" in next)) url.searchParams.delete("page");
		goto(url, { keepFocus: true });
	}

	function clearAll() {
		const url = new URL(page.url);
		for (const k of ["from", "to", "user", "project", "concept", "client", "status", "q", "page"]) {
			url.searchParams.delete(k);
		}
		goto(url);
	}

	/** Switching tabs drops every filter that doesn't exist on the tab being entered — a project
	 *  or concept means nothing for a login or an email, a send status means nothing for a
	 *  request, and leaving one set would silently empty the table. The date range and the user
	 *  are common to all three, so they survive the switch. */
	function switchTab(next: string) {
		setParams({
			tab: next === "logins" ? null : next,
			project: null,
			concept: null,
			client: null,
			status: null,
			q: null,
		});
	}

	const activeFilters = $derived(
		[
			data.filters.from,
			data.filters.to,
			data.filters.userId,
			data.filters.projectId,
			data.filters.conceptId,
			data.filters.emailStatus,
			data.filters.q,
		].filter(Boolean).length,
	);

	// Timestamps are naive UTC; mark them as such before rendering in the viewer's timezone.
	const when = (ts: string) =>
		new Date(ts + "Z").toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

	const userLabel = $derived(
		data.filters.userId
			? (data.options.users.find((u) => u.id === data.filters.userId)?.username ?? "All users")
			: "All users",
	);
	const projectLabel = $derived(
		data.filters.projectId
			? (data.options.projects.find((p) => p.id === data.filters.projectId)?.name ??
					"All projects")
			: "All projects",
	);
	const conceptLabel = $derived(
		data.filters.conceptId
			? (data.options.concepts.find((c) => c.id === data.filters.conceptId)?.name ??
					"All concepts")
			: "All concepts",
	);
	const clientLabels: Record<string, string> = {
		external: "External clients",
		app: "Web app",
		"": "All clients",
	};
	// "" is the filter's "no status chosen"; a row always has one.
	const statusLabels: Record<string, string> = {
		sent: "Sent",
		failed: "Failed",
		skipped: "Not sent",
		"": "Any status",
	};
	const statusLabel = (s: string | null) => (s ? (statusLabels[s] ?? s) : "—");

	const tabValue = $derived(isLogins ? "logins" : isCalls ? "calls" : "emails");

	/** A skipped send is not a failure — we never tried, because mail is off or the directory
	 *  has no address for the person. It still needs to be visible: it's the difference between
	 *  "they were told" and "we assumed they were". */
	const statusVariant = (s: string | null) =>
		s === "sent" ? "outline" : s === "failed" ? "destructive" : "secondary";
</script>

<svelte:head><title>Audit log</title></svelte:head>

<div class="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-6">
	<h1 class="text-2xl font-semibold tracking-tight">Audit log</h1>

	<Tabs.Root value={tabValue} onValueChange={switchTab}>
		<Tabs.List>
			<Tabs.Trigger value="logins">Logins</Tabs.Trigger>
			<Tabs.Trigger value="calls">API calls</Tabs.Trigger>
			<Tabs.Trigger value="emails">Emails</Tabs.Trigger>
		</Tabs.List>
	</Tabs.Root>

	<!-- Filters. Date and user apply to every tab; the rest only to the tab that has the column. -->
	<div class="flex flex-wrap items-end gap-3">
		<div class="flex flex-col gap-1.5">
			<Label class="text-muted-foreground text-xs" for="from">From</Label>
			<Input
				id="from"
				type="date"
				class="w-40"
				value={data.filters.from}
				onchange={(e) => setParams({ from: e.currentTarget.value })}
			/>
		</div>
		<div class="flex flex-col gap-1.5">
			<Label class="text-muted-foreground text-xs" for="to">To</Label>
			<Input
				id="to"
				type="date"
				class="w-40"
				value={data.filters.to}
				onchange={(e) => setParams({ to: e.currentTarget.value })}
			/>
		</div>

		<div class="flex flex-col gap-1.5">
			<!-- On the emails tab this column holds the recipient, not a caller. -->
			<Label class="text-muted-foreground text-xs">{isEmails ? "Recipient" : "User"}</Label>
			<Select.Root
				type="single"
				value={data.filters.userId ? String(data.filters.userId) : ""}
				onValueChange={(v) => setParams({ user: v || null })}
			>
				<Select.Trigger class="w-44">{userLabel}</Select.Trigger>
				<Select.Content>
					<Select.Item value="">All users</Select.Item>
					{#each data.options.users as u (u.id)}
						<Select.Item value={String(u.id)}>{u.display_name || u.username}</Select.Item>
					{/each}
				</Select.Content>
			</Select.Root>
		</div>

		{#if isEmails}
			<div class="flex flex-col gap-1.5">
				<Label class="text-muted-foreground text-xs">Status</Label>
				<Select.Root
					type="single"
					value={data.filters.emailStatus}
					onValueChange={(v) => setParams({ status: v || "all" })}
				>
					<Select.Trigger class="w-40">
						{statusLabels[data.filters.emailStatus] ?? "Any status"}
					</Select.Trigger>
					<Select.Content>
						<Select.Item value="all">Any status</Select.Item>
						<Select.Item value="sent">Sent</Select.Item>
						<Select.Item value="failed">Failed</Select.Item>
						<Select.Item value="skipped">Not sent</Select.Item>
					</Select.Content>
				</Select.Root>
			</div>
		{/if}

		{#if isCalls}
			<div class="flex flex-col gap-1.5">
				<Label class="text-muted-foreground text-xs">Project</Label>
				<Select.Root
					type="single"
					value={data.filters.projectId}
					onValueChange={(v) => setParams({ project: v || null })}
				>
					<Select.Trigger class="w-44">{projectLabel}</Select.Trigger>
					<Select.Content>
						<Select.Item value="">All projects</Select.Item>
						{#each data.options.projects as p (p.id)}
							<Select.Item value={p.id}>{p.name}</Select.Item>
						{/each}
					</Select.Content>
				</Select.Root>
			</div>

			<div class="flex flex-col gap-1.5">
				<Label class="text-muted-foreground text-xs">Concept</Label>
				<Select.Root
					type="single"
					value={data.filters.conceptId ? String(data.filters.conceptId) : ""}
					onValueChange={(v) => setParams({ concept: v || null })}
				>
					<Select.Trigger class="w-52">{conceptLabel}</Select.Trigger>
					<Select.Content>
						<Select.Item value="">All concepts</Select.Item>
						{#each data.options.concepts as c (c.id)}
							<Select.Item value={String(c.id)}>{c.name}</Select.Item>
						{/each}
					</Select.Content>
				</Select.Root>
			</div>

			<div class="flex flex-col gap-1.5">
				<Label class="text-muted-foreground text-xs">Client</Label>
				<Select.Root
					type="single"
					value={data.filters.client}
					onValueChange={(v) => setParams({ client: v || "all" })}
				>
					<Select.Trigger class="w-40">
						{clientLabels[data.filters.client] ?? "All clients"}
					</Select.Trigger>
					<Select.Content>
						<Select.Item value="external">External clients</Select.Item>
						<Select.Item value="app">Web app</Select.Item>
						<Select.Item value="all">All clients</Select.Item>
					</Select.Content>
				</Select.Root>
			</div>
		{/if}

		{#if isCalls || isEmails}
			<div class="flex flex-col gap-1.5">
				<Label class="text-muted-foreground text-xs" for="q">Search</Label>
				<div class="relative">
					<SearchIcon
						class="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
					/>
					<!-- Committed on Enter rather than per keystroke: each commit is a server round-trip. -->
					<Input
						id="q"
						class="w-56 pl-9"
						placeholder={isEmails ? "Subject or recipient…" : "Endpoint or concept…"}
						value={data.filters.q}
						onkeydown={(e) => e.key === "Enter" && setParams({ q: e.currentTarget.value })}
					/>
				</div>
			</div>
		{/if}

		{#if activeFilters > 0}
			<Button variant="ghost" size="sm" onclick={clearAll}>Clear ({activeFilters})</Button>
		{/if}
	</div>

	<div class="rounded-lg border">
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head class="w-48">Date</Table.Head>
					<Table.Head>{isEmails ? "Recipient" : "User"}</Table.Head>
					{#if isLogins}
						<Table.Head class="w-32">Result</Table.Head>
						<Table.Head class="w-40">IP address</Table.Head>
					{:else if isEmails}
						<Table.Head class="w-64">Address</Table.Head>
						<Table.Head>Subject</Table.Head>
						<Table.Head class="w-28">Status</Table.Head>
					{:else}
						<Table.Head class="w-36">Project</Table.Head>
						<Table.Head>Concept</Table.Head>
						<Table.Head class="w-24">Version</Table.Head>
						<Table.Head>Endpoint</Table.Head>
						<Table.Head class="w-20">Status</Table.Head>
					{/if}
					<Table.Head class="w-24"></Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				{#each items as e (e.id)}
					<Table.Row>
						<Table.Cell class="text-muted-foreground tabular-nums">{when(e.created_at)}</Table.Cell>

						<Table.Cell>
							{#if e.user}
								<a
									href="/users/{e.user.username}/profile"
									class="font-medium underline-offset-2 hover:underline"
								>
									{e.user.display_name || e.user.username}
								</a>
							{:else if isLogins}
								<!-- A failed login authenticates nobody: show the name that was tried. -->
								<span class="text-muted-foreground">
									{e.detail?.username ?? "—"}
									<span class="text-xs">(unknown)</span>
								</span>
							{:else}
								<span class="text-muted-foreground">—</span>
							{/if}
						</Table.Cell>

						{#if isLogins}
							<Table.Cell>
								{#if e.status_code === 200}
									<Badge variant="outline">Success</Badge>
								{:else}
									<Badge variant="destructive">Failed</Badge>
								{/if}
							</Table.Cell>
							<Table.Cell class="text-muted-foreground tabular-nums">
								{e.ip_address ?? "—"}
							</Table.Cell>
						{:else if isEmails}
							<Table.Cell class="text-muted-foreground font-mono text-xs">
								{#if e.email_to}
									{e.email_to}
								{:else}
									<!-- No address in the directory — which is why nothing was sent. -->
									<span class="italic">no address</span>
								{/if}
							</Table.Cell>
							<Table.Cell class="max-w-sm truncate">{e.email_subject ?? "—"}</Table.Cell>
							<Table.Cell>
								<Badge variant={statusVariant(e.email_status)}>{statusLabel(e.email_status)}</Badge>
							</Table.Cell>
						{:else}
							<Table.Cell>
								{#if e.project_name}
									<a
										href="/projects/{e.project_id}"
										class="underline-offset-2 hover:underline">{e.project_name}</a
									>
								{:else}
									<span class="text-muted-foreground text-xs">internal</span>
								{/if}
							</Table.Cell>
							<Table.Cell>
								{#if e.concept_name}
									<a
										href="/concepts/tax/{e.taxonomy}/{e.concept_name}"
										class="font-medium underline-offset-2 hover:underline">{e.concept_name}</a
									>
								{:else}
									<span class="text-muted-foreground">—</span>
								{/if}
							</Table.Cell>
							<Table.Cell class="tabular-nums">
								{#if e.concept_version !== null}
									v{e.concept_version}
								{:else}
									<span class="text-muted-foreground">—</span>
								{/if}
							</Table.Cell>
							<Table.Cell class="text-muted-foreground max-w-xs truncate font-mono text-xs">
								{e.method}
								{e.path}
							</Table.Cell>
							<Table.Cell class="tabular-nums">
								<span class={e.status_code && e.status_code >= 400 ? "text-destructive" : ""}>
									{e.status_code ?? "—"}
								</span>
							</Table.Cell>
						{/if}

						<Table.Cell class="text-right">
							<Button variant="ghost" size="sm" onclick={() => (selected = e)}>Details</Button>
						</Table.Cell>
					</Table.Row>
				{:else}
					<Table.Row>
						<Table.Cell
							colspan={isLogins ? 5 : isEmails ? 6 : 8}
							class="text-muted-foreground py-10 text-center text-sm"
						>
							No {isLogins ? "logins" : isEmails ? "emails" : "API calls"} match these filters.
						</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	</div>

	{#if total > 0}
		<div class="flex items-center justify-between text-sm">
			<span class="text-muted-foreground tabular-nums">
				{offset + 1}–{Math.min(offset + limit, total)} of {total}
			</span>
			<div class="flex items-center gap-2">
				<Button
					variant="outline"
					size="sm"
					disabled={data.filters.page <= 1}
					onclick={() => setParams({ page: data.filters.page - 1 })}
				>
					<ChevronLeftIcon class="size-4" />
					Previous
				</Button>
				<Button
					variant="outline"
					size="sm"
					disabled={data.filters.page >= lastPage}
					onclick={() => setParams({ page: data.filters.page + 1 })}
				>
					Next
					<ChevronRightIcon class="size-4" />
				</Button>
			</div>
		</div>
	{/if}
</div>

<AuditDetailDialog bind:event={selected} />
