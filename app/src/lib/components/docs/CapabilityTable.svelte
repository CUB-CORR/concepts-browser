<script lang="ts">
	// `::capability-table` — every capability the app knows, what it grants and where it shows.
	// Iterates ALL_CAPABILITIES, so a new capability cannot be added without appearing here; the
	// prose lives in $lib/docs/capabilities.
	import * as Table from "$lib/components/ui/table";
	import { Badge } from "$lib/components/ui/badge";
	import { ALL_CAPABILITIES } from "$lib/types";
	import { described, entails, routeHref } from "$lib/docs/capabilities";
</script>

<Table.Root>
	<Table.Header>
		<Table.Row>
			<Table.Head class="w-40">Capability</Table.Head>
			<Table.Head>What it allows</Table.Head>
			<Table.Head class="w-44">Mainly seen on</Table.Head>
		</Table.Row>
	</Table.Header>
	<Table.Body>
		{#each ALL_CAPABILITIES as cap (cap)}
			<Table.Row>
				<Table.Cell class="align-top">
					<div class="flex flex-col gap-1">
						<Badge variant="outline" class="font-mono">{cap}</Badge>
						{#if entails(cap).length}
							<span class="text-muted-foreground text-[11px]">
								also grants {entails(cap).join(", ")}
							</span>
						{:else if cap === "can_admin"}
							<span class="text-muted-foreground text-[11px]">grants everything</span>
						{/if}
					</div>
				</Table.Cell>
				<Table.Cell class="text-muted-foreground align-top text-sm">
					{described[cap]?.grants}
				</Table.Cell>
				<Table.Cell class="align-top text-sm">
					{#each (described[cap]?.where ?? "").split(", ") as route, i (route)}
						{#if i > 0},&nbsp;{/if}
						{#if routeHref[route]}
							<a
								href={routeHref[route]}
								class="text-primary font-mono text-xs underline-offset-4 hover:underline"
								>{route}</a
							>
						{:else}
							<span class="font-mono text-xs">{route}</span>
						{/if}
					{/each}
				</Table.Cell>
			</Table.Row>
		{/each}
	</Table.Body>
</Table.Root>
