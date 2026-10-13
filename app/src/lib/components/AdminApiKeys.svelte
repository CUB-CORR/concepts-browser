<!-- An admin's view of another user's API keys, on that user's profile: when each was last used,
     re-scoping in place (the holder keeps the same secret), and revocation. Backed by the
     `rescope` / `revoke` actions of the profile route. -->
<script lang="ts">
	import { enhance } from "$app/forms";
	import { toast } from "svelte-sonner";
	import { SvelteSet } from "svelte/reactivity";
	import * as Table from "$lib/components/ui/table";
	import * as Dialog from "$lib/components/ui/dialog";
	import * as AlertDialog from "$lib/components/ui/alert-dialog";
	import { Button, buttonVariants } from "$lib/components/ui/button";
	import { Badge } from "$lib/components/ui/badge";
	import { Checkbox } from "$lib/components/ui/checkbox";
	import { Label } from "$lib/components/ui/label";
	import { expandCapabilities } from "$lib/caps";
	import { formatTimestamp } from "$lib/format";
	import type { ApiKey, Capability } from "$lib/types";
	import type { SubmitFunction } from "@sveltejs/kit";

	let {
		keys,
		userId,
		ownerCapabilities,
		labels,
	}: {
		keys: ApiKey[];
		userId: number;
		ownerCapabilities: Capability[];
		labels: Record<Capability, string>;
	} = $props();

	// What a key of this owner may carry: everything they hold, never the key-minting capability.
	const grantable = $derived(
		expandCapabilities(ownerCapabilities).filter((c) => c !== "create_api_key"),
	);

	let editing = $state<ApiKey | null>(null);
	const scopes = new SvelteSet<Capability>();
	let saving = $state(false);

	function openEditor(key: ApiKey) {
		scopes.clear();
		for (const s of key.scopes) scopes.add(s);
		editing = key;
	}

	function toggle(c: Capability) {
		if (scopes.has(c)) scopes.delete(c);
		else scopes.add(c);
	}

	function keyStatus(k: ApiKey): { label: string; variant: "secondary" | "destructive" } {
		if (k.revoked) return { label: "Revoked", variant: "destructive" };
		if (k.expires_at && new Date(`${k.expires_at}Z`) < new Date())
			return { label: "Expired", variant: "destructive" };
		return { label: "Active", variant: "secondary" };
	}

	function submitted(success: string): SubmitFunction {
		return () => {
			saving = true;
			return async ({ result, update }) => {
				saving = false;
				await update();
				if (result.type === "success") {
					editing = null;
					toast.success(success);
				} else if (result.type === "failure") {
					toast.error(String(result.data?.error ?? "Request failed"));
				}
			};
		};
	}
</script>

