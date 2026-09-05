<script lang="ts">
	import * as Card from "$lib/components/ui/card";
	import DatabaseIcon from "@lucide/svelte/icons/database";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
</script>

<svelte:head><title>Data files</title></svelte:head>

<div class="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6">
	<h1 class="text-2xl font-semibold tracking-tight">Data files</h1>

	{#if data.sources.length === 0}
		<div class="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
			No sources are configured.
		</div>
	{:else}
		<div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
			{#each data.sources as source (source.key)}
				<a href={`/files/${encodeURIComponent(source.key)}`} class="block">
					<Card.Root class="hover:bg-accent/40 h-full transition-colors">
						<Card.Header>
							<Card.Title class="flex items-center gap-2 font-mono text-base">
								<DatabaseIcon class="text-muted-foreground size-4" />
								{source.key}
							</Card.Title>
							{#if source.nicename}
								<Card.Description>{source.nicename}</Card.Description>
							{/if}
						</Card.Header>
					</Card.Root>
				</a>
			{/each}
		</div>
	{/if}
</div>
