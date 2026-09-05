<script lang="ts">
	import { enhance } from "$app/forms";
	import { tick, untrack } from "svelte";
	import { toast } from "svelte-sonner";
	import * as Table from "$lib/components/ui/table";
	import { Badge } from "$lib/components/ui/badge";
	import { Checkbox } from "$lib/components/ui/checkbox";
	import { Switch } from "$lib/components/ui/switch";
	import { Label } from "$lib/components/ui/label";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import { CAPABILITY_CHAIN, expandCapabilities, highestChainRank } from "$lib/caps";
	import { ALL_CAPABILITIES, type AdminUser, type Capability } from "$lib/types";

	let { user, isSelf = false }: { user: AdminUser; isSelf?: boolean } = $props();

	const CAP_LABELS: Record<Capability, string> = {
		can_read: "Read",
		can_read_detail: "Read code",
		can_edit: "Edit",
		can_publish: "Publish",
		create_api_key: "API keys",
		add_project: "Add projects",
		can_admin: "Admin",
	};

	// Editable copy of this user's state, seeded once from the prop (the prop catches up when a
	// save reloads the page data). Every toggle posts on its own: there is nothing to hold.
	let caps = $state<Capability[]>(untrack(() => [...user.capabilities]));
	let active = $state(untrack(() => user.is_active));
	let saving = $state(false);
	let form: HTMLFormElement;
	// What to restore when the PATCH is refused — an admin cannot demote or deactivate themselves.
	let previous: { caps: Capability[]; active: boolean } | null = null;

	const isAdmin = $derived(caps.includes("can_admin"));
	const strongest = $derived(highestChainRank(caps));
	const rank = (c: Capability) => (CAPABILITY_CHAIN as readonly string[]).indexOf(c);
	// Which held capability entails `c`, if any — `can_admin` entails every other one, and a chain
	// capability entails the weaker ones to its left. An entailed box is ticked and locked:
	// revoking it on its own would narrow nothing. Null means the box is the admin's to choose.
	const impliedBy = (c: Capability): string | null => {
		if (isAdmin) return c === "can_admin" ? null : CAP_LABELS.can_admin;
		return rank(c) >= 0 && rank(c) < strongest ? CAP_LABELS[CAPABILITY_CHAIN[strongest]] : null;
	};

	// Post the row's form with the new state. `tick()` first so the hidden inputs carry it.
	async function save(next: { caps?: Capability[]; active?: boolean }) {
		previous = { caps, active };
		if (next.caps) caps = next.caps;
		if (next.active !== undefined) active = next.active;
		saving = true;
		await tick();
		form.requestSubmit();
	}

	function toggle(c: Capability) {
		// Store what the admin sees: the display fills in whatever is entailed, so the stored set
		// does too. Ticking Admin (or a stronger chain capability) pulls the implied ones in;
		// unticking it leaves them behind, ticked and free to edit again.
		const base = expandCapabilities(caps);
		save({
			caps: caps.includes(c) ? base.filter((x) => x !== c) : expandCapabilities([...base, c]),
		});
	}
</script>

<Table.Row class={user.capabilities.length === 0 ? "bg-amber-50/50 dark:bg-amber-950/20" : ""}>
	<Table.Cell class="align-top">
		<form
			bind:this={form}
			id="user-form-{user.id}"
			method="POST"
			action="?/update"
			use:enhance={() => {
				return async ({ result, update }) => {
					if (result.type === "success" || result.type === "redirect") {
						await update({ reset: false });
					} else {
						// Refused or unreachable: put the control back where it was and say why.
						if (previous) {
							caps = previous.caps;
							active = previous.active;
						}
						toast.error(
							result.type === "failure"
								? String(result.data?.error ?? "Save failed")
								: `Could not save ${user.username}`,
						);
					}
					previous = null;
					saving = false;
				};
			}}
		>
			<input type="hidden" name="user_id" value={user.id} />
			<input type="hidden" name="capabilities" value={caps.join(",")} />
			<input type="hidden" name="is_active" value={String(active)} />

			<div class="flex flex-col gap-0.5">
				<div class="flex items-center gap-2">
					<a
						href="/users/{encodeURIComponent(user.username)}/profile"
						class="font-medium hover:underline"
					>
						{user.display_name ?? user.username}
					</a>
					<Badge variant={user.is_ldap ? "secondary" : "outline"} class="text-[10px]">
						{user.is_ldap ? "LDAP" : "local"}
					</Badge>
					{#if isSelf}<Badge variant="outline" class="text-[10px]">you</Badge>{/if}
				</div>
				<span class="text-muted-foreground font-mono text-xs">{user.username}</span>
				{#if user.capabilities.length === 0}
					<span class="text-xs font-medium text-amber-700 dark:text-amber-400">
						Pending approval
					</span>
				{/if}
			</div>
		</form>
	</Table.Cell>

	<Table.Cell class="align-top">
		<div
			class="flex flex-wrap gap-x-4 gap-y-2 py-0.5"
			class:pointer-events-none={!active}
			class:opacity-50={!active}
		>
			{#each ALL_CAPABILITIES as c (c)}
				{@const source = impliedBy(c)}
				<Label
					class="flex items-center gap-1.5 text-sm font-normal {source
						? 'text-muted-foreground cursor-default'
						: 'cursor-pointer'}"
					title={source ? `Implied by ${source}` : undefined}
				>
					<Checkbox
						checked={caps.includes(c) || source !== null}
						onCheckedChange={() => toggle(c)}
						disabled={!active || saving || source !== null}
					/>
					{CAP_LABELS[c]}
				</Label>
			{/each}
		</div>
	</Table.Cell>

	<Table.Cell class="text-center align-top">
		<div class="flex items-center justify-center gap-2 py-0.5">
			<Switch
				checked={active}
				onCheckedChange={(v) => save({ active: v })}
				disabled={saving}
				aria-label="Active"
			/>
			<!-- Fixed slot so the in-flight spinner never shifts the switch. -->
			<span class="text-muted-foreground inline-flex size-4 items-center" aria-live="polite">
				{#if saving}<LoaderIcon class="size-4 animate-spin" />{/if}
			</span>
		</div>
	</Table.Cell>
</Table.Row>
