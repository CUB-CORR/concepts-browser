<script lang="ts">
	import { enhance } from "$app/forms";
	import { untrack } from "svelte";
	import * as Card from "$lib/components/ui/card";
	import * as Tabs from "$lib/components/ui/tabs";
	import * as Alert from "$lib/components/ui/alert";
	import * as AlertDialog from "$lib/components/ui/alert-dialog";
	import { Badge } from "$lib/components/ui/badge";
	import { Button, buttonVariants } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Textarea } from "$lib/components/ui/textarea";
	import ActivityChart from "$lib/components/ActivityChart.svelte";
	import UsageTable from "$lib/components/UsageTable.svelte";
	import UserMultiSelect from "$lib/components/UserMultiSelect.svelte";
	import StudyContextCard from "$lib/components/StudyContextCard.svelte";
	import { formatTimestamp } from "$lib/format";
	import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import PencilIcon from "@lucide/svelte/icons/pencil";
	import Trash2Icon from "@lucide/svelte/icons/trash-2";
	import CheckIcon from "@lucide/svelte/icons/check";
	import type { ActionData, PageData } from "./$types";

	let { data, form }: { data: PageData; form: ActionData } = $props();

	const p = $derived(data.project);

	let editing = $state(false);
	let name = $state(untrack(() => data.project.name));
	let description = $state(untrack(() => data.project.description ?? ""));
	let eaId = $state(untrack(() => data.project.ea_id ?? ""));
	let leadIds = $state<number[]>(untrack(() => data.project.leads.map((l) => l.id)));

	function startEdit() {
		name = p.name;
		description = p.description ?? "";
		eaId = p.ea_id ?? "";
		leadIds = p.leads.map((l) => l.id);
		editing = true;
	}

	const statusVariant = $derived(
		p.status === "completed" ? "secondary" : p.status === "deleted" ? "destructive" : "outline",
	) as "secondary" | "destructive" | "outline";

	const leadLabel = (l: { username: string; display_name: string | null }) =>
		l.display_name ? `${l.display_name} (${l.username})` : l.username;
</script>

<svelte:head><title>{p.name} · Project</title></svelte:head>

