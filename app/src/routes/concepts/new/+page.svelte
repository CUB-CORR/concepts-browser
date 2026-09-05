<script lang="ts">
	// Adding a name starts with a question the old form never asked: is this a *new* concept, or
	// another name for one that already exists? Getting that wrong is how a vocabulary ends up
	// with two ids meaning one thing — which then has to be undone through a deprecation review.
	import { enhance } from "$app/forms";
	import { untrack } from "svelte";
	import * as Tabs from "$lib/components/ui/tabs";
	import * as Card from "$lib/components/ui/card";
	import * as Select from "$lib/components/ui/select";
	import * as Alert from "$lib/components/ui/alert";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Textarea } from "$lib/components/ui/textarea";
	import ConceptSearchPicker from "$lib/components/ConceptSearchPicker.svelte";
	import NotionImport from "$lib/components/NotionImport.svelte";
	import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import type { ActionData, PageData } from "./$types";
	import type { ConceptSearchResult } from "$lib/types";

	let { form, data }: { form: ActionData; data: PageData } = $props();

	let taxonomy = $state(untrack(() => form?.values?.taxonomy ?? data.taxonomy));
	// The identifier is the one thing both paths need, so it is owned here and survives the
	// switch between them.
	let name = $state(untrack(() => form?.values?.name ?? ""));
	let displayName = $state(untrack(() => form?.values?.display_name ?? ""));
	let existing = $state<ConceptSearchResult | null>(null);
	let submitting = $state(false);

	const taxonomyName = $derived(
		data.taxonomies.find((t) => t.key === taxonomy)?.name ?? taxonomy,
	);

	// Only the "new concept" path carries a description; narrow before echoing it back.
	const echoedDescription = $derived(
		form?.values && "description" in form.values ? (form.values.description ?? "") : "",
	);

	// Set when the API refused the name because it is already live for another concept: the
	// submit below re-sends it confirmed, forming a group on purpose.
	const conflict = $derived(form?.conflict ?? null);

	// Keep what was typed on a refusal: a name conflict is answered by confirming, not by
	// filling the form in again.
	const submit = () => {
		submitting = true;
		return async ({ update }: { update: (opts?: { reset?: boolean }) => Promise<void> }) => {
			await update({ reset: false });
			submitting = false;
		};
	};
</script>

<svelte:head><title>New concept</title></svelte:head>

