<script lang="ts">
	import * as Card from "$lib/components/ui/card";
	import { Separator } from "$lib/components/ui/separator";
	import { docIcon } from "$lib/docs/icons";
	import DocSection from "$lib/components/docs/DocSection.svelte";
	import Markdown from "$lib/components/docs/Markdown.svelte";
	import { page } from "$app/state";
	import { shown } from "$lib/docs/conditions";

	let { data } = $props();

	// The landing page is `index.md`: its intro above the chapter cards, its sections below.
	const chapters = $derived(data.docsNav.filter((e) => e.kind === "chapter"));
	const sections = $derived(
		data.index.body.sections.filter((s) => shown(s.condition, data.user, page.data.docs?.links ?? [])),
	);
</script>

<svelte:head><title>{data.index.title}</title></svelte:head>

<div class="flex flex-col gap-8">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">{data.index.title}</h1>
		{#if data.index.body.intro.length}
			<div class="text-muted-foreground flex max-w-2xl flex-col gap-2 text-sm leading-relaxed">
				<Markdown nodes={data.index.body.intro} />
			</div>
		{/if}
	</header>

	<div class="grid gap-3 sm:grid-cols-2">
		{#each chapters as chapter (chapter.slug)}
			{@const Icon = docIcon(chapter.icon)}
			<a href="/docs/{chapter.slug}" class="block">
				<Card.Root class="hover:bg-accent/40 h-full transition-colors">
					<Card.Header>
						<Card.Title class="flex items-center gap-2 text-base">
							<Icon class="text-muted-foreground size-4" />
							{chapter.title}
						</Card.Title>
						<Card.Description>{chapter.summary}</Card.Description>
					</Card.Header>
				</Card.Root>
			</a>
		{/each}
	</div>

	{#if sections.length}
		<Separator />
		{#each sections as section (section.id)}
			<DocSection id={section.id} title={section.title}>
				<Markdown nodes={section.nodes} />
			</DocSection>
		{/each}
	{/if}
</div>
