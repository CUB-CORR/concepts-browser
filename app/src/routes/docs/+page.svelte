<script lang="ts">
	import * as Card from "$lib/components/ui/card";
	import { Separator } from "$lib/components/ui/separator";
	import { visibleChapters } from "$lib/docs/chapters";
	import { brand } from "$lib/brand";
	import { page } from "$app/state";
	import AppLink from "$lib/components/docs/AppLink.svelte";
	import ExternalLinkIcon from "@lucide/svelte/icons/external-link";

	const chapters = $derived(visibleChapters(page.data.user));
</script>

<svelte:head><title>User guide</title></svelte:head>

<div class="flex flex-col gap-8">
	<header class="flex flex-col gap-2">
		<h1 class="text-2xl font-semibold tracking-tight">User guide</h1>
		<p class="text-muted-foreground max-w-2xl text-sm leading-relaxed">
			{brand.appName} is a governed repository of clinical concept definitions. Every concept is a
			machine-readable definition per data source, versioned, reviewed before it is published, and
			readable as it stood on any past date. This guide explains the app you are looking at — what
			each page does, what you may do on it, and how to reach the same data from your own code.
		</p>
	</header>

	<div class="grid gap-3 sm:grid-cols-2">
		{#each chapters as chapter (chapter.slug)}
			{@const Icon = chapter.icon}
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

	<Separator />

	<section class="flex flex-col gap-3">
		<h2 class="text-lg font-semibold tracking-tight">In a hurry?</h2>
		<ul class="text-muted-foreground flex flex-col gap-2 text-sm">
			<li>
				Looking for a definition — go to
				<AppLink href="/concepts">all concepts</AppLink> and search by name, or read
				<a href="/docs/search" class="text-primary underline-offset-4 hover:underline"
					>Search and navigation</a
				>.
			</li>
			<li>
				Need the data in a script — read
				<a href="/docs/clients" class="text-primary underline-offset-4 hover:underline"
					>Connecting clients</a
				>; you will need an API key and a project slug.
			</li>
			<li>
				Something looks wrong in a definition — the concept page has a report-issue button when
				this deployment configured a tracker; see
				<a href="/docs/concepts#issues" class="text-primary underline-offset-4 hover:underline"
					>Browsing concepts</a
				>.
			</li>
			<li>
				Cannot see a page you expect — check
				<a href="/docs/capabilities" class="text-primary underline-offset-4 hover:underline"
					>Capabilities</a
				>; most of the app is capability-gated.
			</li>
		</ul>
	</section>

	{#if brand.apiDocsUrl}
		<section class="flex flex-col gap-2">
			<h2 class="text-lg font-semibold tracking-tight">Endpoint reference</h2>
			<p class="text-muted-foreground text-sm">
				This guide explains the app and the shape of the API. For the exhaustive, always-current
				list of endpoints, parameters and response schemas, use the generated API reference.
			</p>
			<a
				href={brand.apiDocsUrl}
				target="_blank"
				rel="noopener noreferrer"
				class="text-primary flex w-fit items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline"
			>
				Open the API reference
				<ExternalLinkIcon class="size-3.5" />
			</a>
		</section>
	{/if}
</div>
