<script lang="ts">
	import { Input } from "$lib/components/ui/input";
	import { Badge } from "$lib/components/ui/badge";
	import { Checkbox } from "$lib/components/ui/checkbox";
	import XIcon from "@lucide/svelte/icons/x";
	import type { UserOption } from "$lib/types";

	// A searchable, checkable list of users. `selected` (ids) is bindable; the component also
	// emits a hidden <input name={name}> per selected id so plain form posts carry the values
	// (read them server-side with formData.getAll(name)). Ids in `locked` can't be removed.
	let {
		options,
		selected = $bindable([]),
		name = "lead_ids",
		locked = [],
	}: {
		options: UserOption[];
		selected?: number[];
		name?: string;
		locked?: number[];
	} = $props();

	let search = $state("");

	const byId = $derived(new Map(options.map((o) => [o.id, o])));

	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return options;
		return options.filter((o) => `${o.username} ${o.display_name ?? ""}`.toLowerCase().includes(q));
	});

	function label(o: UserOption): string {
		return o.display_name ? `${o.display_name} (${o.username})` : o.username;
	}

	function toggle(id: number, on: boolean) {
		if (on) {
			if (!selected.includes(id)) selected = [...selected, id];
		} else if (!locked.includes(id)) {
			selected = selected.filter((x) => x !== id);
		}
	}
</script>

{#each selected as id (id)}
	<input type="hidden" {name} value={id} />
{/each}

<div class="flex flex-col gap-2">
	{#if selected.length}
		<div class="flex flex-wrap gap-1.5">
			{#each selected as id (id)}
				{@const o = byId.get(id)}
				<Badge variant="secondary" class="gap-1">
					{o ? label(o) : `#${id}`}
					{#if !locked.includes(id)}
						<button
							type="button"
							class="hover:text-foreground -mr-0.5 cursor-pointer"
							aria-label="Remove"
							onclick={() => toggle(id, false)}
						>
							<XIcon class="size-3" />
						</button>
					{/if}
				</Badge>
			{/each}
		</div>
	{/if}

	<Input placeholder="Search users…" bind:value={search} />

	<div class="max-h-56 overflow-y-auto rounded-md border">
		{#each filtered as o (o.id)}
			{@const checked = selected.includes(o.id)}
			<label
				class="hover:bg-muted/50 flex cursor-pointer items-center gap-2 px-3 py-2 text-sm"
				class:opacity-60={locked.includes(o.id)}
			>
				<Checkbox
					{checked}
					disabled={locked.includes(o.id)}
					onCheckedChange={(v) => toggle(o.id, v === true)}
				/>
				<span>{label(o)}</span>
			</label>
		{/each}
		{#if filtered.length === 0}
			<div class="text-muted-foreground px-3 py-3 text-sm">No users match.</div>
		{/if}
	</div>
</div>
