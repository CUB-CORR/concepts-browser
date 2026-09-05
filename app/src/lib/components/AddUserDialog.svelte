<script lang="ts">
	import { enhance } from "$app/forms";
	import { invalidateAll } from "$app/navigation";
	import { toast } from "svelte-sonner";
	import { SvelteSet } from "svelte/reactivity";
	import * as Dialog from "$lib/components/ui/dialog";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Checkbox } from "$lib/components/ui/checkbox";
	import SearchIcon from "@lucide/svelte/icons/search";
	import UserPlusIcon from "@lucide/svelte/icons/user-plus";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import { ALL_CAPABILITIES, type Capability, type DirectoryEntry } from "$lib/types";

	const CAP_LABELS: Record<Capability, string> = {
		can_read: "Read",
		can_read_detail: "Read code",
		can_edit: "Edit",
		can_publish: "Publish",
		create_api_key: "API keys",
		add_project: "Add projects",
		can_admin: "Admin",
	};

	let open = $state(false);
	let q = $state("");
	let results = $state<DirectoryEntry[]>([]);
	let searched = $state(false);
	let searching = $state(false);
	// Capabilities granted to whoever is added; seeded to Read (the baseline for an approved
	// user). Applies to every "Add" click while the dialog is open.
	const caps = new SvelteSet<Capability>(["can_read"]);
	// uids added during this dialog session, so their row flips to "Added" without a re-search.
	const added = new SvelteSet<string>();
	let provisioning = $state<string | null>(null);

	function reset() {
		q = "";
		results = [];
		searched = false;
		added.clear();
	}

	function toggle(c: Capability) {
		if (caps.has(c)) caps.delete(c);
		else caps.add(c);
	}
</script>

<Dialog.Root
	bind:open
	onOpenChange={(v) => {
		if (!v) reset();
	}}
>
	<Dialog.Trigger>
		{#snippet child({ props })}
			<Button {...props} size="sm">
				<UserPlusIcon class="size-4" />
				Add user
			</Button>
		{/snippet}
	</Dialog.Trigger>
	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>Add a user from the directory</Dialog.Title>
			<Dialog.Description>
				Search the directory by username or name, then add someone before their first
				login. They are created with the capabilities selected below.
			</Dialog.Description>
		</Dialog.Header>

		<!-- Capabilities the added user will receive. -->
		<div class="flex flex-col gap-2">
			<span class="text-sm font-medium">Grant capabilities</span>
			<span class="text-muted-foreground text-xs">
				Read → Read code → Edit → Publish are incremental: granting one grants everything to
				its left.
			</span>
			<div class="flex flex-wrap gap-x-4 gap-y-2">
				{#each ALL_CAPABILITIES as c (c)}
					<Label class="flex cursor-pointer items-center gap-1.5 text-sm font-normal">
						<Checkbox checked={caps.has(c)} onCheckedChange={() => toggle(c)} />
						{CAP_LABELS[c]}
					</Label>
				{/each}
			</div>
		</div>

		<!-- Directory search. -->
		<form
			method="POST"
			action="?/search"
			class="flex items-center gap-2"
			use:enhance={() => {
				searching = true;
				return async ({ result }) => {
					searching = false;
					searched = true;
					if (result.type === "success") {
						results = (result.data?.results as DirectoryEntry[]) ?? [];
					} else if (result.type === "failure") {
						results = [];
						toast.error(String(result.data?.error ?? "Search failed"));
					}
				};
			}}
		>
			<div class="relative flex-1">
				<SearchIcon
					class="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
				/>
				<Input
					name="q"
					type="search"
					placeholder="Username or name…"
					bind:value={q}
					aria-label="Search directory"
					class="pl-9"
				/>
			</div>
			<Button type="submit" variant="secondary" disabled={!q.trim() || searching}>
				{#if searching}<LoaderIcon class="size-4 animate-spin" />{/if}
				Search
			</Button>
		</form>

		<!-- Results. -->
		<div class="max-h-72 overflow-y-auto rounded-md border">
			{#if !searched}
				<p class="text-muted-foreground p-4 text-center text-sm">
					Search the directory to find a user.
				</p>
			{:else if results.length === 0}
				<p class="text-muted-foreground p-4 text-center text-sm">No directory matches.</p>
			{:else}
				<ul class="divide-y">
					{#each results as entry (entry.ldap_guid)}
						{@const alreadyInDb = entry.user_id !== null || added.has(entry.username)}
						<li class="flex items-center justify-between gap-3 px-3 py-2">
							<div class="flex min-w-0 flex-col">
								<span class="truncate font-medium">
									{entry.display_name ?? entry.username}
								</span>
								<span class="text-muted-foreground font-mono text-xs">{entry.username}</span>
							</div>
							{#if alreadyInDb}
								<span class="text-muted-foreground shrink-0 text-xs">Added</span>
							{:else}
								<form
									method="POST"
									action="?/provision"
									use:enhance={() => {
										provisioning = entry.username;
										return async ({ result }) => {
											provisioning = null;
											if (result.type === "success") {
												added.add(entry.username);
												toast.success(`Added ${entry.username}`);
												await invalidateAll(); // refresh the main user table
											} else if (result.type === "failure") {
												toast.error(String(result.data?.error ?? "Failed to add user"));
											}
										};
									}}
								>
									<input type="hidden" name="username" value={entry.username} />
									<input type="hidden" name="capabilities" value={[...caps].join(",")} />
									<Button
										type="submit"
										size="sm"
										variant="outline"
										disabled={provisioning !== null}
									>
										{#if provisioning === entry.username}
											<LoaderIcon class="size-4 animate-spin" />
										{/if}
										Add
									</Button>
								</form>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</Dialog.Content>
</Dialog.Root>
