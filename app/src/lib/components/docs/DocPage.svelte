<script lang="ts">
	// The frame every chapter shares: title, lede, body, and the prev/next footer derived from
	// the chapter list so the order lives in exactly one place.
	import type { Snippet } from "svelte";
	import { Separator } from "$lib/components/ui/separator";
	import ArrowLeftIcon from "@lucide/svelte/icons/arrow-left";
	import ArrowRightIcon from "@lucide/svelte/icons/arrow-right";
	import { chapterBySlug, neighbours } from "$lib/docs/chapters";
	import { page } from "$app/state";

	let { slug, children }: { slug: string; children: Snippet } = $props();

	const chapter = $derived(chapterBySlug(slug));
	// Walks only the chapters this reader can see, so a gated one is skipped rather than
	// offered as the next chapter.
	const around = $derived(neighbours(slug, page.data.user));
</script>

<svelte:head><title>{chapter?.title ?? "User guide"} — User guide</title></svelte:head>

<article class="flex flex-col gap-8">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">{chapter?.title}</h1>
		<p class="text-muted-foreground text-sm">{chapter?.summary}</p>
	</header>

	{@render children()}

	<Separator />

	<nav class="flex items-center justify-between gap-4 text-sm">
		{#if around.prev}
			<a
				href="/docs/{around.prev.slug}"
				class="text-muted-foreground hover:text-foreground flex items-center gap-1.5"
			>
				<ArrowLeftIcon class="size-4" />
				{around.prev.title}
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
		{#if around.next}
			<a
				href="/docs/{around.next.slug}"
				class="text-muted-foreground hover:text-foreground ml-auto flex items-center gap-1.5"
			>
				{around.next.title}
				<ArrowRightIcon class="size-4" />
			</a>
		{/if}
	</nav>
</article>
