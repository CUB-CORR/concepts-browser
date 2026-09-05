<script lang="ts">
	// One identifier, several concepts — a *group*. Legitimate and rare (an ATC code covering
	// several substances), but a page showing one member without saying so would read as the
	// whole truth, so the banner is loud and the member is switched explicitly (`?cid=`).
	import * as Select from "$lib/components/ui/select";
	import { goto } from "$app/navigation";
	import { page } from "$app/state";
	import LayersIcon from "@lucide/svelte/icons/layers";
	import type { ConceptDetail } from "$lib/types";

	let {
		members,
		selectedId,
		taxonomy,
		name,
	}: {
		members: ConceptDetail[];
		selectedId: number;
		taxonomy: string;
		name: string;
	} = $props();

	/** What tells the members apart: they share the name in *this* taxonomy, so the label comes
	 *  from another one — the canonical corr_v1 name where there is one. */
	function label(m: ConceptDetail): string {
		const alt =
			m.names.find((n) => n.taxonomy === "corr_v1" && !n.deprecated_at) ??
			m.names.find((n) => n.taxonomy !== taxonomy && !n.deprecated_at) ??
			m.names.find((n) => !n.deprecated_at);
		return alt?.identifier ?? m.display_name ?? m.description ?? `concept #${m.id}`;
	}

	const options = $derived(members.map((m) => ({ id: m.id, label: label(m) })));
	const selectedLabel = $derived(
		options.find((o) => o.id === selectedId)?.label ?? `concept #${selectedId}`,
	);

	function pick(next: string) {
		const url = new URL(page.url);
		url.searchParams.set("cid", next);
		// A version/draft pin belongs to the member it was chosen on.
		url.searchParams.delete("v");
		url.searchParams.delete("draft");
		goto(url, { invalidateAll: true });
	}
</script>

<div
	class="flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-200"
>
	<LayersIcon class="size-4 shrink-0" />
	<span>
		<span class="font-mono font-medium">{name}</span>
		points at <strong>{members.length} concepts</strong> in {taxonomy}. Showing one of them.
	</span>
	<div class="ml-auto flex items-center gap-2">
		<span class="text-xs">Member</span>
		<Select.Root type="single" value={String(selectedId)} onValueChange={pick}>
			<Select.Trigger class="h-8 min-w-[16rem] bg-background">
				{selectedLabel} · #{selectedId}
			</Select.Trigger>
			<Select.Content>
				{#each options as o (o.id)}
					<Select.Item value={String(o.id)} label={`${o.label} · #${o.id}`}>
						<span class="font-mono">{o.label}</span>
						<span class="text-muted-foreground ml-2 font-mono text-xs">#{o.id}</span>
					</Select.Item>
				{/each}
			</Select.Content>
		</Select.Root>
	</div>
</div>
