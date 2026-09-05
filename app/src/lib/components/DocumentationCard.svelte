<script lang="ts">
	import { enhance } from "$app/forms";
	import * as Card from "$lib/components/ui/card";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Textarea } from "$lib/components/ui/textarea";
	import { cn } from "$lib/utils";
	import { conceptContext } from "$lib/concept-context";
	import FileTextIcon from "@lucide/svelte/icons/file-text";
	import ExternalLinkIcon from "@lucide/svelte/icons/external-link";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LoaderCircleIcon from "@lucide/svelte/icons/loader-circle";
	import PencilIcon from "@lucide/svelte/icons/pencil";
	import type { ConceptDetail } from "$lib/types";

	let {
		concept,
		canEdit,
		canPublish,
	}: { concept: ConceptDetail; canEdit: boolean; canPublish: boolean } = $props();

	const pinnedConcept = conceptContext();

	let editing = $state(false);
	let saving = $state(false);
	let errorMsg = $state<string | null>(null);

	// Common workflow labels → badge tint; anything unrecognized renders neutral. The status
	// is a free-form string in the DB, so this is presentation-only.
	const STATUS_CLASS: Record<string, string> = {
		"in production": "bg-accent-green/25 text-accent-green-fg dark:bg-accent-green/25 dark:text-accent-green-fg-dark",
		done: "bg-accent-green/25 text-accent-green-fg dark:bg-accent-green/25 dark:text-accent-green-fg-dark",
		"in progress": "bg-accent-mango/25 text-accent-mango-fg dark:bg-accent-mango/25 dark:text-accent-mango-fg-dark",
		draft: "bg-accent-mango/25 text-accent-mango-fg dark:bg-accent-mango/25 dark:text-accent-mango-fg-dark",
		review: "bg-blue-200 text-blue-900 dark:bg-blue-900/40 dark:text-blue-200",
		deprecated: "bg-red-200 text-red-900 dark:bg-red-900/40 dark:text-red-200",
	};
	const statusClass = (s: string) =>
		STATUS_CLASS[s.toLowerCase()] ?? "bg-muted text-muted-foreground";

	const hasContent = $derived(
		Boolean(concept.doc_clinical || concept.doc_implementation || concept.doc_caveats),
	);
</script>

<!-- Clinical documentation, stored on the concept itself. Editable in-app; deployments that
     sync from Notion get in-app edits overwritten on the next reimport. -->
<Card.Root class="bg-muted/40">
	<Card.Header>
		<Card.Title class="text-muted-foreground flex items-center gap-2 text-sm font-medium">
			<FileTextIcon class="size-4" /> Documentation
			<span class="ml-auto flex items-center gap-1.5">
				{#if concept.doc_status && !editing}
					<Badge class={cn(statusClass(concept.doc_status))}>{concept.doc_status}</Badge>
				{/if}
				{#if (canEdit || canPublish) && !editing}
					<Button
						variant="ghost"
						size="icon"
						class="size-6"
						title="Edit documentation"
						aria-label="Edit documentation"
						onclick={() => {
							errorMsg = null;
							editing = true;
						}}
					>
						<PencilIcon class="size-3.5" />
					</Button>
				{/if}
			</span>
		</Card.Title>
	</Card.Header>
	<Card.Content class="text-sm">
		{#if editing}
			<form
				method="POST"
				action="?/saveDocumentation"
				class="flex flex-col gap-3"
				use:enhance={() => {
					saving = true;
					errorMsg = null;
					return async ({ result, update }) => {
						saving = false;
						if (result.type === "failure") {
							errorMsg = (result.data as { error?: string })?.error ?? "Saving failed.";
						} else {
							editing = false;
						}
						await update({ reset: false });
					};
				}}
			>
				<input type="hidden" name="cid" value={pinnedConcept.id} />
				{#if canPublish}
					<div class="flex flex-col gap-1.5">
						<Label for="doc-status">Status</Label>
						<Input
							id="doc-status"
							name="status"
							value={concept.doc_status ?? ""}
							placeholder="e.g. In Production"
						/>
					</div>
				{/if}
				{#if canEdit}
					<div class="flex flex-col gap-1.5">
						<Label for="doc-clinical">Clinical description</Label>
						<Textarea id="doc-clinical" name="clinical" rows={4} value={concept.doc_clinical ?? ""} />
					</div>
					<div class="flex flex-col gap-1.5">
						<Label for="doc-implementation">Implementation description</Label>
						<Textarea
							id="doc-implementation"
							name="implementation"
							rows={4}
							value={concept.doc_implementation ?? ""}
						/>
					</div>
					<div class="flex flex-col gap-1.5">
						<Label for="doc-caveats">Known caveats</Label>
						<Textarea id="doc-caveats" name="caveats" rows={3} value={concept.doc_caveats ?? ""} />
					</div>
				{/if}
				{#if errorMsg}
					<p class="text-destructive text-xs">{errorMsg}</p>
				{/if}
				<div class="flex items-center gap-2">
					<Button type="submit" size="sm" disabled={saving}>
						{#if saving}<LoaderCircleIcon class="size-3.5 animate-spin" />{/if}
						Save
					</Button>
					<Button
						type="button"
						variant="ghost"
						size="sm"
						disabled={saving}
						onclick={() => (editing = false)}
					>
						Cancel
					</Button>
				</div>
			</form>
		{:else}
			<div class="flex flex-col gap-3">
				{#if concept.doc_caveats}
					<div
						class="flex gap-1.5 rounded-md border border-accent-mango/40 bg-accent-mango/10 px-2.5 py-2 text-xs text-accent-mango-fg dark:border-accent-mango/50 dark:bg-accent-mango/15 dark:text-accent-mango-fg-dark"
					>
						<TriangleAlertIcon class="mt-0.5 size-3.5 shrink-0" />
						<div><span class="font-medium">Caveats.</span> {concept.doc_caveats}</div>
					</div>
				{/if}

				{#if concept.doc_clinical}
					<div class="flex flex-col gap-0.5">
						<span class="text-muted-foreground text-xs font-medium">Clinical</span>
						<p class="whitespace-pre-line">{concept.doc_clinical}</p>
					</div>
				{/if}

				{#if concept.doc_implementation}
					<div class="flex flex-col gap-0.5">
						<span class="text-muted-foreground text-xs font-medium">Implementation</span>
						<p class="whitespace-pre-line">{concept.doc_implementation}</p>
					</div>
				{/if}

				{#if !hasContent}
					<p class="text-muted-foreground text-xs">
						No documentation yet.{#if canEdit}
							Use the pencil to add some.{/if}
					</p>
				{/if}

				{#if concept.notion_url}
					<div>
						<Button variant="outline" size="sm" href={concept.notion_url} target="_blank">
							Open in Notion <ExternalLinkIcon class="size-3.5" />
						</Button>
					</div>
				{/if}
			</div>
		{/if}
	</Card.Content>
</Card.Root>
