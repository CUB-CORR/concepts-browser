<script lang="ts">
	// Naming a concept in a taxonomy it has no name in yet — opened by picking a greyed-out
	// entry in the taxonomy selector on a concept page.
	//
	// It is one write, the same one a rename's first half makes: a pointer is registered
	// (api/routers/pointers.py), nothing is edited in place. A hand-typed name is `origin=user`,
	// which the reference import never retires — see `_sync_pointers`. As with a rename, an
	// identifier that is already live for *another* concept comes back as a `name_exists` 409
	// and is only accepted once the user confirms they mean to form a group.
	import { enhance, applyAction } from "$app/forms";
	import { Button } from "$lib/components/ui/button";
	import { Badge } from "$lib/components/ui/badge";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import * as Dialog from "$lib/components/ui/dialog";
	import * as Alert from "$lib/components/ui/alert";
	import { toast } from "svelte-sonner";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import type { NameExistsConflict } from "$lib/types";

	let {
		taxonomy = $bindable(),
		conceptId,
		conceptName,
		canEdit,
	}: {
		/** The taxonomy the concept is missing a name in; null closes the dialog. */
		taxonomy: string | null;
		conceptId: number;
		/** What the concept is called on the page the selector was used from. */
		conceptName: string;
		/** Registering a name needs can_edit; without it this only explains the situation. */
		canEdit: boolean;
	} = $props();

	let identifier = $state("");
	let displayName = $state("");
	let busy = $state(false);
	let errorMsg = $state<string | null>(null);
	// Set once the API has said the name is taken; the submit then re-sends confirmed.
	let conflict = $state<NameExistsConflict | null>(null);

	function close() {
		taxonomy = null;
		identifier = "";
		displayName = "";
		errorMsg = null;
		conflict = null;
		busy = false;
	}
</script>

<Dialog.Root open={taxonomy != null} onOpenChange={(o) => !o && close()}>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>
				Name <span class="font-mono">{conceptName}</span> in {taxonomy}
			</Dialog.Title>
			<Dialog.Description>
				This concept has no name in <strong>{taxonomy}</strong>, so there is no page for it there
				yet.
				{#if canEdit}
					Registering one points that identifier at concept
					<span class="font-mono">#{conceptId}</span> — the concept itself, its versions and its
					other names are untouched.
				{:else}
					Registering one takes the edit capability; ask an editor, or pick a taxonomy the
					concept is named in.
				{/if}
			</Dialog.Description>
		</Dialog.Header>

		{#if !canEdit}
			<Dialog.Footer>
				<Button variant="outline" onclick={close}>Close</Button>
			</Dialog.Footer>
		{:else}
			<form
				method="POST"
				action="?/addName"
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
							errorMsg = conflict ? null : (data?.error ?? "The name could not be registered.");
						} else if (result.type === "redirect") {
							toast.success(`${identifier} now names this concept in ${taxonomy}`);
							close();
						}
						await applyAction(result);
					};
				}}
			>
				<input type="hidden" name="cid" value={conceptId} />
				<input type="hidden" name="taxonomy" value={taxonomy} />
				<input type="hidden" name="confirm_group" value={conflict ? "true" : "false"} />

				<div class="flex flex-col gap-1.5">
					<Label for="addname-identifier">Name in {taxonomy}</Label>
					<Input
						id="addname-identifier"
						name="identifier"
						class="font-mono"
						bind:value={identifier}
						oninput={() => (conflict = null)}
						placeholder="the identifier this taxonomy uses"
						required
					/>
				</div>

				<div class="flex flex-col gap-1.5">
					<Label for="addname-display">Display name</Label>
					<Input
						id="addname-display"
						name="display_name"
						bind:value={displayName}
						placeholder="optional"
					/>
				</div>

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
											{#if m.display_name}<span class="text-muted-foreground ml-1"
													>{m.display_name}</span
												>{/if}
										</Badge>
									{/each}
								</div>
							</div>
						</Alert.Description>
					</Alert.Root>
				{/if}

				<Dialog.Footer>
					<Button type="submit" disabled={!identifier || busy}>
						{#if busy}<LoaderIcon class="size-4 animate-spin" />{/if}
						{conflict ? "Create the group and go there" : "Register the name"}
					</Button>
				</Dialog.Footer>
			</form>
		{/if}
	</Dialog.Content>
</Dialog.Root>
