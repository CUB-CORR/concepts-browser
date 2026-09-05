<script lang="ts">
	// Find a concept by any of its names, in any taxonomy.
	//
	// Backed by `GET /concepts/search` (through the app's own proxy route, so the token stays
	// server-side). Results are grouped per concept and carry every pointer that matched, which
	// is the point: the operator adding an ATC code knows the substance by its corr_v1 name, and
	// picking the right concept id is only possible if the picker shows what it is already
	// called elsewhere.
	import { Input } from "$lib/components/ui/input";
	import { Badge } from "$lib/components/ui/badge";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import type { ConceptSearchResult } from "$lib/types";

	let {
		selected = $bindable(null),
		exclude = null,
		placeholder = "Search concepts by any name…",
	}: {
		/** The chosen concept, or null. */
		selected?: ConceptSearchResult | null;
		/** A concept id never offered (a concept cannot point at, or succeed, itself). */
		exclude?: number | null;
		placeholder?: string;
	} = $props();

	let query = $state("");
	let results = $state<ConceptSearchResult[]>([]);
	let loading = $state(false);

	// Search-as-you-type, debounced. `seq` drops the answer to a query the user has already
	// typed past, which arrives out of order often enough to matter.
	let seq = 0;
	$effect(() => {
		const q = query.trim();
		if (!q) {
			results = [];
			loading = false;
			return;
		}
		const mine = ++seq;
		loading = true;
		const timer = setTimeout(async () => {
			try {
				const res = await fetch(`/concepts/search?q=${encodeURIComponent(q)}`);
				const found: ConceptSearchResult[] = res.ok ? await res.json() : [];
				if (mine === seq) results = found;
			} catch {
				if (mine === seq) results = [];
			} finally {
				if (mine === seq) loading = false;
			}
		}, 250);
		return () => clearTimeout(timer);
	});

	const offered = $derived(results.filter((r) => r.concept_id !== exclude));
</script>

<div class="flex flex-col gap-2">
	<Input bind:value={query} {placeholder} />

	{#if selected}
		<div class="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
			<Badge variant="secondary" class="font-mono">#{selected.concept_id}</Badge>
			{#each selected.matches.slice(0, 3) as m (m.taxonomy + m.identifier)}
				<span class="font-mono text-xs">{m.identifier}</span>
			{/each}
			<button
				type="button"
				class="text-muted-foreground hover:text-foreground ml-auto text-xs underline underline-offset-2"
				onclick={() => (selected = null)}
			>
				change
			</button>
		</div>
	{:else if query.trim()}
		<div class="max-h-56 overflow-y-auto rounded-md border">
			{#if loading}
				<div class="text-muted-foreground flex items-center gap-2 px-3 py-3 text-sm">
					<LoaderIcon class="size-3.5 animate-spin" /> Searching…
				</div>
			{:else}
				{#each offered as r (r.concept_id)}
					<button
						type="button"
						class="hover:bg-muted/50 flex w-full flex-col gap-1 border-b px-3 py-2 text-left last:border-0"
						onclick={() => (selected = r)}
					>
						<div class="flex flex-wrap items-center gap-1.5">
							<Badge variant="secondary" class="font-mono text-[11px]">#{r.concept_id}</Badge>
							{#each r.matches as m (m.taxonomy + m.identifier)}
								<Badge
									variant="outline"
									class="text-[11px] {m.deprecated_at ? 'text-muted-foreground line-through' : ''}"
								>
									<span class="text-muted-foreground mr-1">{m.taxonomy}:</span>
									<span class="font-mono">{m.identifier}</span>
								</Badge>
							{/each}
							{#if r.deprecated_at}
								<Badge variant="outline" class="text-muted-foreground text-[11px]">deprecated</Badge>
							{/if}
						</div>
						{#if r.description}
							<span class="text-muted-foreground line-clamp-1 text-xs">{r.description}</span>
						{/if}
					</button>
				{:else}
					<div class="text-muted-foreground px-3 py-3 text-sm">No concept matches.</div>
				{/each}
			{/if}
		</div>
	{/if}
</div>
