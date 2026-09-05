<script lang="ts">
	// Inline "requires can_publish" marker. Links to the capabilities chapter so a reader who
	// does not know what the word buys them is one click from the table.
	import { Badge } from "$lib/components/ui/badge";
	import LockIcon from "@lucide/svelte/icons/lock";
	import type { Capability } from "$lib/types";

	let { cap, verb = "requires" }: { cap: Capability; verb?: string } = $props();
</script>

<Badge
	variant="outline"
	href="/docs/capabilities#table"
	class="font-mono align-middle"
	title="See the capability table"
>
	<LockIcon />
	{verb}
	{cap}
</Badge>
