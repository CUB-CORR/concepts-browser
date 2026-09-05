<script lang="ts">
	import { enhance } from "$app/forms";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Label } from "$lib/components/ui/label";
	import * as Card from "$lib/components/ui/card";
	import * as Dialog from "$lib/components/ui/dialog";
	import * as Alert from "$lib/components/ui/alert";
	import ConceptSearchPicker from "$lib/components/ConceptSearchPicker.svelte";
	import { changeTypeVariant, formatTimestamp } from "$lib/format";
	import { toast } from "svelte-sonner";
	import ArchiveIcon from "@lucide/svelte/icons/archive";
	import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";
	import FileTextIcon from "@lucide/svelte/icons/file-text";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import type { ActionData, PageData } from "./$types";
	import type { ConceptSearchResult, DeprecationRequest, OpenDraft } from "$lib/types";

	let { data, form }: { data: PageData; form: ActionData } = $props();

	const tabs = [
		{ key: "pending", label: "Pending" },
		{ key: "approved", label: "Approved" },
		{ key: "rejected", label: "Rejected" },
		{ key: "all", label: "All" },
	];

	// The request being approved, and the successor the reviewer picked for it (which overrides
	// what the requester suggested).
	let approving = $state<DeprecationRequest | null>(null);
	let successor = $state<ConceptSearchResult | null>(null);

	function openApprove(r: DeprecationRequest) {
		approving = r;
		successor = null;
	}

	const statusVariant = (s: string) =>
		s === "approved" ? "default" : s === "rejected" ? "outline" : "secondary";

	// The concept page with this draft open: the source tab it belongs to, the draft pinned as
	// the overlay, and `cid` naming which concept — a name may point at several, and the queue
	// row is about exactly one of them. A concept holding no name at all can only be reached by
	// id, which resolves to the same page.
	function draftHref(d: OpenDraft): string {
		if (!d.taxonomy || !d.name) return `/concepts/id/${d.concept_id}`;
		const query = new URLSearchParams();
		if (d.source) query.set("source", d.source);
		query.set("draft", String(d.id));
		query.set("cid", String(d.concept_id));
		return `/concepts/tax/${encodeURIComponent(d.taxonomy)}/${encodeURIComponent(d.name)}?${query}`;
	}
</script>

<svelte:head><title>Review</title></svelte:head>

