<script lang="ts">
	import TaxonomySelect from "$lib/components/TaxonomySelect.svelte";
	import DateFilter from "$lib/components/DateFilter.svelte";
	import type { Snippet } from "svelte";
	import type { LayoutData } from "./$types";

	let { data, children }: { data: LayoutData; children: Snippet } = $props();
</script>

<div
	class="bg-background sticky top-14 z-30 flex h-12 items-center gap-3 border-b px-4"
>
	<TaxonomySelect taxonomies={data.taxonomies} value={data.taxonomy} />
	<DateFilter value={data.date} />
</div>

{@render children()}
