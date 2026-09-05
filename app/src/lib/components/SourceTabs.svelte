<script lang="ts">
	import * as Tabs from "$lib/components/ui/tabs";
	import * as Select from "$lib/components/ui/select";
	import { Button } from "$lib/components/ui/button";
	import { Label } from "$lib/components/ui/label";
	import SourcePanel from "$lib/components/SourcePanel.svelte";
	import DraftEditor from "$lib/components/DraftEditor.svelte";
	import VersionHistory from "$lib/components/VersionHistory.svelte";
	import { enhance } from "$app/forms";
	import { replaceState } from "$app/navigation";
	import { page } from "$app/state";
	import { conceptContext } from "$lib/concept-context";
	import DatabaseIcon from "@lucide/svelte/icons/database";
	import PlusIcon from "@lucide/svelte/icons/plus";
	import type { ConceptDetail, Draft, HistoryRow, SchemaIndex, Source } from "$lib/types";

	let {
		concept,
		taxonomy,
		name,
		history,
		drafts,
		schemas,
		sources,
		selectedVersion,
		activeDraftId,
		initialSource,
		canEdit,
		canPublish,
	}: {
		concept: ConceptDetail;
		/** The name this page was reached by — the pointer's, not the concept's own. */
		taxonomy: string;
		name: string;
		history: HistoryRow[];
		drafts: Draft[];
		schemas: SchemaIndex;
		sources: Source[];
		selectedVersion: number | null;
		activeDraftId: number | null;
		initialSource: string | null;
		canEdit: boolean;
		canPublish: boolean;
	} = $props();

	const pinnedConcept = conceptContext();

	// `canEdit` alone decides whether the editor opens. Authoring also needs the snippet to
	// be *shown* — an editor handed a null `py` (flagged `py_locked`) would either see an
	// empty snippet or save one over the real code — but `can_edit` entails `can_read_detail`
	// (see `$lib/caps`), so an editor is never in that position.

	const ADD = "__add__";
	const publishedKeys = $derived(Object.keys(concept.sources));
	// A source whose only definition is an open draft has nothing published to render, but the
	// draft is still that source's work: `concept.sources` alone would give it no tab, and it
	// would be reachable only for as long as `?draft=` pins it — so never again once the editor
	// is closed. The drafts list is the other half of what this concept has per source.
	const draftKeys = $derived([...new Set(drafts.map((d) => d.source).filter((k) => k !== null))]);
	const sourceKeys = $derived(
		[...publishedKeys, ...draftKeys.filter((k) => !publishedKeys.includes(k))].sort(),
	);
	const unconfigured = $derived(sources.filter((s) => !sourceKeys.includes(s.key)));
	const firstSource = $derived(
		initialSource && sourceKeys.includes(initialSource) ? initialSource : (sourceKeys[0] ?? ADD),
	);

	let active = $state("");
	// A load that names a source — the redirect after creating, publishing or discarding a draft
	// — has to win over the tab last clicked, which lives only in `active`. Clicking a tab
	// rewrites the URL without re-running `load`, so `initialSource` doesn't move and the two
	// never fight over it.
	let named: string | null | undefined = undefined;
	$effect(() => {
		if (initialSource !== named) {
			named = initialSource;
			if (initialSource && sourceKeys.includes(initialSource)) active = initialSource;
		}
		if (!active || (active !== ADD && !sourceKeys.includes(active))) active = firstSource;
	});

	function select(next: string) {
		active = next;
		const url = new URL(page.url);
		url.searchParams.set("source", next);
		replaceState(url, page.state);
	}

	const historyFor = (src: string) => history.filter((h) => h.source === src);
	const draftsFor = (src: string) => drafts.filter((d) => d.source === src);
	// Auto-generated (medication/laboratory) configs are read-only: no drafts, no editing,
	// even for users who can otherwise edit.
	const isReadOnly = (src: string) => concept.sources[src]?.version_info.read_only ?? false;
	const activeDraft = $derived(
		activeDraftId != null ? (drafts.find((d) => d.id === activeDraftId) ?? null) : null,
	);
	const draftSchema = (type: string, src: string) => schemas[src]?.[type] ?? null;

	// --- "+ add source" tab state ---
	let newSource = $state("");
	let newType = $state("");
	const newSourceMeta = $derived(sources.find((s) => s.key === newSource));
</script>

