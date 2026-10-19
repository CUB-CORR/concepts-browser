<script lang="ts">
	import { page } from "$app/state";
	import { cn } from "$lib/utils";
	import { isExternalHref } from "$lib/docs/types";
	import DocsSearch from "$lib/components/docs/DocsSearch.svelte";
	import BookOpenIcon from "@lucide/svelte/icons/book-open";
	import ExternalLinkIcon from "@lucide/svelte/icons/external-link";

	let { data, children } = $props();

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
			<!-- Chapters and link groups in the order their file numbers give them; the link groups
			     are the same links the top bar's Docs menu offers, so either entry point reaches
			     everything. -->
			{#each data.docsNav as entry (entry.slug)}
				{#if entry.kind === "chapter"}
					<a
						href="/docs/{entry.slug}"
						aria-current={isActive(`/docs/${entry.slug}`) ? "page" : undefined}
						class={cn(
							"rounded-md px-3 py-1.5 pl-9 text-sm transition-colors",
							isActive(`/docs/${entry.slug}`)
								? "bg-accent text-accent-foreground font-medium"
								: "text-muted-foreground hover:text-foreground hover:bg-accent/50",
						)}
					>
						{entry.title}
					</a>
				{:else}
					<div class="mt-2 flex flex-col gap-0.5">
						{#each entry.links as link (link.href)}
							{@const external = isExternalHref(link.href)}
							<a
								href={link.href}
								target={external ? "_blank" : undefined}
								rel={external ? "noopener noreferrer" : undefined}
								class="text-muted-foreground hover:text-foreground hover:bg-accent/50 flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors"
							>
								{link.label}
								{#if external}<ExternalLinkIcon class="size-3.5 opacity-60" />{/if}
							</a>
						{/each}
					</div>
				{/if}
			{/each}
		</nav>
	</aside>

	<div class="min-w-0 flex-1">
		{@render children()}
	</div>
</div>
