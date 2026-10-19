<script lang="ts">
	// The frame every chapter shares: title, lede, body, and the prev/next footer. The neighbours
	// come from the server, walked over the chapters this reader may open (see $lib/server/docs).
	import type { Snippet } from "svelte";
	import type { ChapterMeta } from "$lib/docs/types";
	import { Separator } from "$lib/components/ui/separator";
	import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
	import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";

	let {
		chapter,
		prev,
		next,
		children,
	}: {
		chapter: ChapterMeta;
		prev: ChapterMeta | null;
		next: ChapterMeta | null;
		children: Snippet;
	} = $props();
</script>

<svelte:head><title>{chapter.title} — User guide</title></svelte:head>

<article class="flex flex-col gap-8">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">{chapter.title}</h1>
		<p class="text-muted-foreground text-sm">{chapter.summary}</p>
	</header>

	{@render children()}

	<Separator />

	<nav class="flex items-center justify-between gap-4 text-sm">
		{#if prev}
			<a
				href="/docs/{prev.slug}"
				class="text-muted-foreground hover:text-foreground flex items-center gap-1.5"
			>
				<ArrowLeftIcon class="size-4" />
				{prev.title}
			</a>
		{:else}
			<a
				href="/docs"
				class="text-muted-foreground hover:text-foreground flex items-center gap-1.5"
			>
				<ArrowLeftIcon class="size-4" />
				Guide overview
			</a>
		{/if}
		{#if next}
			<a
				href="/docs/{next.slug}"
				class="text-muted-foreground hover:text-foreground ml-auto flex items-center gap-1.5"
			>
				{next.title}
				<ArrowRightIcon class="size-4" />
			</a>
		{/if}
	</nav>
</article>