<div class="mx-auto flex max-w-5xl flex-col gap-10 px-4 py-6">
	<h1 class="text-2xl font-semibold tracking-tight">Review</h1>

	{#if form?.error}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Title>{form.error}</Alert.Title>
		</Alert.Root>
	{/if}

	<section class="flex flex-col gap-3">
		<div class="flex items-center gap-2">
			<h2 class="text-lg font-semibold tracking-tight">Drafts awaiting review</h2>
			<Badge variant="secondary">{data.drafts.length}</Badge>
		</div>

		{#if data.drafts.length === 0}
			<div class="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
				<FileTextIcon class="mx-auto mb-2 size-6 opacity-60" />
				No open drafts — every definition that has been written is published.
			</div>
		{:else}
			<div class="divide-y rounded-lg border">
				{#each data.drafts as d (d.id)}
					<div class="flex flex-col gap-2 p-4">
						<div class="flex flex-wrap items-center gap-2">
							<a
								href={draftHref(d)}
								class="font-mono text-sm font-medium underline-offset-2 hover:underline"
							>
								{d.name ?? `concept #${d.concept_id}`}
							</a>
							<span class="text-muted-foreground font-mono text-xs">#{d.concept_id}</span>
							{#if d.display_name}
								<span class="text-muted-foreground text-sm">· {d.display_name}</span>
							{/if}
							{#if d.concept_deprecated_at}
								<Badge variant="outline" class="text-xs">concept retired</Badge>
							{/if}
							<div class="ml-auto flex items-center gap-2">
								{#if d.source}
									<Badge variant="outline" class="font-mono text-xs">{d.source}</Badge>
								{/if}
								<Badge variant={changeTypeVariant(d.change_type)} class="text-xs">
									{d.change_type}
								</Badge>
							</div>
						</div>

						{#if d.message}
							<p class="text-sm">{d.message}</p>
						{/if}

						<div class="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
							<span>draft #{d.id}</span>
							<span class="font-mono">{d.type}</span>
							<span>started by <span class="font-medium">{d.author ?? "—"}</span></span>
							<span>{formatTimestamp(d.created_at)}</span>
							<a href={draftHref(d)} class="hover:text-foreground ml-auto underline underline-offset-2">
								Open draft
							</a>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</section>

	<section class="flex flex-col gap-3">
		<div class="flex items-center gap-2">
			<h2 class="text-lg font-semibold tracking-tight">Deprecation requests</h2>
			<Badge variant="secondary">{data.requests.length}</Badge>
		</div>
		<p class="text-muted-foreground text-sm">
			Editors ask for a name — or the concept behind it — to be retired; a reviewer decides. A
			concept that answers to other names loses only the name the request names; its last name
			takes the concept with it, and then approving records the successor clients should follow.
			Nothing is deleted, no version is renumbered, and retired names keep resolving.
		</p>

		<div class="flex flex-wrap items-center gap-1">
			{#each tabs as t (t.key)}
				<Button
					href="?status={t.key}"
					variant={data.status === t.key ? "secondary" : "ghost"}
					size="sm"
				>
					{t.label}
				</Button>
			{/each}
		</div>

		{#if data.requests.length === 0}
			<div class="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
				<ArchiveIcon class="mx-auto mb-2 size-6 opacity-60" />
				No {data.status === "all" ? "" : data.status} deprecation requests.
			</div>
		{:else}
			<div class="flex flex-col gap-3">
				{#each data.requests as r (r.id)}
					<Card.Root>
						<Card.Content class="flex flex-col gap-3">
							<div class="flex flex-wrap items-center gap-2">
								<a
									href="/concepts/id/{r.concept.id}"
									class="font-mono text-sm font-medium underline-offset-2 hover:underline"
								>
									{r.pointer?.name ?? r.concept.name ?? `concept #${r.concept.id}`}
								</a>
								<span class="text-muted-foreground font-mono text-xs">#{r.concept.id}</span>
								{#if r.concept.display_name}
									<span class="text-muted-foreground text-sm">· {r.concept.display_name}</span>
								{/if}
								<!-- What a decision here costs: one of several names, or the definition. -->
								<Badge variant="outline" class="ml-auto text-xs">
									{r.retires === "name" ? "retires this name" : "retires the concept"}
								</Badge>
								<Badge variant={statusVariant(r.status)} class="text-xs">{r.status}</Badge>
							</div>

							{#if r.reason}
								<p class="text-sm">{r.reason}</p>
							{/if}

							<div class="text-muted-foreground flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
								<span>requested by <span class="font-medium">{r.requested_by ?? "—"}</span></span>
								<span>{formatTimestamp(r.created_at)}</span>
								{#if r.successor}
									<span class="flex items-center gap-1">
										superseded by <ArrowRightIcon class="size-3" />
										<a
											href="/concepts/id/{r.successor.id}"
											class="hover:text-foreground font-mono underline underline-offset-2"
										>
											{r.successor.name ?? `#${r.successor.id}`}
										</a>
									</span>
								{/if}
								{#if r.resolved_by}
									<span>{r.status} by <span class="font-medium">{r.resolved_by}</span>
										· {formatTimestamp(r.resolved_at)}</span>
								{/if}
							</div>

							{#if r.status === "pending" && data.canDecide}
								<div class="flex items-center gap-2">
									<Button size="sm" onclick={() => openApprove(r)}>Approve…</Button>
									<form
										method="POST"
										action="?/reject"
										use:enhance={() => async ({ result, update }) => {
											if (result.type === "success") toast.success("Request rejected");
											await update();
										}}
									>
										<input type="hidden" name="requestId" value={r.id} />
										<Button type="submit" variant="ghost" size="sm">Reject</Button>
									</form>
								</div>
							{/if}
						</Card.Content>
					</Card.Root>
				{/each}
			</div>
		{/if}
	</section>
</div>

<Dialog.Root open={approving != null} onOpenChange={(o) => !o && (approving = null)}>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>
				Retire
				<span class="font-mono">
					{approving?.pointer?.name ?? approving?.concept.name ?? `#${approving?.concept.id}`}
				</span>?
			</Dialog.Title>
			<Dialog.Description>
				{#if approving?.retires === "name"}
					Only this name is retired — it stops listing but keeps resolving. Concept #{approving
						?.concept.id} stays live under its other names, keeps taking new versions, and its
					successor is left as it is.
				{:else}
					The concept is marked retired and takes no new versions. Its names keep resolving and its
					published history is untouched.
				{/if}
			</Dialog.Description>
		</Dialog.Header>

		<form
			method="POST"
			action="?/approve"
			class="flex flex-col gap-4"
			use:enhance={() => async ({ result, update }) => {
				if (result.type === "success") {
					toast.success(approving?.retires === "name" ? "Name retired" : "Concept retired");
					approving = null;
				}
				await update();
			}}
		>
			<input type="hidden" name="requestId" value={approving?.id} />
			<input type="hidden" name="successor_id" value={successor?.concept_id ?? ""} />

			<div class="flex flex-col gap-1.5">
				<Label>Superseded by</Label>
				{#if approving?.retires === "name"}
					<p class="text-muted-foreground text-xs">
						Recorded on the request only — a successor replaces a concept, and this retires a name
						the concept can spare.
					</p>
				{/if}
				{#if approving?.successor}
					<p class="text-muted-foreground text-xs">
						Suggested: <span class="font-mono">{approving.successor.name ?? ""}</span>
						#{approving.successor.id}. Pick another to override it.
					</p>
				{/if}
				<ConceptSearchPicker
					bind:selected={successor}
					exclude={approving?.concept.id ?? null}
					placeholder="Search the replacing concept…"
				/>
			</div>

			<Dialog.Footer>
				<Button type="submit">Approve and retire</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
