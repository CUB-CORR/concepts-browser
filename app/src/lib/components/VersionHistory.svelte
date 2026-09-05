<script lang="ts">
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import * as AlertDialog from "$lib/components/ui/alert-dialog";
	import { enhance, applyAction } from "$app/forms";
	import { changeTypeVariant, formatTimestamp } from "$lib/format";
	import { conceptContext } from "$lib/concept-context";
	import { toast } from "svelte-sonner";
	import CopyIcon from "@lucide/svelte/icons/copy";
	import CheckIcon from "@lucide/svelte/icons/check";
	import GitBranchIcon from "@lucide/svelte/icons/git-branch";
	import Trash2Icon from "@lucide/svelte/icons/trash-2";
	import type { Draft, HistoryRow } from "$lib/types";

	let {
		taxonomy,
		name,
		source,
		rows,
		drafts = [],
		selectedVersion,
		activeDraftId = null,
		canDelete = false,
	}: {
		taxonomy: string;
		name: string;
		source: string;
		rows: HistoryRow[];
		drafts?: Draft[];
		selectedVersion: number | null;
		activeDraftId?: number | null;
		canDelete?: boolean;
	} = $props();

	const pinnedConcept = conceptContext();

	// The highest published version for this source is the live/current one.
	const latest = $derived(
		rows.reduce<number | null>(
			(m, r) => (r.version != null && (m == null || r.version > m) ? r.version : m),
			null,
		),
	);

	// A version is "applyable": clicking loads it into this source tab via ?v=, keeping the
	// tab open via ?source=. A draft opens via ?draft=.
	function versionHref(v: number | null): string {
		const p = new URLSearchParams({ source });
		if (v != null) p.set("v", String(v));
		return `?${p}`;
	}
	function draftHref(id: number): string {
		return `?${new URLSearchParams({ source, draft: String(id) })}`;
	}

	// A name that points at several concepts cannot address one concept's version — quote the
	// id form there, which is never ambiguous.
	function reference(v: number | null): string {
		return pinnedConcept.grouped
			? `GET /concept/id/${pinnedConcept.id}?v=${v}`
			: `GET /concept/${taxonomy}/${name}?v=${v}`;
	}

	let copied = $state<number | null>(null);
	async function copyRef(v: number | null) {
		await navigator.clipboard.writeText(reference(v));
		copied = v;
		toast.success("Reference copied", { description: reference(v) });
		setTimeout(() => (copied = v === copied ? null : copied), 1500);
	}
</script>

<div class="flex flex-col gap-2">
	<h4 class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">History</h4>

	<!-- Unpublished drafts sit "ahead" of the published timeline — amber accent + dashed to signal pending/future. -->
	{#if drafts.length}
		<ul
			class="divide-y divide-accent-mango/30 rounded-md border border-dashed border-accent-mango/40 bg-accent-mango/8 text-sm dark:divide-accent-mango/30 dark:border-accent-mango/50 dark:bg-accent-mango/10"
		>
			{#each drafts as d (d.id)}
				{@const open = d.id === activeDraftId}
				<li class="flex items-center gap-3 px-3 py-2 {open ? 'bg-accent-mango/20 dark:bg-accent-mango/20' : ''}">
					<a href={draftHref(d.id)} class="flex flex-1 items-center gap-2" data-sveltekit-noscroll>
						<Badge
							class="gap-1 border-accent-mango/50 bg-accent-mango/25 font-mono text-accent-mango-fg dark:border-accent-mango/50 dark:bg-accent-mango/25 dark:text-accent-mango-fg-dark"
						>
							<GitBranchIcon class="size-3" /> draft #{d.id}
						</Badge>
						<Badge variant={changeTypeVariant(d.change_type)} class="text-xs">{d.change_type}</Badge>
						{#if d.message}<span class="truncate">{d.message}</span>{/if}
					</a>
					<span class="shrink-0 text-xs text-accent-mango-fg dark:text-accent-mango-fg-dark">
						pending · {formatTimestamp(d.created_at)}
					</span>
					{#if canDelete}
						<AlertDialog.Root>
							<AlertDialog.Trigger>
								{#snippet child({ props })}
									<Button
										variant="ghost"
										size="icon"
										{...props}
										title="Discard draft"
										class="text-destructive hover:bg-destructive/10 hover:text-destructive size-7 shrink-0"
									>
										<Trash2Icon class="size-3.5" />
									</Button>
								{/snippet}
							</AlertDialog.Trigger>
							<AlertDialog.Content>
								<AlertDialog.Header>
									<AlertDialog.Title>Discard draft #{d.id}?</AlertDialog.Title>
									<AlertDialog.Description>
										This permanently deletes the unpublished draft for
										<span class="font-mono">{source}</span>. Published versions are unaffected.
									</AlertDialog.Description>
								</AlertDialog.Header>
								<form method="POST" action="?/deleteDraft" use:enhance={() => async ({ result }) => {
									if (result.type === "redirect" || result.type === "success") toast.success("Draft discarded");
									else if (result.type === "failure") toast.error(String(result.data?.error ?? "Delete failed"));
									await applyAction(result);
								}}>
									<input type="hidden" name="cid" value={pinnedConcept.id} />
									<input type="hidden" name="draftId" value={d.id} />
									<input type="hidden" name="source" value={source} />
									<AlertDialog.Footer>
										<AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
										<AlertDialog.Action type="submit" class="bg-destructive text-white hover:bg-destructive/90">
											Discard draft
										</AlertDialog.Action>
									</AlertDialog.Footer>
								</form>
							</AlertDialog.Content>
						</AlertDialog.Root>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	{#if rows.length === 0}
		<p class="text-muted-foreground text-sm">No published versions for this source yet.</p>
	{:else}
		<ul class="divide-y rounded-md border text-sm">
			{#each rows as r (r.version)}
				{@const active = r.version === selectedVersion}
				{@const isLatest = r.version === latest}
				<li
					class="flex items-center gap-3 px-3 py-2 {isLatest
						? 'bg-accent-green/8 dark:bg-accent-green/15'
						: active
							? 'bg-muted/60'
							: ''}"
				>
					<a href={versionHref(r.version)} class="flex flex-1 items-center gap-2" data-sveltekit-noscroll>
						<Badge
							variant="secondary"
							class="font-mono {isLatest
								? 'border border-accent-green/50 bg-accent-green/15 text-accent-green-fg dark:bg-accent-green/25 dark:text-accent-green-fg-dark'
								: ''}">v{r.version}</Badge
						>
						{#if isLatest}
							<Badge
								class="border-accent-green/50 bg-accent-green/25 text-xs text-accent-green-fg dark:border-accent-green/50 dark:bg-accent-green/25 dark:text-accent-green-fg-dark"
								>current</Badge
							>
						{/if}
						<Badge variant={changeTypeVariant(r.change_type)} class="text-xs">{r.change_type}</Badge>
						{#if r.message}<span class="truncate">{r.message}</span>{/if}
					</a>
					<span class="text-muted-foreground shrink-0 text-xs">{formatTimestamp(r.committed_at)}</span>
					<Button
						variant="ghost"
						size="icon"
						class="size-7 shrink-0"
						title="Copy reference"
						onclick={() => copyRef(r.version)}
					>
						{#if copied === r.version}<CheckIcon class="size-3.5" />{:else}<CopyIcon class="size-3.5" />{/if}
					</Button>
				</li>
			{/each}
		</ul>
	{/if}
</div>