<div class="mx-auto flex max-w-3xl flex-col gap-6 px-4 py-6">
	<a href="/projects" class="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm">
		<ArrowLeftIcon class="size-4" /> All projects
	</a>

	<div class="flex items-start justify-between gap-3">
		<div class="flex flex-col gap-1">
			<div class="flex items-center gap-2">
				<h1 class="text-2xl font-semibold tracking-tight">{p.name}</h1>
				<Badge variant={statusVariant} class="capitalize">{p.status}</Badge>
			</div>
			{#if p.description}<p class="text-muted-foreground text-sm">{p.description}</p>{/if}
		</div>
		{#if p.can_edit && !editing}
			<div class="flex shrink-0 items-center gap-2">
				<Button variant="outline" size="sm" onclick={startEdit}>
					<PencilIcon class="size-4" /> Edit
				</Button>
				<AlertDialog.Root>
					<AlertDialog.Trigger class={buttonVariants({ variant: "outline", size: "sm" })}>
						<Trash2Icon class="size-4" />
					</AlertDialog.Trigger>
					<AlertDialog.Content>
						<AlertDialog.Header>
							<AlertDialog.Title>Delete “{p.name}”?</AlertDialog.Title>
							<AlertDialog.Description>
								The project is soft-deleted: external clients naming it will be rejected. It won't
								appear in the project list. This can be undone in the database if needed.
							</AlertDialog.Description>
						</AlertDialog.Header>
						<AlertDialog.Footer>
							<AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
							<form method="POST" action="?/delete" use:enhance>
								<AlertDialog.Action type="submit" class={buttonVariants({ variant: "destructive" })}>
									Delete project
								</AlertDialog.Action>
							</form>
						</AlertDialog.Footer>
					</AlertDialog.Content>
				</AlertDialog.Root>
			</div>
		{/if}
	</div>

	{#if form?.error}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Description>{form.error}</Alert.Description>
		</Alert.Root>
	{/if}

	<!-- License state: a prominent (re-)approval prompt when out of date and editable. -->
	{#if !p.license_ok}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Description class="flex flex-col gap-3">
				<span>
					{p.license_approval === 0
						? "The CORR license has not been accepted for this project."
						: `This project accepted license v${p.license_approval}, but the current version is v${p.license_current_version}. It must be re-approved.`}
				</span>
				{#if p.can_edit && data.license}
					<pre class="bg-background/60 max-h-40 overflow-y-auto rounded p-3 text-xs whitespace-pre-wrap">{data.license.body}</pre>
					<form method="POST" action="?/approve" use:enhance>
						<Button type="submit" size="sm">
							<CheckIcon class="size-4" /> Accept &amp; approve v{p.license_current_version}
						</Button>
					</form>
				{:else if !p.can_edit}
					<span class="text-xs">Only a project lead can accept the license.</span>
				{/if}
			</Alert.Description>
		</Alert.Root>
	{/if}

	{#if editing}
		<Card.Root>
			<form
				method="POST"
				action="?/update"
				use:enhance={() => async ({ result, update }) => {
					await update();
					if (result.type === "success") editing = false;
				}}
			>
				<Card.Header><Card.Title>Edit project</Card.Title></Card.Header>
				<Card.Content class="flex flex-col gap-4">
					<div class="flex flex-col gap-1.5">
						<Label for="name">Name</Label>
						<Input id="name" name="name" bind:value={name} required />
					</div>
					<div class="flex flex-col gap-1.5">
						<Label for="description">Description</Label>
						<Textarea id="description" name="description" rows={3} bind:value={description} />
					</div>
					<div class="flex flex-col gap-1.5">
						<Label for="ea_id">Ethics approval ID</Label>
						<Input id="ea_id" name="ea_id" bind:value={eaId} placeholder="e.g. EA1/234/56" />
					</div>
					<div class="flex flex-col gap-1.5">
						<Label>Lead(s)</Label>
						<UserMultiSelect options={data.userOptions} bind:selected={leadIds} />
					</div>
				</Card.Content>
				<Card.Footer class="mt-4 gap-2">
					<Button type="submit">Save changes</Button>
					<Button type="button" variant="ghost" onclick={() => (editing = false)}>Cancel</Button>
				</Card.Footer>
			</form>
		</Card.Root>
	{:else}
		<Card.Root>
			<Card.Content class="grid grid-cols-1 gap-4 sm:grid-cols-2">
				<div>
					<div class="text-muted-foreground text-xs">Lead(s)</div>
					<div class="text-sm">{p.leads.map(leadLabel).join(", ") || "—"}</div>
				</div>
				<div>
					<div class="text-muted-foreground text-xs">Ethics approval ID</div>
					<div class="text-sm">{p.ea_id ?? "—"}</div>
				</div>
				<div>
					<div class="text-muted-foreground text-xs">License</div>
					<div class="text-sm">
						{#if p.license_ok}
							Accepted (v{p.license_approval}){#if p.license_approved_on}, {formatTimestamp(p.license_approved_on)}{/if}
						{:else}
							<span class="text-destructive">Not up to date</span>
						{/if}
					</div>
				</div>
				<div>
					<div class="text-muted-foreground text-xs">Created</div>
					<div class="text-sm">{formatTimestamp(p.created_on)}</div>
				</div>
				{#if p.completed_on}
					<div>
						<div class="text-muted-foreground text-xs">Completed</div>
						<div class="text-sm">{formatTimestamp(p.completed_on)}</div>
					</div>
				{/if}
			</Card.Content>
			{#if p.can_edit}
				<Card.Footer>
					<form method="POST" action="?/complete" use:enhance>
						<input type="hidden" name="completed" value={p.status === "completed" ? "false" : "true"} />
						<Button type="submit" variant="outline" size="sm">
							{p.status === "completed" ? "Reopen project" : "Mark completed"}
						</Button>
					</form>
				</Card.Footer>
			{/if}
		</Card.Root>
	{/if}

	<!-- The study the project is: its PICO frame and the people behind it. Hidden while empty
	     unless you may edit the project. -->
	<StudyContextCard project={p} canEdit={p.can_edit} />

	<!-- Request activity from the audit log, per time window. -->
	<Card.Root>
		<Card.Header>
			<Card.Title>API requests</Card.Title>
			<Card.Description>Queries attributed to this project.</Card.Description>
		</Card.Header>
		<Card.Content>
			<Tabs.Root value="day">
				<Tabs.List>
					<Tabs.Trigger value="day">24 hours ({data.activity.last_24h.total})</Tabs.Trigger>
					<Tabs.Trigger value="week">Week ({data.activity.last_week.total})</Tabs.Trigger>
					<Tabs.Trigger value="month">Month ({data.activity.last_month.total})</Tabs.Trigger>
				</Tabs.List>
				<Tabs.Content value="day" class="pt-4">
					<ActivityChart window={data.activity.last_24h} bucket="hour" />
				</Tabs.Content>
				<Tabs.Content value="week" class="pt-4">
					<ActivityChart window={data.activity.last_week} bucket="day" />
				</Tabs.Content>
				<Tabs.Content value="month" class="pt-4">
					<ActivityChart window={data.activity.last_month} bucket="day" />
				</Tabs.Content>
			</Tabs.Root>
		</Card.Content>
	</Card.Root>

	<!-- Which concepts those requests pulled, in which versions. -->
	<Card.Root>
		<Card.Header>
			<Card.Title>Concepts read</Card.Title>
			<Card.Description>
				Concepts read under this project, over its whole history. Reads this app made while
				somebody browsed are not counted.
			</Card.Description>
		</Card.Header>
		<Card.Content>
			{#if data.usage.length}
				<UsageTable concepts={data.usage} />
			{:else}
				<p class="text-muted-foreground text-sm">No concept has been read under this project yet.</p>
			{/if}
		</Card.Content>
	</Card.Root>
</div>
