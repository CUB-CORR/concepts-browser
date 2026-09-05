<script lang="ts">
	import { enhance } from "$app/forms";
	import { toast } from "svelte-sonner";
	import { SvelteSet } from "svelte/reactivity";
	import * as Table from "$lib/components/ui/table";
	import * as Dialog from "$lib/components/ui/dialog";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Badge } from "$lib/components/ui/badge";
	import { Checkbox } from "$lib/components/ui/checkbox";
	import KeyRoundIcon from "@lucide/svelte/icons/key-round";
	import CopyIcon from "@lucide/svelte/icons/copy";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import { formatTimestamp } from "$lib/format";
	import { type ApiKeyCreated, type Capability } from "$lib/types";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const CAP_LABELS: Record<Capability, string> = {
		can_read: "Read",
		can_read_detail: "Read code",
		can_edit: "Edit",
		can_publish: "Publish",
		create_api_key: "API keys",
		add_project: "Add projects",
		can_admin: "Admin",
	};

	const EXPIRY_OPTIONS = [
		{ label: "30 days", value: "30" },
		{ label: "90 days", value: "90" },
		{ label: "1 year", value: "365" },
		{ label: "Never", value: "" },
	];

	let dialogOpen = $state(false);
	let name = $state("");
	let expiry = $state("365");
	const scopes = new SvelteSet<Capability>();
	let creating = $state(false);
	// The one-time plaintext of the just-created key, surfaced until dismissed.
	let newKey = $state<ApiKeyCreated | null>(null);

	// What a fresh key is for, almost always: corr-vars needs the snippets, so "Read code"
	// when grantable, plain "Read" otherwise. Mirrors what non-admins get server-side.
	function seedDefaultScope() {
		scopes.clear();
		if (data.grantableScopes.includes("can_read_detail")) scopes.add("can_read_detail");
		else if (data.grantableScopes.includes("can_read")) scopes.add("can_read");
	}
	seedDefaultScope();

	function resetForm() {
		name = "";
		expiry = "365";
		seedDefaultScope();
	}

	function toggle(c: Capability) {
		if (scopes.has(c)) scopes.delete(c);
		else scopes.add(c);
	}

	async function copyKey() {
		if (!newKey) return;
		try {
			await navigator.clipboard.writeText(newKey.key);
			toast.success("Key copied to clipboard");
		} catch {
			toast.error("Copy failed — select and copy manually");
		}
	}

	function keyStatus(k: { revoked: boolean; expires_at: string | null }): {
		label: string;
		variant: "secondary" | "outline" | "destructive";
	} {
		if (k.revoked) return { label: "Revoked", variant: "destructive" };
		if (k.expires_at && new Date(`${k.expires_at}Z`) < new Date())
			return { label: "Expired", variant: "destructive" };
		return { label: "Active", variant: "secondary" };
	}
</script>

<svelte:head><title>API keys</title></svelte:head>