{#if sourceKeys.length === 0 && !canEdit}
	<div class="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
		<DatabaseIcon class="mx-auto mb-2 size-6 opacity-60" />
		No sources are configured for this concept yet.
	</div>
{:else}
	<Tabs.Root value={active} onValueChange={select}>
		<Tabs.List>
			{#each sourceKeys as src (src)}
				<Tabs.Trigger value={src} class="font-mono">{src}</Tabs.Trigger>
			{/each}
			{#if canEdit && unconfigured.length}
				<Tabs.Trigger value={ADD}><PlusIcon class="size-3.5" /> add source</Tabs.Trigger>
			{/if}
		</Tabs.List>

		{#each sourceKeys as src (src)}
			<Tabs.Content value={src} class="flex flex-col gap-5 pt-4">
				{#if canEdit && !isReadOnly(src) && activeDraft && initialSource === src}
					<!-- Authoring: editing an open draft for this source -->
					<DraftEditor
						{name}
						source={src}
						draft={activeDraft}
						schema={draftSchema(activeDraft.type, src)}
						files={concept.sources[src]?.files ?? []}
						{canPublish}
					/>
					<VersionHistory {taxonomy} {name} source={src}
						rows={historyFor(src)} drafts={draftsFor(src)} {selectedVersion} {activeDraftId}
						canDelete={canEdit} />
				{:else if !concept.sources[src]}
					<!-- Draft-only: nothing is published for this source, so there is no config to
					     show — the history block is where the open draft is picked up again. -->
					<p class="text-muted-foreground text-sm">
						Nothing is published for <span class="font-mono">{src}</span> yet — this source has only
						the open draft below.
					</p>
					<VersionHistory {taxonomy} {name} source={src}
						rows={historyFor(src)} drafts={draftsFor(src)} {selectedVersion} {activeDraftId}
						canDelete={canEdit} />
				{:else}
					<SourcePanel
						{taxonomy}
						{name}
						source={src}
						config={concept.sources[src]}
						schema={draftSchema(concept.sources[src].version_info.type, src)}
						history={historyFor(src)}
						drafts={draftsFor(src)}
						{selectedVersion}
						{activeDraftId}
						{canEdit}
						readOnly={isReadOnly(src)}
					/>
					{#if canEdit && !isReadOnly(src)}
						<form method="POST" action="?/createDraft" use:enhance>
							<input type="hidden" name="cid" value={pinnedConcept.id} />
							<input type="hidden" name="source" value={src} />
							<input type="hidden" name="empty" value="false" />
							<Button type="submit" variant="default">
								<PlusIcon class="size-4" /> New draft from v{concept.sources[src].version_info.source_version}
							</Button>
						</form>
					{/if}
				{/if}
			</Tabs.Content>
		{/each}

		{#if canEdit && unconfigured.length}
			<Tabs.Content value={ADD} class="flex flex-col gap-4 pt-4">
				<!-- Only sources this concept has nothing for at all: once a draft exists the source
				     has a tab of its own, which is where the draft is edited. -->
				<p class="text-muted-foreground text-sm">
					Configure a source this concept doesn't have yet. Pick the source and a type to start a
					fresh definition.
				</p>
				<div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
					<div class="flex flex-col gap-1.5">
						<Label class="text-xs">Source</Label>
						<Select.Root type="single" bind:value={newSource} onValueChange={() => (newType = "")}>
							<Select.Trigger class="w-full">{newSource || "Select source…"}</Select.Trigger>
							<Select.Content>
								{#each unconfigured as s (s.key)}
									<Select.Item value={s.key}>{s.key}</Select.Item>
								{/each}
							</Select.Content>
						</Select.Root>
					</div>
					<div class="flex flex-col gap-1.5">
						<Label class="text-xs">Type</Label>
						<Select.Root type="single" bind:value={newType} disabled={!newSourceMeta?.supported_types?.length}>
							<Select.Trigger class="w-full">
								{newType || (newSourceMeta?.supported_types?.length ? "Select type…" : "no schema types")}
							</Select.Trigger>
							<Select.Content>
								{#each newSourceMeta?.supported_types ?? [] as t (t)}
									<Select.Item value={t}>{t}</Select.Item>
								{/each}
							</Select.Content>
						</Select.Root>
					</div>
				</div>
				{#if newSource && (newType || !newSourceMeta?.schema_governed)}
					<!-- Compose-then-create: edit a skeleton, create only what validates -->
					<DraftEditor
						{name}
						source={newSource}
						type={newType || "config"}
						schema={newType ? (schemas[newSource]?.[newType] ?? null) : null}
						{canPublish}
					/>
				{/if}
			</Tabs.Content>
		{/if}
	</Tabs.Root>
{/if}
