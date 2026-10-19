<script lang="ts">
	// A parsed chapter body: its intro, then each `## Title {#id}` as a linkable `DocSection`.
	// The intro's blocks sit directly in the chapter's frame, spaced like the sections.
	import type { DocBody } from "$lib/docs/types";
	import DocSection from "./DocSection.svelte";
	import Markdown from "./Markdown.svelte";
	import { page } from "$app/state";
	import { shown } from "$lib/docs/conditions";

	let { body }: { body: DocBody } = $props();

	const sections = $derived(
		body.sections.filter((s) => shown(s.condition, page.data.user, page.data.docs?.links ?? [])),
	);
</script>

<Markdown nodes={body.intro} />
{#each sections as section (section.id)}
	<DocSection id={section.id} title={section.title}>
		<Markdown nodes={section.nodes} />
	</DocSection>
{/each}
