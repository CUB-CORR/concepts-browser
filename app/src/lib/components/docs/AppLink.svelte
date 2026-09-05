<script lang="ts">
	// A link out of the guide and into the live app. Marked with an arrow so a reader can tell
	// "this sentence explains a page" from "this sentence opens it".
	import type { Snippet } from "svelte";
	import ArrowUpRightIcon from "@lucide/svelte/icons/arrow-up-right";

	let { href, children }: { href: string; children: Snippet } = $props();
</script>

<a
	{href}
	class="text-primary inline-flex items-center gap-0.5 font-medium underline-offset-4 hover:underline"
>
	{@render children()}<ArrowUpRightIcon class="size-3 shrink-0" />
</a>
