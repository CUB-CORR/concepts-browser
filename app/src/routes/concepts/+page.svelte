<script lang="ts">
	import ConceptTable from "$lib/components/ConceptTable.svelte";
	import ExportDialog from "$lib/components/ExportDialog.svelte";
	import { Input } from "$lib/components/ui/input";
	import { Button } from "$lib/components/ui/button";
	import { Badge } from "$lib/components/ui/badge";
	import { Label } from "$lib/components/ui/label";
	import { Switch } from "$lib/components/ui/switch";
	import { Separator } from "$lib/components/ui/separator";
	import * as DropdownMenu from "$lib/components/ui/dropdown-menu";
	import * as Select from "$lib/components/ui/select";
	import { can } from "$lib/caps";
	import { untrack } from "svelte";
	import { pushState, replaceState } from "$app/navigation";
	import { page } from "$app/state";
	import {
		conceptColumns,
		visibilityFromParam,
		visibilityToParam,
		type ConceptColumnId,
	} from "$lib/components/concept-table-columns";
	import type { ConceptTablePage, ConceptTableRow } from "$lib/types";
	import type { SortingState } from "@tanstack/table-core";
	import SearchIcon from "@lucide/svelte/icons/search";
	import PlusIcon from "@lucide/svelte/icons/plus";
	import Settings2Icon from "@lucide/svelte/icons/settings-2";
	import FilterIcon from "@lucide/svelte/icons/filter";
	import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import ClockIcon from "@lucide/svelte/icons/clock";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	const taxonomyName = $derived(
		data.taxonomies.find((t) => t.key === data.taxonomy)?.name ?? data.taxonomy,
	);

	// --- the query string -------------------------------------------------------------------
	// The URL *is* the table's state, but it cannot be read back off `page.url`. Shallow routing
	// deliberately leaves `page.url` on the last URL `load` ran for: `pushState`/`replaceState`
	// write the history entry and `page.state`, and nothing else. So every control here reads
	// the query string this component keeps instead — seeded from the URL the page was rendered
	// for, advanced by `navigate`, and re-seeded whenever a real navigation lands a new payload.
	// `page.url` still has its job, which is to say what a *real* navigation (taxonomy, date)
	// means.
	let query = $state(untrack(() => page.url.search));
	const params = $derived(new URLSearchParams(query));

	// --- what is on screen ----------------------------------------------------------------
	// The rows are *accumulated*: the server renders the first slice, and scrolling to the
	// bottom appends the next. That only works because the API's sort ends in (identifier, id),
	// a unique pair — so slice N+1 continues slice N instead of resampling a shuffled order.
	let rows = $state<ConceptTableRow[]>(untrack(() => data.table.rows));
	// Totals, facet counts, export ids and the degraded-columns note — everything around the
	// rows that a new slice of *page 1* replaces and an appended slice leaves alone.
	let meta = $state<ConceptTablePage>(untrack(() => data.table));
	/** The URL query string the rows currently answer. */
	let shownFor = $state(untrack(() => data.query));
	let nextSlice = $state(2);
	let searching = $state(false);
	let loadingMore = $state(false);
	let failed = $state<string | null>(null);

	/** The last server-rendered payload that was taken as the truth, so it is taken only once. */
	let adopted: ConceptTablePage | null = untrack(() => data.table);
	let searchRequest: AbortController | null = null;
	let moreRequest: AbortController | null = null;

	const exhausted = $derived(rows.length >= meta.total);

	function adopt(payload: ConceptTablePage, search: string) {
		rows = payload.rows;
		meta = payload;
		query = search;
		shownFor = search;
		nextSlice = 2;
		failed = null;
	}

	/** The part of a query string the server cares about — everything but the column choice,
	 *  which is drawn entirely in the browser and must not cost a round trip. */
	function serverKey(search: string): string {
		const asked = new URLSearchParams(search);
		asked.delete("cols");
		const entries = [...asked.entries()].sort(([a, x], [b, y]) =>
			a === b ? x.localeCompare(y) : a.localeCompare(b),
		);
		return entries.map(([k, v]) => `${k}=${v}`).join("&");
	}

	function sliceUrl(search: string, slice: number): string {
		const url = new URL("/concepts/table", location.origin);
		url.search = search;
		url.searchParams.set("page", String(slice));
		return url.pathname + url.search;
	}

	function aborted(err: unknown): boolean {
		return err instanceof DOMException && err.name === "AbortError";
	}

	/** Fetch the first slice for a query and swap the whole table over to it. */
	async function refresh(search: string) {
		// A newer request supersedes both the older search and any append it had started: the
		// rows those would land in no longer exist.
		searchRequest?.abort();
		moreRequest?.abort();
		const request = new AbortController();
		searchRequest = request;
		searching = true;
		try {
			const res = await fetch(sliceUrl(search, 1), { signal: request.signal });
			if (!res.ok) throw new Error(`The table could not be loaded (${res.status}).`);
			const payload: ConceptTablePage = await res.json();
			adopt(payload, search);
		} catch (err) {
			if (!aborted(err)) failed = err instanceof Error ? err.message : String(err);
		} finally {
			if (searchRequest === request) {
				searchRequest = null;
				searching = false;
			}
		}
	}

	/** Fetch the slice after the last one on screen and append it. */
	async function loadMore() {
		if (loadingMore || searching || exhausted || searchRequest) return;
		const request = new AbortController();
		moreRequest = request;
		loadingMore = true;
		const slice = nextSlice;
		const search = shownFor;
		try {
			const res = await fetch(sliceUrl(search, slice), { signal: request.signal });
			if (!res.ok) throw new Error(`More rows could not be loaded (${res.status}).`);
			const payload: ConceptTablePage = await res.json();
			// The filters may have moved while this was in flight; a slice of the old query
			// must not be appended to the new one.
			if (search !== shownFor) return;
			const seen = new Set(rows.map((r) => r.pointer_id));
			rows = [...rows, ...payload.rows.filter((r) => !seen.has(r.pointer_id))];
			meta = { ...meta, total: payload.total, pages: payload.pages };
			nextSlice = slice + 1;
		} catch (err) {
			if (!aborted(err)) failed = err instanceof Error ? err.message : String(err);
		} finally {
			if (moreRequest === request) {
				moreRequest = null;
				loadingMore = false;
			}
		}
	}

	// A server-rendered payload — the first visit, or a real navigation (taxonomy, date) — is
	// always the truth about what the URL means, and is taken exactly once.
	$effect(() => {
		const payload = data.table;
		const search = data.query;
		untrack(() => {
			if (payload === adopted) return;
			adopted = payload;
			searchRequest?.abort();
			moreRequest?.abort();
			adopt(payload, search);
		});
	});

	// Everything a control does is a query change (see `navigate`), so this is the one place a
	// fetch is triggered from — and the only thing that has to hold is that the rows on screen
	// answer `query`.
	$effect(() => {
		const search = query;
		untrack(() => {
			if (search === shownFor) return;
			// A navigation whose payload has not arrived yet — the effect above will take it.
			if (search === data.query && data.table !== adopted) return;
			// Column visibility rides in the URL but is drawn from rows already here.
			if (serverKey(search) === serverKey(shownFor)) {
				shownFor = search;
				return;
			}
			refresh(search);
		});
	});

	// Back and forward move the address bar without re-running `load` — the entries `navigate`
	// pushed are shallow — so the query is read back off the browser and the effect above turns
	// it into rows. A step that crosses a real navigation re-runs `load` too, and the payload it
	// lands supersedes whatever this started.
	function onPopState() {
		query = location.search;
	}

	// --- moving the URL -------------------------------------------------------------------------
	// A view is shareable because the URL carries it, so every control writes there. It is
	// written shallowly: `load` does not re-run, because the rows are fetched from
	// `/concepts/table` directly — a full navigation would re-render the page around a table
	// that only needed new rows, which is what made typing in the search box feel heavy.
	// Discrete choices push a history entry; typing replaces one, so back does not walk the
	// search box letter by letter.
	function navigate(mutate: (p: URLSearchParams) => void, { replace = false } = {}) {
		const url = new URL(page.url);
		url.search = query;
		mutate(url.searchParams);
		// A scroll position is not shareable state, so nothing here carries a page number.
		url.searchParams.delete("page");
		if (url.search === query) return;
		if (replace) replaceState(url, page.state);
		else pushState(url, page.state);
		query = url.search;
	}

	function setParam(key: string, value: string | null, opts?: { replace?: boolean }) {
		navigate((p) => (value === null || value === "" ? p.delete(key) : p.set(key, value)), opts);
	}

	// --- search -------------------------------------------------------------------------------
	// Debounced, because the search reaches into the documentation text of every concept and so
	// is a round trip, not a keystroke-cheap client-side filter — but a short one, and each
	// keystroke aborts the request the one before it started, so what lands is always the
	// answer to what is in the box.
	const SEARCH_DEBOUNCE_MS = 180;
	let searchBox = $state(untrack(() => data.q));
	let searchTimer: ReturnType<typeof setTimeout> | undefined;
	$effect(() => {
		// Follow the URL when navigation (back/forward, a cleared filter) changes it.
		const fromUrl = params.get("q") ?? "";
		untrack(() => {
			if (searchTimer === undefined) searchBox = fromUrl;
		});
	});
	function onSearchInput(value: string) {
		searchBox = value;
		clearTimeout(searchTimer);
		searchTimer = setTimeout(() => {
			searchTimer = undefined;
			setParam("q", value || null, { replace: true });
		}, SEARCH_DEBOUNCE_MS);
	}

	// --- sorting ------------------------------------------------------------------------------
	// With no `sort` in the URL the server picks: relevance while searching, most-used-first
	// otherwise. The header arrows show that choice without writing it into the URL.
	const activeSort = $derived(params.get("sort") ?? (params.get("q") ? null : "usage"));
	const sorting = $derived<SortingState>(
		activeSort ? [{ id: activeSort, desc: params.get("dir") !== "asc" }] : [],
	);

	function onSort(id: ConceptColumnId, desc: boolean) {
		navigate((p) => {
			p.set("sort", id);
			p.set("dir", desc ? "desc" : "asc");
		});
	}

	// --- column visibility --------------------------------------------------------------------
	const visibility = $derived(visibilityFromParam(params.get("cols")));

	function toggleColumn(id: ConceptColumnId, show: boolean) {
		setParam("cols", visibilityToParam({ ...visibility, [id]: show }));
	}

	// --- facet filters ------------------------------------------------------------------------
	const statusFilter = $derived(params.getAll("status"));
	const sourceFilter = $derived(params.getAll("source"));
	const typeFilter = $derived(params.getAll("type"));
	const configured = $derived(params.get("configured") ?? "all");
	const includeDeprecated = $derived(params.get("include_deprecated") === "true");
	const searchTerm = $derived(params.get("q") ?? "");

	function toggleFacet(key: string, value: string, on: boolean) {
		navigate((p) => {
			const kept = p.getAll(key).filter((v) => v !== value);
			p.delete(key);
			for (const v of on ? [...kept, value] : kept) p.append(key, v);
		});
	}

	const configuredLabels: Record<string, string> = {
		all: "All concepts",
		configured: "Configured only",
		unconfigured: "Unconfigured only",
	};

	const activeFilters = $derived(
		statusFilter.length +
			sourceFilter.length +
			typeFilter.length +
			(configured !== "all" ? 1 : 0),
	);

	function clearFilters() {
		clearTimeout(searchTimer);
		searchTimer = undefined;
		searchBox = "";
		navigate((p) => {
			for (const key of ["status", "source", "type", "configured", "q"]) p.delete(key);
		});
	}

	// Retired names are a server-side lens (the API only sends them on request), so the toggle
	// lives in the URL like the date filter rather than in client-side filter state.
	function toggleDeprecated(next: boolean) {
		setParam("include_deprecated", next ? "true" : null);
	}

	const date = $derived(params.get("date"));

	// The unfiltered export is sent as "everything in the taxonomy" (ids = null) rather than as
	// a list, so it stays correct even if the page is stale; a filtered one takes the ids the
	// server matched across *all* pages, not just the rows scrolled to.
	const isFiltered = $derived(activeFilters > 0 || searchTerm !== "");
	const exportIds = $derived(isFiltered ? (meta.ids ?? []) : null);

	// --- infinite scroll -------------------------------------------------------------------
	// A sentinel below the last row, watched a screen ahead of itself so the next slice is
	// usually already in when the reader gets there.
	let sentinel = $state<HTMLElement | null>(null);
	$effect(() => {
		const node = sentinel;
		// Rebuilt whenever rows are appended. An observer only reports a *change* of
		// intersection, so a sentinel that was already visible and stayed visible — a short
		// slice on a tall screen — would never ask for the slice after it; a fresh observer
		// reports the state it starts in and the list keeps filling until it reaches past the
		// fold.
		rows.length;
		if (!node) return;
		const observer = new IntersectionObserver(
			(entries) => {
				if (entries.some((e) => e.isIntersecting)) loadMore();
			},
			{ rootMargin: "800px 0px" },
		);
		observer.observe(node);
		return () => observer.disconnect();
	});

	// --- narrow screens ----------------------------------------------------------------------
	// The sidebar needs room the table also needs, so below `lg` (1024px) it collapses into a
	// disclosure above the table: at that width a 16rem column plus a table wide enough to read
	// does not fit, and hiding the controls entirely would put the filters out of reach.
	let filtersOpen = $state(false);
