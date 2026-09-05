<script lang="ts">
	// A pointer at the Administration chapter, which only `can_admin` may open (see
	// routes/docs/admin/+page.server.ts). For everyone else the sentence keeps its words and
	// loses the link, so the guide never offers a door that would bounce the reader back.
	import type { Snippet } from "svelte";
	import { page } from "$app/state";
	import { can } from "$lib/caps";

	let { href = "/docs/admin", children }: { href?: string; children: Snippet } = $props();

	const isAdmin = $derived(can(page.data.user, "can_admin"));
</script>

{#if isAdmin}
	<a {href} class="text-primary underline-offset-4 hover:underline">{@render children()}</a>
{:else}
	{@render children()}
{/if}
