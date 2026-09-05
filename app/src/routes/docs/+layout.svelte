<script lang="ts">
	import { page } from "$app/state";
	import { cn } from "$lib/utils";
	import { visibleChapters } from "$lib/docs/chapters";
	import DocsSearch from "$lib/components/docs/DocsSearch.svelte";
	import BookOpenIcon from "@lucide/svelte/icons/book-open";
	import ExternalLinkIcon from "@lucide/svelte/icons/external-link";
	import { brand } from "$lib/brand";

	let { children } = $props();

	const chapters = $derived(visibleChapters(page.data.user));

	function isActive(href: string): boolean {
		return page.url.pathname === href;
	}
</script>

<div class="mx-auto flex w-full max-w-6xl gap-8 px-4 py-6">
	<!-- Chapter navigation. Sticky on wide screens; on narrow ones the guide reads top-to-bottom
	     and the prev/next footer carries the order instead. -->
	<aside class="hidden w-56 shrink-0 lg:block">
		<nav class="sticky top-20 flex flex-col gap-0.5">
			<!-- Searches every chapter, not the one on screen; hits link at the section anchor. -->
			<DocsSearch />
			<a
				href="/docs"
				class={cn(
					"flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
					isActive("/docs")
						? "bg-accent text-accent-foreground"
						: "text-muted-foreground hover:text-foreground hover:bg-accent/50",
				)}
			>
				<BookOpenIcon class="size-4" />
				User guide
			</a>
			{#each chapters as chapter (chapter.slug)}
				<a
					href="/docs/{chapter.slug}"
					aria-current={isActive(`/docs/${chapter.slug}`) ? "page" : undefined}
					class={cn(
						"rounded-md px-3 py-1.5 pl-9 text-sm transition-colors",
						isActive(`/docs/${chapter.slug}`)
							? "bg-accent text-accent-foreground font-medium"
							: "text-muted-foreground hover:text-foreground hover:bg-accent/50",
					)}
				>
					{chapter.title}
				</a>
			{/each}
			<!-- The same external links the top bar's Docs menu offers, so either entry point
			     reaches everything. -->
			<a
				href="https://github.com/CUB-CORR/corr-vars"
				target="_blank"
				rel="noopener noreferrer"
				class="text-muted-foreground hover:text-foreground hover:bg-accent/50 mt-2 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors"
			>
				CORR-Vars
				<ExternalLinkIcon class="size-3.5 opacity-60" />
			</a>
			{#if brand.apiDocsUrl}
				<a
					href={brand.apiDocsUrl}
					target="_blank"
					rel="noopener noreferrer"
					class="text-muted-foreground hover:text-foreground hover:bg-accent/50 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors"
				>
					API reference
					<ExternalLinkIcon class="size-3.5 opacity-60" />
				</a>
			{/if}
		</nav>
	</aside>

	<div class="min-w-0 flex-1">
		{@render children()}
	</div>
</div>