<div class="mx-auto flex max-w-4xl flex-col gap-6 px-4 py-6">
	<div class="flex items-start justify-between gap-4">
		<h1 class="text-2xl font-semibold tracking-tight">API keys</h1>

		<Dialog.Root
			bind:open={dialogOpen}
			onOpenChange={(v) => {
				if (!v) resetForm();
			}}
		>
			<Dialog.Trigger>
				{#snippet child({ props })}
					<Button {...props} size="sm">
						<KeyRoundIcon class="size-4" />
						New key
					</Button>
				{/snippet}
			</Dialog.Trigger>
			<Dialog.Content class="sm:max-w-lg">
				<Dialog.Header>
					<Dialog.Title>Create an API key</Dialog.Title>
					<Dialog.Description>
						The full key is shown only once, right after creation. Store it somewhere safe.
					</Dialog.Description>
				</Dialog.Header>

				<form
					method="POST"
					action="?/create"
					class="flex flex-col gap-4"
					use:enhance={() => {
						creating = true;
						return async ({ result, update }) => {
							creating = false;
							if (result.type === "success" && result.data?.created) {
								newKey = result.data.created as ApiKeyCreated;
								dialogOpen = false;
								resetForm();
								await update(); // refresh the list
							} else if (result.type === "failure") {
								toast.error(String(result.data?.error ?? "Could not create key"));
							}
						};
					}}
				>
					<div class="flex flex-col gap-1.5">
						<Label for="key-name">Name</Label>
						<Input
							id="key-name"
							name="name"
							bind:value={name}
							placeholder="e.g. CI pipeline"
							required
						/>
					</div>

					<div class="flex flex-col gap-2">
						<Label>Scopes</Label>
						{#if data.isAdmin}
							<div class="flex flex-wrap gap-x-4 gap-y-2">
								{#each data.grantableScopes as c (c)}
									<Label class="flex cursor-pointer items-center gap-1.5 text-sm font-normal">
										<Checkbox checked={scopes.has(c)} onCheckedChange={() => toggle(c)} />
										{CAP_LABELS[c]}
									</Label>
								{/each}
							</div>
							<p class="text-muted-foreground text-xs">
								Leave all unchecked for a key that authenticates but can do nothing on its own.
							</p>
						{:else}
							<p class="text-muted-foreground text-sm">
								Your keys are <span class="font-medium">read-only</span> — they can query concepts
								(including code, as far as you may read it) and nothing else.
							</p>
						{/if}
					</div>

					<div class="flex flex-col gap-1.5">
						<Label for="key-expiry">Expires</Label>
						<select
							id="key-expiry"
							name="expires_in_days"
							bind:value={expiry}
							class="border-input bg-background ring-offset-background focus-visible:ring-ring h-9 rounded-md border px-3 py-1 text-sm focus-visible:ring-2 focus-visible:outline-none"
						>
							{#each EXPIRY_OPTIONS as opt (opt.value)}
								<option value={opt.value}>{opt.label}</option>
							{/each}
						</select>
					</div>

					<input type="hidden" name="scopes" value={[...scopes].join(",")} />

					<Dialog.Footer>
						<Button type="submit" disabled={creating || !name.trim()}>
							{#if creating}<LoaderIcon class="size-4 animate-spin" />{/if}
							Create key
						</Button>
					</Dialog.Footer>
				</form>
			</Dialog.Content>
		</Dialog.Root>
	</div>

	<!-- One-time plaintext of a freshly created key. -->
	{#if newKey}
		<div class="rounded-lg border border-amber-300 bg-amber-50 p-4 dark:border-amber-700 dark:bg-amber-950/30">
			<div class="flex items-center justify-between gap-2">
				<span class="text-sm font-medium text-amber-900 dark:text-amber-200">
					Copy your new key “{newKey.name}” now — it won’t be shown again.
				</span>
				<button
					type="button"
					class="text-amber-900 underline underline-offset-2 dark:text-amber-200"
					onclick={() => (newKey = null)}
				>
					Dismiss
				</button>
			</div>
			<div class="mt-2 flex items-center gap-2">
				<code
					class="flex-1 overflow-x-auto rounded border bg-white px-3 py-2 font-mono text-xs whitespace-nowrap dark:bg-neutral-900"
				>
					{newKey.key}
				</code>
				<Button size="sm" variant="outline" onclick={copyKey}>
					<CopyIcon class="size-4" />
					Copy
				</Button>
			</div>
		</div>
	{/if}

	<div class="rounded-lg border">
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head>Name</Table.Head>
					<Table.Head>Scopes</Table.Head>
					<Table.Head>Expires</Table.Head>
					<Table.Head>Last used</Table.Head>
					<Table.Head class="w-24 text-center">Status</Table.Head>
					<Table.Head class="w-24"></Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				{#each data.keys as key (key.id)}
					{@const status = keyStatus(key)}
					<Table.Row>
						<Table.Cell>
							<div class="flex flex-col gap-0.5">
								<span class="font-medium">{key.name}</span>
								<span class="text-muted-foreground font-mono text-xs">{key.key_prefix}…</span>
							</div>
						</Table.Cell>
						<Table.Cell>
							<div class="flex flex-wrap gap-1">
								{#each key.scopes as s (s)}
									<Badge variant="outline" class="text-[10px]">{CAP_LABELS[s] ?? s}</Badge>
								{:else}
									<span class="text-muted-foreground text-xs">none</span>
								{/each}
							</div>
						</Table.Cell>
						<Table.Cell class="text-sm">
							{key.expires_at ? formatTimestamp(key.expires_at) : "Never"}
						</Table.Cell>
						<Table.Cell class="text-muted-foreground text-sm">
							{key.last_used_at ? formatTimestamp(key.last_used_at) : "Never"}
						</Table.Cell>
						<Table.Cell class="text-center">
							<Badge variant={status.variant} class="text-[10px]">{status.label}</Badge>
						</Table.Cell>
						<Table.Cell>
							{#if !key.revoked}
								<form
									method="POST"
									action="?/revoke"
									use:enhance={() => {
										return async ({ result, update }) => {
											await update();
											if (result.type === "success") toast.success(`Revoked ${key.name}`);
											else if (result.type === "failure")
												toast.error(String(result.data?.error ?? "Revoke failed"));
										};
									}}
								>
									<input type="hidden" name="key_id" value={key.id} />
									<Button
										type="submit"
										size="sm"
										variant="outline"
										class="text-destructive hover:text-destructive"
									>
										Revoke
									</Button>
								</form>
							{/if}
						</Table.Cell>
					</Table.Row>
				{:else}
					<Table.Row>
						<Table.Cell colspan={6} class="text-muted-foreground py-8 text-center text-sm">
							No API keys yet. Create one to authenticate scripts and CI.
						</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	</div>
</div>
