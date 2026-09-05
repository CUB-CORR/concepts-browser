<script lang="ts">
	import * as Select from "$lib/components/ui/select";
	import AddTaxonomyNameDialog from "$lib/components/AddTaxonomyNameDialog.svelte";
	import { goto } from "$app/navigation";
	import { page } from "$app/state";
	import { can } from "$lib/caps";
	import { CONCEPT_ROUTE_ID, conceptHrefIn, liveNameIn } from "$lib/taxonomy-switch";
	import type { ConceptDetail, Taxonomy, User } from "$lib/types";

	let { taxonomies, value }: { taxonomies: Taxonomy[]; value: string } = $props();

	const label = $derived(taxonomies.find((t) => t.key === value)?.name ?? value);

	// On a concept page the switch is about *this concept*; anywhere else (the list, the create
	// form) it is only about what the browser is scoped to, and behaves as it always has.
	const data = $derived(page.data as { concept?: ConceptDetail; user?: User | null });
	const concept = $derived(page.route.id === CONCEPT_ROUTE_ID ? (data.concept ?? null) : null);
	const date = $derived(page.url.searchParams.get("date"));

	// Taxonomies the concept holds no live name in: shown, but muted, because picking one is not
	// a navigation — it is an offer to name the concept there.
	const unnamed = $derived(
		new Set(
			concept
				? taxonomies.filter((t) => !liveNameIn(concept.names, t.key, date)).map((t) => t.key)
				: [],
		),
	);

	// The selection bits-ui holds. Kept separate from the prop so that picking a muted entry —
	// which opens a dialog rather than navigating — can be undone without the trigger lying.
	let selected = $state("");
	$effect(() => {
		selected = value;
	});
	// The taxonomy the "name it here" dialog is about; null when closed.
	let missing = $state<string | null>(null);

	function choose(next: string) {
		if (!next || next === value) return;
		if (concept) {
			const name = liveNameIn(concept.names, next, date);
			if (!name) {
				// Nothing to navigate to — ask whether to give the concept a name there instead.
				missing = next;
				selected = value;
				return;
			}
			goto(conceptHrefIn(next, name.identifier, concept.id, page.url.searchParams), {
				invalidateAll: true,
			});
			return;
		}
		// Everywhere else: changing the active taxonomy re-scopes the browser; land on the list
		// for it, preserving the global date filter.
		const params = new URLSearchParams({ taxonomy: next });
		if (date) params.set("date", date);
		goto(`/concepts?${params}`, { invalidateAll: true });
	}
</script>

<Select.Root type="single" bind:value={selected} onValueChange={choose}>
	<Select.Trigger size="sm" class="w-[210px]" aria-label="Active taxonomy">
		<span class="text-muted-foreground mr-1 text-xs">Taxonomy</span>
		<span class="truncate">{label}</span>
	</Select.Trigger>
	<Select.Content>
		{#each taxonomies as t (t.key)}
			<Select.Item
				value={t.key}
				label={t.name ?? t.key}
				class={unnamed.has(t.key) ? "opacity-50" : undefined}
			>
				{t.name ?? t.key}
				<span class="text-muted-foreground ml-2 text-xs">
					{unnamed.has(t.key) ? "no name here" : t.key}
				</span>
			</Select.Item>
		{/each}
	</Select.Content>
</Select.Root>

{#if concept}
	<AddTaxonomyNameDialog
		bind:taxonomy={missing}
		conceptId={concept.id}
		conceptName={page.params.name ?? concept.name ?? String(concept.id)}
		canEdit={can(data.user ?? null, "can_edit")}
	/>
{/if}