<div class="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-6">
	<a
		href="/concepts"
		class="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
	>
		<ArrowLeftIcon class="size-4" /> All concepts
	</a>

	<div>
		<h1 class="text-2xl font-semibold tracking-tight">Add a concept</h1>
		<p class="text-muted-foreground text-sm">
			A concept must exist before any source configuration can be added — but a name that means
			something already defined belongs on that concept, not on a second one.
		</p>
	</div>

	{#snippet conflictAlert(action: string)}
		{#if conflict}
			<Alert.Root>
				<TriangleAlertIcon class="size-4" />
				<Alert.Title>
					<span class="font-mono">{conflict.name}</span> already names
					{conflict.members.length === 1 ? "a concept" : `${conflict.members.length} concepts`}
					in {conflict.taxonomy}
				</Alert.Title>
				<Alert.Description>
					<div class="flex flex-col gap-2">
						<span>
							Continuing makes the name point at all of them — a group. If that is not what you
							mean, change the name, or give the existing concept this name as a second one
							under "Alias".
						</span>
						<div class="flex flex-wrap gap-1.5">
							{#each conflict.members as m (m.id)}
								<a href="/concepts/id/{m.id}">
									<Badge variant="outline" class="text-xs">
										<span class="font-mono">#{m.id}</span>
										{#if m.display_name}
											<span class="text-muted-foreground ml-1">{m.display_name}</span>
										{/if}
									</Badge>
								</a>
							{/each}
						</div>
						<div>
							<Button type="submit" formaction={action} name="confirm_group" value="true" size="sm">
								Create the group anyway
							</Button>
						</div>
					</div>
				</Alert.Description>
			</Alert.Root>
		{/if}
	{/snippet}

	{#snippet identifierField(id: string)}
		<div class="flex flex-col gap-1.5">
			<Label for={id}>Name (identifier)</Label>
			<Input {id} name="name" placeholder="e.g. serum_creatinine" class="font-mono" required bind:value={name} />
			<p class="text-muted-foreground text-xs">
				Used in code and URLs — lowercase_snake_case. It need not be unique, but a name shared by
				two concepts is a group and has to be confirmed as one.
			</p>
		</div>
	{/snippet}

	{#snippet taxonomyField()}
		<div class="flex flex-col gap-1.5">
			<Label>Taxonomy</Label>
			<input type="hidden" name="taxonomy" value={taxonomy} />
			<Select.Root type="single" bind:value={taxonomy}>
				<Select.Trigger class="w-full">{taxonomyName}</Select.Trigger>
				<Select.Content>
					{#each data.taxonomies as t (t.key)}
						<Select.Item value={t.key} label={t.name ?? t.key}>
							{t.name ?? t.key}
							<span class="text-muted-foreground ml-2 text-xs">{t.key}</span>
						</Select.Item>
					{/each}
				</Select.Content>
			</Select.Root>
		</div>
	{/snippet}

	<Tabs.Root value="new">
		<Tabs.List>
			<Tabs.Trigger value="new">New concept</Tabs.Trigger>
			<Tabs.Trigger value="existing">Alias</Tabs.Trigger>
			<Tabs.Trigger value="notion">Import from Notion</Tabs.Trigger>
		</Tabs.List>

		<Tabs.Content value="new" class="pt-4">
			<Card.Root>
				<form method="POST" action="?/create" use:enhance={submit}>
					<Card.Content class="flex flex-col gap-4">
						{#if form?.error}
							<Alert.Root variant="destructive">
								<TriangleAlertIcon class="size-4" />
								<Alert.Description>{form.error}</Alert.Description>
							</Alert.Root>
						{/if}
						{@render conflictAlert("?/create")}

						{@render identifierField("name")}

						<div class="flex flex-col gap-1.5">
							<Label for="display_name">Display name</Label>
							<Input
								id="display_name"
								name="display_name"
								placeholder="e.g. Serum Creatinine"
								bind:value={displayName}
							/>
						</div>

						<div class="flex flex-col gap-1.5">
							<Label for="description">Description</Label>
							<Textarea
								id="description"
								name="description"
								rows={3}
								value={echoedDescription}
							/>
						</div>

						{@render taxonomyField()}
					</Card.Content>
					<Card.Footer class="mt-2">
						<Button type="submit" disabled={submitting}>
							{#if submitting}<LoaderIcon class="size-4 animate-spin" />{/if}
							Create concept
						</Button>
					</Card.Footer>
				</form>
			</Card.Root>
		</Tabs.Content>

		<Tabs.Content value="existing" class="pt-4">
			<Card.Root>
				<form method="POST" action="?/addPointer" use:enhance={submit}>
					<Card.Content class="flex flex-col gap-4">
						{#if form?.error}
							<Alert.Root variant="destructive">
								<TriangleAlertIcon class="size-4" />
								<Alert.Description>{form.error}</Alert.Description>
							</Alert.Root>
						{/if}
						{@render conflictAlert("?/addPointer")}

						<div class="flex flex-col gap-1.5">
							<Label>Concept</Label>
							<input type="hidden" name="concept_id" value={existing?.concept_id ?? ""} />
							<ConceptSearchPicker bind:selected={existing} />
							<p class="text-muted-foreground text-xs">
								Gives a concept that already exists a second name. No new concept and no new
								definition — both names resolve to the same one, and retiring either leaves the
								other working. Searches every taxonomy, so find it by whatever it is already
								called.
							</p>
						</div>

						{@render identifierField("pointer-name")}

						<div class="flex flex-col gap-1.5">
							<Label for="pointer-display">Display name</Label>
							<Input
								id="pointer-display"
								name="display_name"
								placeholder="optional, stored on this name"
								bind:value={displayName}
							/>
						</div>

						{@render taxonomyField()}
					</Card.Content>
					<Card.Footer class="mt-2">
						<Button type="submit" disabled={submitting || !existing || !name.trim()}>
							{#if submitting}<LoaderIcon class="size-4 animate-spin" />{/if}
							Add this name to concept {existing ? `#${existing.concept_id}` : ""}
						</Button>
					</Card.Footer>
				</form>
			</Card.Root>
		</Tabs.Content>

		<Tabs.Content value="notion" class="pt-4">
			<Card.Root>
				<Card.Content>
					<NotionImport />
				</Card.Content>
			</Card.Root>
		</Tabs.Content>
	</Tabs.Root>
</div>