<div class="overflow-x-auto rounded-lg border">
	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>Name</Table.Head>
				<Table.Head>Scopes</Table.Head>
				<Table.Head>Last used</Table.Head>
				<Table.Head>Expires</Table.Head>
				<Table.Head class="w-20 text-center">Status</Table.Head>
				<Table.Head class="w-40"></Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each keys as key (key.id)}
				{@const status = keyStatus(key)}
				<Table.Row>
					<Table.Cell>
						<div class="flex flex-col gap-0.5">
							<span class="font-medium">{key.name}</span>
							<span class="text-muted-foreground font-mono text-xs">{key.key_prefix}…</span>
						</div>
					</Table.Cell>
					<Table.Cell>
						<div class="flex flex-wrap items-center gap-1">
							{#each key.scopes as s (s)}
								<Badge variant="outline" class="text-[10px]">{labels[s] ?? s}</Badge>
							{:else}
								<span class="text-muted-foreground text-xs">none</span>
							{/each}
							{#if !key.scopes_pinned}
								<span
									class="text-muted-foreground text-[10px]"
									title="The owner default: raised automatically when the owner is promoted"
								>
									auto
								</span>
							{/if}
						</div>
					</Table.Cell>
					<Table.Cell class="text-muted-foreground text-sm">
						{key.last_used_at ? formatTimestamp(key.last_used_at) : "Never"}
					</Table.Cell>
					<Table.Cell class="text-sm">
						{key.expires_at ? formatTimestamp(key.expires_at) : "Never"}
					</Table.Cell>
					<Table.Cell class="text-center">
						<Badge variant={status.variant} class="text-[10px]">{status.label}</Badge>
					</Table.Cell>
					<Table.Cell>
						{#if !key.revoked}
							<div class="flex justify-end gap-1.5">
								<Button size="sm" variant="outline" onclick={() => openEditor(key)}>Scopes</Button>
								<AlertDialog.Root>
									<AlertDialog.Trigger
										class={buttonVariants({ variant: "outline", size: "sm" }) +
											" text-destructive hover:text-destructive"}
									>
										Revoke
									</AlertDialog.Trigger>
									<AlertDialog.Content>
										<AlertDialog.Header>
											<AlertDialog.Title>Revoke “{key.name}”?</AlertDialog.Title>
											<AlertDialog.Description>
												Every request with this key is rejected from now on. The owner has to mint a
												new key; a revoked one cannot be restored.
											</AlertDialog.Description>
										</AlertDialog.Header>
										<AlertDialog.Footer>
											<AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
											<form method="POST" action="?/revoke" use:enhance={submitted(`Revoked ${key.name}`)}>
												<input type="hidden" name="user_id" value={userId} />
												<input type="hidden" name="key_id" value={key.id} />
												<AlertDialog.Action
													type="submit"
													class={buttonVariants({ variant: "destructive" })}
												>
													Revoke key
												</AlertDialog.Action>
											</form>
										</AlertDialog.Footer>
									</AlertDialog.Content>
								</AlertDialog.Root>
							</div>
						{/if}
					</Table.Cell>
				</Table.Row>
			{:else}
				<Table.Row>
					<Table.Cell colspan={6} class="text-muted-foreground py-6 text-center text-sm">
						No API keys.
					</Table.Cell>
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>
</div>

<Dialog.Root
	open={editing !== null}
	onOpenChange={(v) => {
		if (!v) editing = null;
	}}
>
	<Dialog.Content class="sm:max-w-lg">
		{#if editing}
			<Dialog.Header>
				<Dialog.Title>Scopes of “{editing.name}”</Dialog.Title>
				<Dialog.Description>
					Changes apply on the key's next request; its holder keeps the same secret. A key never
					exceeds its owner, so only what they hold is offered.
				</Dialog.Description>
			</Dialog.Header>

			<form
				method="POST"
				action="?/rescope"
				class="flex flex-col gap-4"
				use:enhance={submitted(`Updated ${editing.name}`)}
			>
				<input type="hidden" name="user_id" value={userId} />
				<input type="hidden" name="key_id" value={editing.id} />
				<input type="hidden" name="scopes" value={[...scopes].join(",")} />

				<div class="flex flex-wrap gap-x-4 gap-y-2">
					{#each grantable as c (c)}
						<Label class="flex cursor-pointer items-center gap-1.5 text-sm font-normal">
							<Checkbox checked={scopes.has(c)} onCheckedChange={() => toggle(c)} />
							{labels[c]}
						</Label>
					{/each}
				</div>
				<p class="text-muted-foreground text-xs">
					Saving pins the key to exactly these scopes: a later promotion of the owner leaves it
					alone. <span class="font-medium">Reset to default</span> instead makes it read as far as
					the owner can, and follow their promotions.
				</p>

				<Dialog.Footer class="gap-2">
					<Button type="submit" name="reset" value="1" variant="outline" disabled={saving}>
						Reset to default
					</Button>
					<Button type="submit" disabled={saving}>Save scopes</Button>
				</Dialog.Footer>
			</form>
		{/if}
	</Dialog.Content>
</Dialog.Root>
