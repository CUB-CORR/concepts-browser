<script lang="ts">
	import * as Table from "$lib/components/ui/table";
	import { Input } from "$lib/components/ui/input";
	import UserManagementRow from "$lib/components/UserManagementRow.svelte";
	import AddUserDialog from "$lib/components/AddUserDialog.svelte";
	import SearchIcon from "@lucide/svelte/icons/search";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	let query = $state("");

	const filtered = $derived(
		query.trim()
			? data.users.filter((u) =>
					[u.username, u.display_name].some((field) =>
						field?.toLowerCase().includes(query.trim().toLowerCase()),
					),
				)
			: data.users,
	);
</script>

<svelte:head><title>User management</title></svelte:head>

<div class="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6">
	<div class="flex items-start justify-between gap-4">
		<h1 class="text-2xl font-semibold tracking-tight">User management</h1>
		<AddUserDialog />
	</div>

	<div class="relative w-full max-w-xs">
		<SearchIcon
			class="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
		/>
		<Input
			type="search"
			placeholder="Search by username…"
			bind:value={query}
			aria-label="Search users by username"
			class="pl-9"
		/>
	</div>

	<div class="rounded-lg border">
		<Table.Root>
			<Table.Header>
				<Table.Row>
					<Table.Head>User</Table.Head>
					<Table.Head>Capabilities</Table.Head>
					<Table.Head class="w-28 text-center">Active</Table.Head>
				</Table.Row>
			</Table.Header>
			<Table.Body>
				{#each filtered as user (user.id)}
					<UserManagementRow {user} isSelf={user.id === data.user?.id} />
				{:else}
					<Table.Row>
						<Table.Cell colspan={3} class="text-muted-foreground py-8 text-center text-sm">
							No users match “{query}”.
						</Table.Cell>
					</Table.Row>
				{/each}
			</Table.Body>
		</Table.Root>
	</div>
</div>
