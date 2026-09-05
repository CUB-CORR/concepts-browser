<script lang="ts">
	import ConceptHeader from "$lib/components/ConceptHeader.svelte";
	import ConceptGroupBanner from "$lib/components/ConceptGroupBanner.svelte";
	import SourceTabs from "$lib/components/SourceTabs.svelte";
	import DocumentationCard from "$lib/components/DocumentationCard.svelte";
	import RenameConceptDialog from "$lib/components/RenameConceptDialog.svelte";
	import RequestDeprecationDialog from "$lib/components/RequestDeprecationDialog.svelte";
	import { Button } from "$lib/components/ui/button";
	import { can } from "$lib/caps";
	import { conceptIssueUrl } from "$lib/brand";
	import { withDate } from "$lib/utils";
	import { formatTimestamp } from "$lib/format";
	import { setConceptContext } from "$lib/concept-context";
	import { page } from "$app/state";
	import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
	import ArchiveIcon from "@lucide/svelte/icons/archive";
	import GitBranchIcon from "@lucide/svelte/icons/git-branch";
	import HistoryIcon from "@lucide/svelte/icons/history";
	import MessageSquareWarningIcon from "@lucide/svelte/icons/message-square-warning";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const concept = $derived(data.concept);
	// The name this page was reached by, which is the pointer's — not necessarily the name the
	// id route would present the concept under.
	const taxonomy = $derived(page.params.taxonomy ?? concept.taxonomy ?? "");
	const name = $derived(page.params.name ?? concept.name ?? "");
	const grouped = $derived(data.members.length > 1);
	// Live names other than the one this page was reached by — what decides whether retiring this
	// name would leave the concept reachable, or take it out of circulation with it. `names`
	// includes retired ones, flagged by `deprecated_at`.
	const otherActiveNames = $derived(
		concept.names.filter((n) => !n.deprecated_at && n.id !== data.pointer?.id).length,
	);

	// Every write below addresses the pinned member by id (see concept-context).
	setConceptContext({
		get id() {
			return concept.id;
		},
		get grouped() {
			return grouped;
		},
	});

	// Empty unless the deployment configured an issue-tracker template (see $lib/brand).
	const issueHref = $derived(conceptIssueUrl(taxonomy, name));

	const canEdit = $derived(can(data.user, "can_edit"));
	const canPublish = $derived(can(data.user, "can_publish"));
	// The concept's newest published version (version_no is a per-concept monotonic sequence,
	// so the max across all history rows is the latest overall).
	const latestVersion = $derived(
		data.history.reduce<number | null>(
			(m, r) => (r.version != null && (m == null || r.version > m) ? r.version : m),
			null,
		),
	);
	// Only warn about a pinned version when it isn't already the latest.
	const pinned = $derived(data.selected.v != null && data.selected.v !== latestVersion);

	// "Back to latest" drops the v/draft pin but keeps the ambient source tab, date lens and
	// pinned group member.
	const latestHref = $derived.by(() => {
		const p = new URLSearchParams();
		for (const key of ["source", "date", "cid"]) {
			const value = page.url.searchParams.get(key);
			if (value) p.set(key, value);
		}
		const qs = p.toString();
		return qs ? `?${qs}` : page.url.pathname;
	});
</script>

<svelte:head><title>{name} · {taxonomy}</title></svelte:head>

<div class="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
	<a
		href={withDate("/concepts", page.url.searchParams.get("date"))}
		class="text-muted-foreground hover:text-foreground flex w-fit items-center gap-1 text-sm"
	>
		<ArrowLeftIcon class="size-4" /> All concepts
	</a>

	{#if grouped}
		<ConceptGroupBanner members={data.members} selectedId={concept.id} {taxonomy} {name} />
	{/if}

	<ConceptHeader {concept} {taxonomy} {name} pointer={data.pointer} />

	{#if concept.deprecated_at}
		<div
			class="flex flex-wrap items-center gap-2 rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200"
		>
			<ArchiveIcon class="size-4 shrink-0" />
			<span>
				This concept was <strong>retired</strong> on {formatTimestamp(concept.deprecated_at)}. Its
				names keep resolving and its versions are unchanged, but it takes no new ones.
			</span>
			{#if concept.successor_id != null}
				<Button href="/concepts/id/{concept.successor_id}" variant="outline" size="sm" class="ml-auto h-7">
					Go to concept #{concept.successor_id}
				</Button>
			{/if}
		</div>
	{/if}

	{#if pinned}
		<div
			class="flex items-center gap-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-200"
		>
			<HistoryIcon class="size-4" />
			<span>Viewing <strong>version v{data.selected.v}</strong> (not necessarily the latest).</span>
			<Button href={latestHref} variant="outline" size="sm" class="ml-auto h-7" data-sveltekit-noscroll>
				Back to latest
			</Button>
		</div>
	{:else if data.selected.draft != null}
		<div
			class="flex items-center gap-2 rounded-md border border-blue-300 bg-blue-50 px-3 py-2 text-sm text-blue-900 dark:border-blue-800 dark:bg-blue-950/40 dark:text-blue-200"
		>
			<GitBranchIcon class="size-4" />
			<span>Editing <strong>draft #{data.selected.draft}</strong> — overlaid on the published config.</span>
			<Button href={latestHref} variant="outline" size="sm" class="ml-auto h-7" data-sveltekit-noscroll>
				Done editing
			</Button>
		</div>
	{/if}

	<div class="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
		<div class="min-w-0">
			<SourceTabs
				{concept}
				{taxonomy}
				{name}
				history={data.history}
				drafts={data.drafts}
				schemas={data.schemas}
				sources={data.sources}
				selectedVersion={data.selected.v}
				activeDraftId={data.selected.draft}
				initialSource={data.activeSource}
				{canEdit}
				{canPublish}
			/>
		</div>
		<div class="flex flex-col gap-4">
			<DocumentationCard concept={data.concept} {canEdit} {canPublish} />
			{#if (canEdit && !concept.deprecated_at) || issueHref}
				<div class="flex flex-col gap-2">
					{#if canEdit && !concept.deprecated_at}
						<RenameConceptDialog {taxonomy} {name} pointerId={data.pointer?.id ?? null} />
						<RequestDeprecationDialog
							{name}
							pointerId={data.pointer?.id ?? null}
							otherNames={otherActiveNames}
						/>
					{/if}
					{#if issueHref}
						<Button
							href={issueHref}
							target="_blank"
							rel="noopener"
							variant="outline"
							size="sm"
							class="w-full"
						>
							<MessageSquareWarningIcon class="size-4" /> Report issue
						</Button>
					{/if}
				</div>
			{/if}
		</div>
	</div>
</div>
