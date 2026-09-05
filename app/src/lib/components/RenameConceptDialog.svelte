<script lang="ts">
	// Rename = point a new identifier at the concept, then retire the old one. Two writes, in
	// that order, so the concept is never nameless in between and the old name keeps resolving
	// afterwards — nothing is renamed in place (see api/routers/pointers.py).
	//
	// The one thing the user has to decide is what a collision means: an identifier that is
	// already live for *another* concept is refused until they say they mean to form a group,
	// which is what the second step of this dialog asks.
	import { enhance, applyAction } from "$app/forms";
	import { Button } from "$lib/components/ui/button";
	import { Badge } from "$lib/components/ui/badge";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import * as Dialog from "$lib/components/ui/dialog";
	import * as Alert from "$lib/components/ui/alert";
	import { conceptContext } from "$lib/concept-context";
	import { toast } from "svelte-sonner";
	import PencilIcon from "@lucide/svelte/icons/pencil";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";
	import type { NameExistsConflict } from "$lib/types";

	let {
		taxonomy,
		name,
		pointerId,
	}: {
		/** The taxonomy and name this page was reached by — the pointer being replaced. */
		taxonomy: string;
		name: string;
		/** Id of that pointer; null when the page has none to retire (nothing to rename). */
		pointerId: number | null;
	} = $props();

	const concept = conceptContext();

	let open = $state(false);
	let identifier = $state("");
	let displayName = $state("");
	let busy = $state(false);
	let errorMsg = $state<string | null>(null);
	// Set once the API has said the name is taken; the submit then re-sends confirmed.
	let conflict = $state<NameExistsConflict | null>(null);

	function reset() {
		identifier = "";
		displayName = "";
		errorMsg = null;
		conflict = null;
		busy = false;
	}
</script>

<Dialog.Root bind:open onOpenChange={(o) => !o && reset()}>
	<Dialog.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="outline" size="sm" class="w-full" disabled={pointerId == null}>
				<PencilIcon class="size-4" /> Rename in {taxonomy}
			</Button>
		{/snippet}
	</Dialog.Trigger>

	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>Rename <span class="font-mono">{name}</span></Dialog.Title>
			<Dialog.Description>
				The new name is registered first, then <span class="font-mono">{name}</span> is retired.
				The old name keeps resolving to this concept — links and pinned versions stay valid.
			</Dialog.Description>
		</Dialog.Header>

		<form
			method="POST"
			action="?/rename"
			class="flex flex-col gap-4"
			use:enhance={() => {
				busy = true;
				return async ({ result }) => {
					busy = false;
					if (result.type === "failure") {
						const data = result.data as
							| { error?: string; conflict?: NameExistsConflict }
							| undefined;
						conflict = data?.conflict ?? null;
						errorMsg = conflict ? null : (data?.error ?? "The rename failed.");
					} else if (result.type === "redirect") {
						toast.success(`Renamed to ${identifier}`);
						open = false;
					}
					await applyAction(result);
				};
			}}
		>
			<input type="hidden" name="cid" value={concept.id} />
			<input type="hidden" name="taxonomy" value={taxonomy} />
			<input type="hidden" name="pointerId" value={pointerId} />
			<input type="hidden" name="confirm_group" value={conflict ? "true" : "false"} />

			<div class="flex flex-col gap-1.5">
				<Label for="rename-identifier">New name</Label>
				<Input
					id="rename-identifier"
					name="identifier"
					class="font-mono"
					bind:value={identifier}
					oninput={() => (conflict = null)}
					placeholder="e.g. serum_creatinine"
					required
				/>
			</div>

			<div class="flex flex-col gap-1.5">
				<Label for="rename-display">Display name</Label>
				<Input id="rename-display" name="display_name" bind:value={displayName} placeholder="optional" />
			</div>

			{#if identifier}
				<p class="text-muted-foreground flex flex-wrap items-center gap-1.5 text-sm">
					<span class="font-mono line-through">{name}</span>
					<ArrowRightIcon class="size-3.5" />
					<span class="font-mono font-medium">{identifier}</span>
				</p>
			{/if}

			{#if errorMsg}
				<Alert.Root variant="destructive">
					<TriangleAlertIcon class="size-4" />
					<Alert.Title>{errorMsg}</Alert.Title>
				</Alert.Root>
			{/if}

			{#if conflict}
				<Alert.Root>
					<TriangleAlertIcon class="size-4" />
					<Alert.Title>
						<span class="font-mono">{conflict.name}</span> already names another concept
					</Alert.Title>
					<Alert.Description>
						<div class="flex flex-col gap-1.5">
							<span>
								Using it here makes the name point at both — a group. That is allowed, but it is
								never an accident: confirm below, or pick a different name.
							</span>
							<div class="flex flex-wrap gap-1.5">
								{#each conflict.members as m (m.id)}
									<Badge variant="outline" class="text-xs">
										<span class="font-mono">#{m.id}</span>
										{#if m.display_name}<span class="text-muted-foreground ml-1">{m.display_name}</span>{/if}
									</Badge>
								{/each}
							</div>
						</div>
					</Alert.Description>
				</Alert.Root>
			{/if}

			<Dialog.Footer>
				<Button type="submit" disabled={!identifier || pointerId == null || busy}>
					{#if busy}<LoaderIcon class="size-4 animate-spin" />{/if}
					{conflict ? "Create the group and rename" : "Rename"}
				</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
