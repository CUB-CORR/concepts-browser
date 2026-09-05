<script lang="ts">
	import { enhance } from "$app/forms";
	import { untrack } from "svelte";
	import * as Card from "$lib/components/ui/card";
	import * as Alert from "$lib/components/ui/alert";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Textarea } from "$lib/components/ui/textarea";
	import * as Dialog from "$lib/components/ui/dialog";
	import UserMultiSelect from "$lib/components/UserMultiSelect.svelte";
	import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import CheckIcon from "@lucide/svelte/icons/check";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import type { ActionData, PageData } from "./$types";

	let { form, data }: { form: ActionData; data: PageData } = $props();

	// The creator always leads their own project — pre-select and lock their row.
	const meId = untrack(() => data.user!.id);
	let leadIds = $state<number[]>(untrack(() => form?.values?.lead_ids ?? [meId]));
	let accepted = $state<boolean>(untrack(() => form?.values?.accept_license ?? false));
	let licenseOpen = $state(false);
	let submitting = $state(false);
</script>

<svelte:head><title>New project</title></svelte:head>

<div class="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6">
	<a href="/projects" class="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm">
		<ArrowLeftIcon class="size-4" /> All projects
	</a>

	<div>
		<h1 class="text-2xl font-semibold tracking-tight">New project</h1>
		<p class="text-muted-foreground text-sm">
			A project gates external API access; every query must name an existing project.
		</p>
	</div>

	<Card.Root>
		<form
			method="POST"
			use:enhance={() => {
				submitting = true;
				return async ({ update }) => {
					await update();
					submitting = false;
				};
			}}
		>
			<Card.Content class="flex flex-col gap-4">
				{#if form?.error}
					<Alert.Root variant="destructive">
						<TriangleAlertIcon class="size-4" />
						<Alert.Description>{form.error}</Alert.Description>
					</Alert.Root>
				{/if}

				<div class="flex flex-col gap-1.5">
					<Label for="name">Name</Label>
					<Input id="name" name="name" placeholder="e.g. aki-outcomes-2026" required value={form?.values?.name ?? ""} />
					<p class="text-muted-foreground text-xs">
						Unique and stable — external clients pass this exact name on every query.
					</p>
				</div>

				<div class="flex flex-col gap-1.5">
					<Label for="description">Description</Label>
					<Textarea id="description" name="description" rows={3} value={form?.values?.description ?? ""} />
				</div>

				<div class="flex flex-col gap-1.5">
					<Label for="ea_id">Ethics approval ID</Label>
					<Input id="ea_id" name="ea_id" placeholder="e.g. EA1/234/56" value={form?.values?.ea_id ?? ""} />
					<p class="text-muted-foreground text-xs">Optional — the project's Ethikvotum reference.</p>
				</div>

				<div class="flex flex-col gap-1.5">
					<Label>Lead(s)</Label>
					<UserMultiSelect options={data.userOptions} bind:selected={leadIds} locked={[meId]} />
					<p class="text-muted-foreground text-xs">You lead this project; add others who may also edit it.</p>
				</div>

				<div class="flex flex-col gap-2 rounded-md border p-3">
					<div class="flex items-center justify-between gap-2">
						<Label>CORR license{data.license ? ` (v${data.license.version})` : ""}</Label>
						{#if data.license}
							<Button type="button" variant={accepted ? "outline" : "secondary"} size="sm" onclick={() => (licenseOpen = true)}>
								{accepted ? "View license" : "Read & accept license"}
							</Button>
						{/if}
					</div>
					{#if data.license}
						{#if accepted}
							<p class="text-muted-foreground flex items-center gap-1.5 text-sm">
								<CheckIcon class="size-4 text-emerald-600" />
								Accepted on behalf of this project.
							</p>
							<input type="hidden" name="accept_license" value="on" />
						{:else}
							<p class="text-muted-foreground text-sm">
								You must read and accept the CORR license before creating this project.
							</p>
						{/if}
					{:else}
						<p class="text-destructive text-sm">No CORR license is configured; a project can't be created yet.</p>
					{/if}
				</div>
			</Card.Content>
			<Card.Footer class="mt-2">
				<Button type="submit" disabled={submitting || !accepted || !data.license}>
					{#if submitting}<LoaderIcon class="size-4 animate-spin" />{/if}
					Create project
				</Button>
			</Card.Footer>
		</form>
	</Card.Root>

	{#if data.license}
		<Dialog.Root bind:open={licenseOpen}>
			<Dialog.Content class="flex max-h-[85vh] w-full flex-col gap-4 sm:max-w-3xl">
				<Dialog.Header>
					<Dialog.Title>CORR license (v{data.license.version})</Dialog.Title>
					<Dialog.Description>
						Read the full license below, then accept it on behalf of this project.
					</Dialog.Description>
				</Dialog.Header>
				<pre class="min-h-0 flex-1 overflow-y-auto rounded bg-muted/50 p-4 text-xs leading-relaxed whitespace-pre-wrap">{data.license.body}</pre>
				<Dialog.Footer class="gap-2 sm:justify-between">
					<Dialog.Close>
						{#snippet child({ props })}
							<Button variant="outline" {...props}>{accepted ? "Close" : "Cancel"}</Button>
						{/snippet}
					</Dialog.Close>
					<Button
						onclick={() => {
							accepted = true;
							licenseOpen = false;
						}}
					>
						I have read and accept the CORR license
					</Button>
				</Dialog.Footer>
			</Dialog.Content>
		</Dialog.Root>
	{/if}
</div>
