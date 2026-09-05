<script lang="ts">
	// The concepts table. TanStack's table-core drives the column model, the visibility state
	// and the sorting state exactly as the shadcn-svelte data-table recipe does — but with
	// `manualSorting`/`manualPagination` on, because the vocabulary is thousands of names and
	// the row model this component ever holds is one server-sorted page of it. Every header
	// click and page step therefore goes back out to the API (via `onSort`/`onPage`), which is
	// also why the table's state is mirrored in the URL by the page above.
	import {
		type ColumnDef,
		type SortingState,
		type VisibilityState,
		getCoreRowModel,
	} from "@tanstack/table-core";
	import { createSvelteTable, FlexRender, renderSnippet } from "$lib/components/ui/data-table";
	import { goto } from "$app/navigation";
	import * as Table from "$lib/components/ui/table";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { withDate } from "$lib/utils";
	import { formatTimestamp } from "$lib/format";
	import { conceptColumns, cellValue, type ConceptColumnId } from "./concept-table-columns";
	import type { ConceptTableRow } from "$lib/types";
	import ArrowDownIcon from "@lucide/svelte/icons/arrow-down";
	import ArrowUpIcon from "@lucide/svelte/icons/arrow-up";
	import ChevronsUpDownIcon from "@lucide/svelte/icons/chevrons-up-down";
	import LayersIcon from "@lucide/svelte/icons/layers";
	import ArchiveIcon from "@lucide/svelte/icons/archive";
	import LockIcon from "@lucide/svelte/icons/lock";

	let {
		rows,
		taxonomy,
		date,
		sorting,
		visibility,
		onSort,
	}: {
		rows: ConceptTableRow[];
		taxonomy: string;
		/** The active as-of date, carried into every concept link so the lens survives a click. */
		date: string | null;
		sorting: SortingState;
		visibility: VisibilityState;
		/** A header click: the column, and the direction it should now be sorted in. */
		onSort: (id: ConceptColumnId, desc: boolean) => void;
	} = $props();

	const columns = $derived<ColumnDef<ConceptTableRow>[]>(
		conceptColumns.map((spec) => ({
			id: spec.id,
			accessorFn: (row) => cellValue(row, spec.id),
			enableHiding: spec.hideable,
			enableSorting: spec.sortable,
			header: () => renderSnippet(headerCell, spec),
			cell: (ctx) => renderSnippet(bodyCell, { id: spec.id, row: ctx.row.original }),
			meta: { class: spec.class },
		})),
	);

	const table = createSvelteTable({
		get data() {
			return rows;
		},
		get columns() {
			return columns;
		},
		state: {
			get sorting() {
				return sorting;
			},
			get columnVisibility() {
				return visibility;
			},
		},
		// The server already sorted and paged; table-core must not do it again over one page.
		manualSorting: true,
		manualPagination: true,
		manualFiltering: true,
		getCoreRowModel: getCoreRowModel(),
		getRowId: (row) => String(row.pointer_id),
	});

	/** The href a row's name links to, pinned and date-lensed like the old list's rows. */
	function href(row: ConceptTableRow): string {
		const base = `/concepts/tax/${encodeURIComponent(taxonomy)}/${encodeURIComponent(row.name)}`;
		// A retired name still resolves, but the identifier may meanwhile point somewhere else —
		// pin the concept so the link lands on the one this row is about.
		return withDate(row.deprecated_at ? `${base}?cid=${row.id}` : base, date);
	}

	// The whole row is the click target, not just the name in it: the row is *about* one concept,
	// and a table this wide makes a link-sized target at the far left a poor one. The name stays a
	// real `<a>` — that is what keyboard users tab to, what the status bar previews on hover, and
	// what makes middle- and modifier-clicks work without any of this; the row only stands in for
	// it when the pointer lands somewhere that means nothing else.
	function openRow(event: MouseEvent, row: ConceptTableRow) {
		// Anything with a behaviour of its own keeps it, and keeps it *undisturbed* — the name link
		// above all, so a modifier-click on it still means exactly what it means everywhere else.
		const target = event.target as HTMLElement | null;
		if (target?.closest("a, button, input, select, textarea, label, [role='button']")) return;
		// Dragging across a description to copy it is reading, not navigating.
		if (window.getSelection()?.toString()) return;
		const to = href(row);
		// Standing in for the link means answering the modifiers the way the link would.
		if (event.metaKey || event.ctrlKey || event.shiftKey || event.button === 1) {
			window.open(to, "_blank", "noopener");
			return;
		}
		goto(to);
	}

	function sortState(id: string): "asc" | "desc" | null {
		const active = sorting.find((s) => s.id === id);
		return active ? (active.desc ? "desc" : "asc") : null;
	}

	const docTitles: Record<string, string> = {
		S: "Short documentation",
		M: "Medium-length documentation",
		L: "Long documentation",
	};
