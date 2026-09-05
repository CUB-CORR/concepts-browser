<script lang="ts">
	// A titled section of a guide chapter. The id makes every heading linkable, which is what
	// lets one chapter point at an exact paragraph of another.
	import type { Snippet } from "svelte";
	import LinkIcon from "@lucide/svelte/icons/link";

	let { id, title, children }: { id: string; title: string; children: Snippet } = $props();
</script>

<section {id} class="scroll-mt-20 flex flex-col gap-3">
	<h2 class="group flex items-center gap-2 text-lg font-semibold tracking-tight">
		{title}
		<a
			href="#{id}"
			class="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
			aria-label="Link to this section"
		>
			<LinkIcon class="size-3.5" />
		</a>
	</h2>
	<div class="text-muted-foreground flex flex-col gap-3 text-sm leading-relaxed">
		{@render children()}
	</div>
</section>
