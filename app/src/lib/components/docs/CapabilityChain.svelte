<script lang="ts">
	// `::capability-chain` — the chain, weakest to strongest, straight from $lib/caps so the guide
	// cannot list an order the app does not apply.
	import { Badge } from "$lib/components/ui/badge";
	import { CAPABILITY_CHAIN } from "$lib/caps";
</script>

<div class="flex flex-wrap items-center gap-1.5 py-1">
	{#each CAPABILITY_CHAIN as cap, i (cap)}
		{#if i > 0}<span class="text-muted-foreground text-xs">&lt;</span>{/if}
		<Badge variant="outline" class="font-mono">{cap}</Badge>
	{/each}
</div>