</script>

{#snippet headerCell(spec: (typeof conceptColumns)[number])}
	{#if spec.sortable}
		{@const active = sortState(spec.id)}
		<Button
			variant="ghost"
			size="sm"
			class="-mx-2 h-7 px-2 font-medium"
			aria-label="Sort by {spec.label}"
			onclick={() =>
				onSort(spec.id, active === null ? spec.firstDir === "desc" : active === "asc")}
		>
			{spec.label}
			{#if active === "asc"}
				<ArrowUpIcon class="size-3.5" />
			{:else if active === "desc"}
				<ArrowDownIcon class="size-3.5" />
			{:else}
				<ChevronsUpDownIcon class="text-muted-foreground/50 size-3.5" />
			{/if}
		</Button>
	{:else}
		{spec.label}
	{/if}
{/snippet}

{#snippet bodyCell({ id, row }: { id: ConceptColumnId; row: ConceptTableRow })}
	{#if id === "name"}
		<div class="flex items-center gap-1.5">
			<!-- Auto-generated (read-only) concepts are italicized to set them apart. -->
			<a
				href={href(row)}
				class="font-mono text-sm font-medium hover:underline"
				class:italic={row.read_only}>{row.name}</a
			>
			{#if row.group_size > 1}
				<Badge
					variant="secondary"
					class="gap-1 text-xs"
					title="This name points at several concepts"
				>
					<LayersIcon class="size-3" /> group of {row.group_size}
				</Badge>
			{/if}
			{#if row.relationship === "alias"}
				<Badge
					variant="outline"
					class="text-muted-foreground text-xs"
					title="Another name of a concept listed elsewhere">alias</Badge
				>
			{/if}
			{#if row.deprecated_at}
				<Badge
					variant="outline"
					class="text-muted-foreground gap-1 text-xs"
					title="This name was retired — it still resolves"
				>
					<ArchiveIcon class="size-3" /> retired
				</Badge>
			{/if}
			{#if row.concept_deprecated_at}
				<Badge
					variant="outline"
					class="text-muted-foreground text-xs"
					title="The concept itself was retired">deprecated</Badge
				>
			{/if}
			<span class="text-muted-foreground font-mono text-[11px]">#{row.id}</span>
		</div>
	{:else if id === "display_name"}
		<span class="text-muted-foreground text-sm">{row.display_name ?? "—"}</span>
	{:else if id === "clinical"}
		<!-- The opening of the clinical documentation, cut to one line by the API. The title
		     attribute repeats it so a truncated cell is still readable on hover. -->
		<p
			class="text-muted-foreground line-clamp-1 max-w-[32rem] min-w-[12rem] text-sm"
			title={row.doc_clinical_excerpt ?? undefined}
		>
			{row.doc_clinical_excerpt ?? "—"}
		</p>
	{:else if id === "description"}
		<p class="text-muted-foreground line-clamp-1 max-w-[24rem] text-sm" title={row.description ?? undefined}>
			{row.description ?? "—"}
		</p>
	{:else if id === "documentation"}
		{#if row.doc_size}
			<Badge variant="secondary" class="font-mono text-xs" title={docTitles[row.doc_size]}>
				{row.doc_size}
			</Badge>
		{:else}
			<span class="text-muted-foreground/60 text-xs">—</span>
		{/if}
	{:else if id === "usage" || id === "mine" || id === "names"}
		<span class="font-mono text-xs tabular-nums">{cellValue(row, id)}</span>
	{:else if id === "sources" || id === "types"}
		{@const values = cellValue(row, id) as string[]}
		{#if values.length}
			<!-- Deliberately not wrapping: the table lays out auto, so a wrapping cell may shrink to
			     one badge wide and stack its badges, making rows with two sources taller than the rest. -->
			<div class="flex flex-row flex-nowrap items-center gap-1">
				{#each values as v (v)}
					<Badge
						variant="outline"
						class={id === "types" ? "text-muted-foreground border-dashed text-xs" : "text-xs"}
						>{v}</Badge
					>
				{/each}
			</div>
		{:else}
			<span class="text-muted-foreground/60 text-xs">—</span>
		{/if}
	{:else if id === "status"}
		{#if row.doc_status}
			<Badge variant="outline" class="text-xs">{row.doc_status}</Badge>
		{:else}
			<span class="text-muted-foreground/60 text-xs">—</span>
		{/if}
	{:else if id === "edited"}
		<span class="text-muted-foreground font-mono text-xs whitespace-nowrap"
			>{formatTimestamp(row.last_edited_at)}</span
		>
	{:else if id === "editor"}
		<span class="text-muted-foreground text-sm">{row.last_edited_by ?? "—"}</span>
	{:else if id === "version"}
		{#if row.read_only}
			<Badge
				variant="outline"
				class="text-muted-foreground gap-1 text-xs"
				title="Auto-generated · not versioned"
			>
				<LockIcon class="size-3" /> auto
			</Badge>
		{:else if row.version != null}
			<Badge variant="secondary" class="font-mono text-xs">v{row.version}</Badge>
		{:else}
			<span class="text-muted-foreground/60 text-xs">—</span>
		{/if}
	{/if}
{/snippet}

<div class="overflow-x-auto rounded-lg border">
	<Table.Root>
		<Table.Header>
			{#each table.getHeaderGroups() as headerGroup (headerGroup.id)}
				<Table.Row>
					{#each headerGroup.headers as header (header.id)}
						<Table.Head
							class={(header.column.columnDef.meta as { class?: string } | undefined)?.class}
							aria-sort={sortState(header.column.id) === "asc"
								? "ascending"
								: sortState(header.column.id) === "desc"
									? "descending"
									: undefined}
						>
							<FlexRender
								content={header.column.columnDef.header}
								context={header.getContext()}
							/>
						</Table.Head>
					{/each}
				</Table.Row>
			{/each}
		</Table.Header>
		<Table.Body>
			{#each table.getRowModel().rows as row (row.id)}
				<Table.Row
					class="cursor-pointer {row.original.deprecated_at || row.original.concept_deprecated_at
						? 'opacity-60'
						: ''}"
					onclick={(e) => openRow(e, row.original)}
					onauxclick={(e) => {
						if (e.button === 1) openRow(e, row.original);
					}}
				>
					{#each row.getVisibleCells() as cell (cell.id)}
						<Table.Cell
							class={(cell.column.columnDef.meta as { class?: string } | undefined)?.class}
						>
							<FlexRender content={cell.column.columnDef.cell} context={cell.getContext()} />
						</Table.Cell>
					{/each}
				</Table.Row>
			{:else}
				<Table.Row>
					<Table.Cell
						colspan={table.getVisibleLeafColumns().length}
						class="text-muted-foreground h-24 text-center text-sm"
					>
						No concepts match the current filters.
					</Table.Cell>
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>
</div>
