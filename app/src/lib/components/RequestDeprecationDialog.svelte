<script lang="ts">
	// Ask for this name — or the concept behind it — to be retired, usually because it turned
	// out to be a duplicate.
	//
	// Filing is editorial work (can_edit); retiring is not, because every client pinned to the
	// concept is affected and the successor is a claim about equivalence somebody has to stand
	// behind. So this writes a request and a reviewer decides it on /review.
	//
	// The request carries the pointer it was filed from, so approving retires the name a reader
	// was actually looking at. A concept with other live names keeps the concept — only its last
	// name takes the definition with it, which is what the dialog says up front.
	import { enhance } from "$app/forms";
	import { Button } from "$lib/components/ui/button";
	import { Label } from "$lib/components/ui/label";
	import { Textarea } from "$lib/components/ui/textarea";
	import * as Dialog from "$lib/components/ui/dialog";
	import * as Alert from "$lib/components/ui/alert";
	import ConceptSearchPicker from "$lib/components/ConceptSearchPicker.svelte";
	import { conceptContext } from "$lib/concept-context";
	import { toast } from "svelte-sonner";
	import ArchiveIcon from "@lucide/svelte/icons/archive";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import type { ConceptSearchResult } from "$lib/types";

	let {
		name,
		pointerId = null,
		otherNames = 0,
	}: { name: string; pointerId?: number | null; otherNames?: number } = $props();

	const concept = conceptContext();

	// Whether retiring this name would leave the concept reachable. Only a hint for the wording:
	// the API decides it again at approval time, on the names the concept has then.
	const nameOnly = $derived(pointerId != null && otherNames > 0);

	let open = $state(false);
	let reason = $state("");
	let successor = $state<ConceptSearchResult | null>(null);
	let busy = $state(false);
	let errorMsg = $state<string | null>(null);

	function reset() {
		reason = "";
		successor = null;
		errorMsg = null;
		busy = false;
	}
</script>

<Dialog.Root bind:open onOpenChange={(o) => !o && reset()}>
	<Dialog.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="outline" size="sm" class="w-full">
				<ArchiveIcon class="size-4" /> Request deprecation
			</Button>
		{/snippet}
	</Dialog.Trigger>

	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>Retire <span class="font-mono">{name}</span>?</Dialog.Title>
			<Dialog.Description>
				A reviewer decides this. Nothing is deleted and no version is renumbered.
				{#if nameOnly}
					This concept has {otherNames === 1 ? "another name" : `${otherNames} other names`}, so an
					approved request retires only this one — the concept stays, under the rest.
				{:else}
					This is the concept's last name, so an approved request marks the concept itself retired
					and points clients at its successor.
				{/if}
			</Dialog.Description>
		</Dialog.Header>

		<form
			method="POST"
			action="?/requestDeprecation"
			class="flex flex-col gap-4"
			use:enhance={() => {
				busy = true;
				return async ({ result, update }) => {
					busy = false;
					if (result.type === "failure") {
						errorMsg = String((result.data as { error?: string })?.error ?? "The request failed.");
					} else if (result.type === "success") {
						toast.success("Deprecation requested — a reviewer will decide it");
						open = false;
					}
					await update({ reset: false });
				};
			}}
		>
			<input type="hidden" name="cid" value={concept.id} />
			<!-- Which name this is about. Without it the request would be about the concept, which
			     is how retiring one spelling used to retire the definition behind it. -->
			<input type="hidden" name="pointer_id" value={pointerId ?? ""} />
			<input type="hidden" name="successor_id" value={successor?.concept_id ?? ""} />

			<div class="flex flex-col gap-1.5">
				<Label for="deprecation-reason">Reason</Label>
				<Textarea
					id="deprecation-reason"
					name="reason"
					rows={3}
					bind:value={reason}
					placeholder="why this concept should be retired — e.g. duplicate of …"
					required
				/>
			</div>

			<div class="flex flex-col gap-1.5">
				<Label>Superseded by <span class="text-muted-foreground font-normal">(optional)</span></Label>
				<ConceptSearchPicker bind:selected={successor} exclude={concept.id} />
				<p class="text-muted-foreground text-xs">
					The concept clients should follow instead. Leave empty when there is no replacement.
					{#if nameOnly}
						Recorded on the request, but only applied if this turns out to be the concept's last
						name by the time a reviewer decides.
					{/if}
				</p>
			</div>

			{#if errorMsg}
				<Alert.Root variant="destructive">
					<TriangleAlertIcon class="size-4" />
					<Alert.Title>{errorMsg}</Alert.Title>
				</Alert.Root>
			{/if}

			<Dialog.Footer>
				<Button type="submit" disabled={!reason.trim() || busy}>
					{#if busy}<LoaderIcon class="size-4 animate-spin" />{/if}
					Request deprecation
				</Button>
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
