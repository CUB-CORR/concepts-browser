<script lang="ts">
	// Inline "requires can_publish" marker. Links to the capabilities chapter so a reader who
	// does not know what the word buys them is one click from the table — unless this deployment
	// hid that chapter, in which case it is a plain badge rather than a link into a 404.
	import { Badge } from "$lib/components/ui/badge";
	import LockIcon from "@lucide/svelte/icons/lock";
	import { page } from "$app/state";
	import type { Capability } from "$lib/types";

	let { cap, verb = "requires" }: { cap: Capability; verb?: string } = $props();

	const linked = $derived((page.data.docs?.slugs ?? []).includes("capabilities"));
</script>

<Badge
	variant="outline"
	href={linked ? "/docs/capabilities#table" : undefined}
	class="font-mono align-middle"
	title={linked ? "See the capability table" : undefined}
>
	<LockIcon />
	{verb}
	{cap}
</Badge>
