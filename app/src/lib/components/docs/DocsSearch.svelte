<script lang="ts">
	// The guide's own search box. It sits at the top of the chapter sidebar, so it is present
	// on every chapter and on the landing page, and it searches all chapters at once — the
	// index is built from the chapter sources themselves (see $lib/docs/search).
	import { goto } from "$app/navigation";
	import { page } from "$app/state";
	import { Input } from "$lib/components/ui/input";
	import { cn } from "$lib/utils";
	import SearchIcon from "@lucide/svelte/icons/search";
	import { docIndex, searchDocs, type DocHit } from "$lib/docs/search";

	let query = $state("");
	let hits = $state<DocHit[]>([]);
	let active = $state(0);
	let open = $state(false);
	let input = $state<HTMLInputElement | null>(null);
	let root = $state<HTMLDivElement | null>(null);

	// The index is fetched on the first keystroke and kept for the session; `run` is guarded
	// by a sequence number so a slow first build cannot overwrite a later query's results.
	let seq = 0;

	async function run(value: string) {
		query = value;
		const mine = ++seq;
		if (value.trim().length < 2) {
			hits = [];
			open = false;
			return;
		}
		// Indexes only the chapters this reader may open, so a gated one cannot leak as a hit.
		const entries = await docIndex(page.data.user);
		if (mine !== seq) return;
		hits = searchDocs(entries, value);
		active = 0;
		open = true;
	}

	function clear() {
		query = "";
		hits = [];
		open = false;
	}

	function visit(hit: DocHit | undefined) {
		if (!hit) return;
		clear();
		input?.blur();
		void goto(hit.href);
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === "Escape") {
			clear();
			input?.blur();
			return;
		}
		if (!open || !hits.length) return;
		if (event.key === "Enter") {
			event.preventDefault();
			visit(hits[active]);
		} else if (event.key === "ArrowDown") {
			event.preventDefault();
			active = (active + 1) % hits.length;
		} else if (event.key === "ArrowUp") {
			event.preventDefault();
			active = (active - 1 + hits.length) % hits.length;
		}
	}

	// Closing on focus leaving the whole widget keeps a click on a result from racing a blur.
	function onFocusOut(event: FocusEvent) {
		const next = event.relatedTarget;
		if (next instanceof Node && root?.contains(next)) return;
		open = false;
	}
</script>

<div class="relative mb-2" bind:this={root} onfocusout={onFocusOut}>
	<SearchIcon
		class="text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
	/>
	<Input
		bind:ref={input}
		id="docs-search"
		type="search"
		placeholder="Search the guide…"
		aria-label="Search the user guide"
		autocomplete="off"
		class="h-8 pl-9 text-sm"
		value={query}
		oninput={(e) => run(e.currentTarget.value)}
		onfocus={() => (open = hits.length > 0)}
		onkeydown={onKeydown}
	/>

	{#if open}
		<div
			class="bg-popover text-popover-foreground absolute top-full left-0 z-50 mt-1 w-80 max-w-[80vw] overflow-hidden rounded-md border shadow-md"
		>
			{#if hits.length}
				<ul class="max-h-96 overflow-y-auto py-1">
					{#each hits as hit, i (hit.href)}
						<li>
							<a
								href={hit.href}
								onclick={() => clear()}
								onmouseenter={() => (active = i)}
								class={cn(
									"flex flex-col gap-0.5 px-3 py-2 text-sm transition-colors",
									i === active ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
								)}
							>
								<span class="flex items-baseline gap-1.5">
									<span class="font-medium">{hit.sectionTitle}</span>
									<span class="text-muted-foreground truncate text-xs">{hit.chapterTitle}</span>
								</span>
								{#if hit.excerpt.match}
									<span class="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
										{hit.excerpt.before}<mark
											class="bg-transparent font-medium text-inherit underline underline-offset-2"
											>{hit.excerpt.match}</mark
										>{hit.excerpt.after}
									</span>
								{/if}
							</a>
						</li>
					{/each}
				</ul>
			{:else}
				<p class="text-muted-foreground px-3 py-3 text-sm">No section matches “{query.trim()}”.</p>
			{/if}
		</div>
	{/if}
</div>