</script>

<svelte:head><title>Concepts · {taxonomyName}</title></svelte:head>
<svelte:window onpopstate={onPopState} />

{#snippet searchField(scope: string)}
	<div class="relative">
		<SearchIcon
			class="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
		/>
		<Input
			id="concept-search-{scope}"
			placeholder="Search names and documentation…"
			class="pr-9 pl-9"
			value={searchBox}
			oninput={(e) => onSearchInput(e.currentTarget.value)}
		/>
		{#if searching}
			<LoaderIcon
				class="text-muted-foreground pointer-events-none absolute top-1/2 right-3 size-4 -translate-y-1/2 animate-spin"
			/>
		{/if}
	</div>
{/snippet}

{#snippet sectionLabel(text: string)}
	<span class="text-muted-foreground text-xs font-medium tracking-wide uppercase">{text}</span>
{/snippet}

{#snippet controls(scope: string)}
	<div class="flex flex-col gap-4">
		{@render searchField(scope)}

		<div class="flex flex-col gap-1.5">
			{@render sectionLabel("Filters")}

			<!-- Status facet -->
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<Button variant="outline" class="w-full justify-start" {...props}>
							<FilterIcon class="size-4" /> Status
							{#if statusFilter.length}
								<Badge variant="secondary" class="ml-auto text-xs">{statusFilter.length}</Badge>
							{/if}
						</Button>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="start" class="max-h-80 w-56 overflow-y-auto">
					<DropdownMenu.Label>Documentation status</DropdownMenu.Label>
					<DropdownMenu.Separator />
					{#each meta.statuses as facet (facet.value)}
						<DropdownMenu.CheckboxItem
							checked={statusFilter.includes(facet.value)}
							onCheckedChange={(on) => toggleFacet("status", facet.value, on)}
							closeOnSelect={false}
						>
							<span class="flex-1 truncate">{facet.value}</span>
							<span class="text-muted-foreground font-mono text-xs">{facet.count}</span>
						</DropdownMenu.CheckboxItem>
					{:else}
						<DropdownMenu.Item disabled>No statuses in this taxonomy</DropdownMenu.Item>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>

			<!-- Source facet -->
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<Button variant="outline" class="w-full justify-start" {...props}>
							<FilterIcon class="size-4" /> Sources
							{#if sourceFilter.length}
								<Badge variant="secondary" class="ml-auto text-xs">{sourceFilter.length}</Badge>
							{/if}
						</Button>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="start" class="max-h-80 w-60 overflow-y-auto">
					<DropdownMenu.Label>Sources</DropdownMenu.Label>
					<DropdownMenu.Separator />
					{#each meta.sources as facet (facet.value)}
						<DropdownMenu.CheckboxItem
							checked={sourceFilter.includes(facet.value)}
							onCheckedChange={(on) => toggleFacet("source", facet.value, on)}
							closeOnSelect={false}
						>
							<span class="flex-1 truncate">{facet.value}</span>
							<span class="text-muted-foreground font-mono text-xs">{facet.count}</span>
						</DropdownMenu.CheckboxItem>
					{:else}
						<DropdownMenu.Item disabled>Nothing is configured here</DropdownMenu.Item>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>

			<!-- Type facet -->
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<Button variant="outline" class="w-full justify-start" {...props}>
							<FilterIcon class="size-4" /> Types
							{#if typeFilter.length}
								<Badge variant="secondary" class="ml-auto text-xs">{typeFilter.length}</Badge>
							{/if}
						</Button>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="start" class="max-h-80 w-60 overflow-y-auto">
					<DropdownMenu.Label>Config types</DropdownMenu.Label>
					<DropdownMenu.Separator />
					{#each meta.types as facet (facet.value)}
						<DropdownMenu.CheckboxItem
							checked={typeFilter.includes(facet.value)}
							onCheckedChange={(on) => toggleFacet("type", facet.value, on)}
							closeOnSelect={false}
						>
							<span class="flex-1 truncate">{facet.value}</span>
							<span class="text-muted-foreground font-mono text-xs">{facet.count}</span>
						</DropdownMenu.CheckboxItem>
					{:else}
						<DropdownMenu.Item disabled>Nothing is configured here</DropdownMenu.Item>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>

			<Select.Root
				type="single"
				value={configured}
				onValueChange={(v) => setParam("configured", v === "all" ? null : v)}
			>
				<Select.Trigger class="w-full">{configuredLabels[configured]}</Select.Trigger>
				<Select.Content>
					<Select.Item value="all">All concepts</Select.Item>
					<Select.Item value="configured">Configured only</Select.Item>
					<Select.Item value="unconfigured">Unconfigured only</Select.Item>
				</Select.Content>
			</Select.Root>

			<div class="flex items-center gap-2 px-1 py-1.5">
				<Switch
					id="include-deprecated-{scope}"
					checked={includeDeprecated}
					onCheckedChange={toggleDeprecated}
				/>
				<Label
					for="include-deprecated-{scope}"
					class="text-muted-foreground text-xs font-normal"
				>
					Show retired names
				</Label>
			</div>

			{#if activeFilters || searchTerm}
				<Button variant="ghost" size="sm" class="justify-start" onclick={clearFilters}>
					Clear filters
				</Button>
			{/if}
		</div>

		<Separator />

		<div class="flex flex-col gap-1.5">
			{@render sectionLabel("View")}
			<DropdownMenu.Root>
				<DropdownMenu.Trigger>
					{#snippet child({ props })}
						<Button variant="outline" class="w-full justify-start" {...props}>
							<Settings2Icon class="size-4" /> Columns
						</Button>
					{/snippet}
				</DropdownMenu.Trigger>
				<DropdownMenu.Content align="start" class="w-52">
					<DropdownMenu.Label>Columns</DropdownMenu.Label>
					<DropdownMenu.Separator />
					{#each conceptColumns.filter((c) => c.hideable) as column (column.id)}
						<DropdownMenu.CheckboxItem
							checked={visibility[column.id]}
							onCheckedChange={(on) => toggleColumn(column.id, on)}
							closeOnSelect={false}
						>
							{column.label}
						</DropdownMenu.CheckboxItem>
					{/each}
				</DropdownMenu.Content>
			</DropdownMenu.Root>
		</div>

		{#if can(data.user, "can_admin") || can(data.user, "can_edit")}
			<Separator />
			<div class="flex flex-col gap-1.5">
				{@render sectionLabel("Actions")}
				{#if can(data.user, "can_admin")}
					<ExportDialog
						taxonomy={data.taxonomy}
						{taxonomyName}
						date={data.date}
						ids={exportIds}
						count={exportIds ? exportIds.length : meta.total}
					/>
				{/if}
				{#if can(data.user, "can_edit")}
					<Button href="/concepts/new" class="w-full">
						<PlusIcon class="size-4" /> New concept
					</Button>
				{/if}
			</div>
		{/if}
	</div>
{/snippet}

<div class="mx-auto flex max-w-[110rem] flex-col gap-4 px-4 py-6 lg:flex-row lg:gap-8">
	<!-- Controls. A column beside the table on wide screens — which is the point: the table
	     gets the rest of the width instead of stretching across the whole window. Below `lg`
	     the same controls fold into a disclosure above it. -->
	<aside class="lg:w-64 lg:shrink-0">
		<div class="lg:hidden">
			<!-- The search box follows the table down the page on narrow screens too, where it is
			     the control most likely to be wanted again after scrolling. It stops below the two
			     bars above it and behind them, so it slides under rather than over. -->
			<div class="bg-background sticky top-26 z-20 py-2">
				{@render searchField("narrow")}
				<Button
					variant="outline"
					class="mt-3 w-full justify-between"
					aria-expanded={filtersOpen}
					onclick={() => (filtersOpen = !filtersOpen)}
				>
					<span class="flex items-center gap-2">
						<FilterIcon class="size-4" /> Filters and columns
						{#if activeFilters}
							<Badge variant="secondary" class="text-xs">{activeFilters}</Badge>
						{/if}
					</span>
					<ChevronDownIcon class="size-4 transition-transform {filtersOpen ? 'rotate-180' : ''}" />
				</Button>
			</div>
			{#if filtersOpen}
				<div class="mt-3 rounded-lg border p-3">{@render controls("narrow-panel")}</div>
			{/if}
		</div>
		<!-- `top-32` is the two sticky bars above this page (a 3.5rem app header and a 3rem taxonomy
		     bar) plus the container's own 1.5rem of top padding — so the controls stay exactly where
		     they started rather than tucking under the bars or jumping as they catch. Taller than the
		     room left, they scroll within themselves; the menus they open are portalled, so nothing
		     here clips them. -->
		<div
			class="sticky top-32 hidden max-h-[calc(100dvh-9rem)] overflow-y-auto overscroll-contain lg:block"
		>
			{@render controls("wide")}
		</div>
	</aside>

	<div class="flex min-w-0 flex-1 flex-col gap-4">
		<div class="text-muted-foreground flex flex-wrap items-center gap-2 text-sm">
			<span>
				{#if meta.total}
					{meta.total.toLocaleString()}
				{:else}
					No
				{/if}
				{meta.total === 1 ? "name" : "names"} in
				<span class="font-medium">{taxonomyName}</span>
				{#if !exhausted}
					<span class="text-muted-foreground/70">· showing {rows.length}</span>
				{/if}
			</span>
			{#if searchTerm && !searching}
				<span class="text-muted-foreground/70 text-xs">
					best matches first — names before documentation
				</span>
			{/if}
		</div>

		{#if failed}
			<p class="text-destructive rounded-md border border-dashed px-3 py-2 text-xs">
				{failed}
			</p>
		{/if}

		{#if meta.degraded.length}
			<!-- The as-of lens moves the versioned columns. Usage, documentation and status are
			     concept-level and carry no history, so they are today's values on a historical row —
			     say so rather than let the table imply the past was measured. -->
			<p
				class="text-muted-foreground flex items-center gap-2 rounded-md border border-dashed px-3 py-2 text-xs"
			>
				<ClockIcon class="size-3.5 shrink-0" />
				Viewing an earlier date. Version, sources, types and “last edited” are as of that date;
				reads, documentation and status are not versioned and show their current values.
			</p>
		{/if}

		<div class="transition-opacity" class:opacity-60={searching}>
			<ConceptTable
				{rows}
				taxonomy={data.taxonomy}
				{date}
				{sorting}
				{visibility}
				{onSort}
			/>
		</div>

		<!-- The bottom of the list: what pulls the next slice in, and what says there is none. -->
		<div bind:this={sentinel} class="flex h-10 items-center justify-center">
			{#if loadingMore}
				<span class="text-muted-foreground flex items-center gap-2 text-xs">
					<LoaderIcon class="size-3.5 animate-spin" /> Loading more…
				</span>
			{:else if rows.length && exhausted}
				<span class="text-muted-foreground/70 text-xs">
					End of the list — {meta.total.toLocaleString()}
					{meta.total === 1 ? "name" : "names"}.
				</span>
			{/if}
		</div>
	</div>
</div>
