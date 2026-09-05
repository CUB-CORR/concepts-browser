<script lang="ts">
	import * as Table from "$lib/components/ui/table";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { can } from "$lib/caps";
	import { formatTimestamp } from "$lib/format";
	import type { Project, ProjectLead } from "$lib/types";
	import SearchIcon from "@lucide/svelte/icons/search";
	import PlusIcon from "@lucide/svelte/icons/plus";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	let search = $state("");

	const filtered = $derived.by(() => {
		const q = search.trim().toLowerCase();
		if (!q) return data.projects;
		return data.projects.filter((p) => {
			const hay = `${p.name} ${p.description ?? ""} ${leadNames(p.leads)}`.toLowerCase();
			return hay.includes(q);
		});
	});

	function leadNames(leads: ProjectLead[]): string {
		return leads.map((l) => l.display_name ?? l.username).join(", ");
	}

	function statusVariant(p: Project): "secondary" | "outline" {
		return p.status === "completed" ? "secondary" : "outline";
	}
</script>

<svelte:head><title>Projects</title></svelte:head>

<div class="mx-auto flex max-w-5xl flex-col gap-4 px-4 py-6">
	<div class="flex items-center justify-between gap-3">
		<h1 class="text-2xl font-semibold tracking-tight">Projects</h1>
		{#if can(data.user, "add_project")}
			<Button href="/projects/new">
				<PlusIcon class="size-4" /> New project
			</Button>
		{/if}
	</div>

	<div class="relative">
		<SearchIcon
			class="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
		/>
		<Input placeholder="Search projects by name, lead or description…" class="pl-9" bind:value={search} />
	</div>

	{#if filtered.length === 0}
		<div class="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
			{data.projects.length === 0 ? "No projects yet." : "No projects match your search."}
		</div>
	{:else}
		<div class="rounded-lg border">
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>Name</Table.Head>
						<Table.Head>Lead(s)</Table.Head>
						<Table.Head>Status</Table.Head>
						<Table.Head>Created</Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each filtered as p (p.id)}
						<Table.Row
							class="hover:bg-muted/50 cursor-pointer"
							onclick={() => (window.location.href = `/projects/${p.id}`)}
						>
							<Table.Cell class="font-medium">
								<a href={`/projects/${p.id}`} class="hover:underline">{p.name}</a>
								{#if p.description}
									<div class="text-muted-foreground line-clamp-1 text-xs font-normal">
										{p.description}
									</div>
								{/if}
							</Table.Cell>
							<Table.Cell class="text-muted-foreground text-sm">{leadNames(p.leads) || "—"}</Table.Cell>
							<Table.Cell>
								<Badge variant={statusVariant(p)} class="capitalize">{p.status}</Badge>
							</Table.Cell>
							<Table.Cell class="text-muted-foreground text-sm">
								{formatTimestamp(p.created_on)}
							</Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
		</div>
	{/if}
</div>
