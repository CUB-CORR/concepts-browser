<script lang="ts">
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { formatTimestamp } from "$lib/format";
	import { toast } from "svelte-sonner";
	import CopyIcon from "@lucide/svelte/icons/copy";
	import CheckIcon from "@lucide/svelte/icons/check";
	import ArchiveIcon from "@lucide/svelte/icons/archive";
	import type { ConceptDetail, PointerInfo } from "$lib/types";

	let {
		concept,
		taxonomy,
		name,
		pointer,
	}: {
		concept: ConceptDetail;
		/** The taxonomy and name this page was reached by — the pointer, not the concept. */
		taxonomy: string;
		name: string;
		/** The taxonomy entry that resolution went through, when the page has one. */
		pointer: PointerInfo | null;
	} = $props();

	// Every name but the one in the heading. Retired names are listed too, flagged: a reader
	// arriving from an old link needs to see that the spelling they used is one of these.
	const otherNames = $derived(
		concept.names.filter((n) => !(n.taxonomy === taxonomy && n.identifier === name)),
	);

	// What this concept is called *now* in the taxonomy the reader is browsing — the answer to
	// "then what is it called?" when the name they arrived by has been retired.
	const currentNames = $derived(
		concept.names.filter((n) => n.taxonomy === taxonomy && !n.deprecated_at),
	);
	const retiredName = $derived(Boolean(pointer?.deprecated_at));

	let copied = $state(false);
	async function copyId() {
		await navigator.clipboard.writeText(String(concept.id));
		copied = true;
		toast.success(`Concept id ${concept.id} copied`);
		setTimeout(() => (copied = false), 1500);
	}
</script>

<div class="flex flex-col gap-3">
	<div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
		<h1 class="font-mono text-2xl font-semibold tracking-tight" class:line-through={retiredName}>
			{name}
		</h1>
		{#if concept.display_name}
			<span class="text-muted-foreground text-lg">{concept.display_name}</span>
		{/if}
		{#if concept.version != null}
			<Badge variant="secondary" class="font-mono">v{concept.version}</Badge>
		{/if}
		<span class="text-muted-foreground text-xs">in {taxonomy}</span>
		<!-- The concept id is the identity everything else is addressed by; make it liftable. -->
		<Button
			variant="ghost"
			size="sm"
			class="text-muted-foreground h-6 gap-1 px-1.5 font-mono text-xs"
			title="Copy the concept id"
			onclick={copyId}
		>
			{#if copied}<CheckIcon class="size-3" />{:else}<CopyIcon class="size-3" />{/if}
			#{concept.id}
		</Button>
	</div>

	{#if retiredName}
		<div
			class="text-muted-foreground flex flex-wrap items-center gap-1.5 rounded-md border border-dashed px-3 py-2 text-sm"
		>
			<ArchiveIcon class="size-3.5 shrink-0" />
			<span>
				<span class="font-mono">{name}</span> was retired on
				{formatTimestamp(pointer?.deprecated_at)} — it still resolves here.
			</span>
			{#if currentNames.length}
				<span>Now called</span>
				{#each currentNames as n (n.id)}
					<a
						href="/concepts/tax/{encodeURIComponent(n.taxonomy)}/{encodeURIComponent(
							n.identifier,
						)}?cid={concept.id}"
						class="hover:text-foreground font-mono underline underline-offset-2"
					>
						{n.identifier}
					</a>
				{/each}
			{/if}
		</div>
	{/if}

	{#if concept.description}
		<p class="text-muted-foreground max-w-3xl text-sm">{concept.description}</p>
	{/if}

	{#if otherNames.length}
		<div class="flex flex-wrap items-center gap-1.5">
			<span class="text-muted-foreground text-xs">Also known as:</span>
			{#each otherNames as n (n.id)}
				<Badge
					variant="outline"
					class="text-xs {n.deprecated_at ? 'text-muted-foreground line-through' : ''}"
					title={n.deprecated_at
						? `Retired on ${formatTimestamp(n.deprecated_at)} — still resolves`
						: n.relationship === "alias"
							? "A secondary name of this concept"
							: undefined}
				>
					<span class="text-muted-foreground mr-1">{n.taxonomy}:</span>
					<span class="font-mono">{n.identifier}</span>
					{#if n.display_name}<span class="text-muted-foreground ml-1">({n.display_name})</span>{/if}
					{#if n.relationship === "alias"}<span class="text-muted-foreground ml-1">alias</span>{/if}
				</Badge>
			{/each}
		</div>
	{/if}
</div>
