<script lang="ts">
	import * as Table from "$lib/components/ui/table";
	import { formatTimestamp } from "$lib/format";
	import type { UsageConcept } from "$lib/types";

	// The concepts read, newest first. Used by the profile page (one user, every project) and by
	// the project page (one project, every user) — the same row shape from either direction.
	let { concepts }: { concepts: UsageConcept[] } = $props();

	// Where a used concept lives now. It is addressed by id when the log never caught a name for
	// it (a read that resolved nothing to name it by) — the id route redirects to the page.
	function conceptHref(c: UsageConcept): string {
		if (!c.name || !c.taxonomy) return `/concepts/id/${c.concept_id}`;
		return `/concepts/tax/${encodeURIComponent(c.taxonomy)}/${encodeURIComponent(c.name)}`;
	}
</script>

<div class="overflow-hidden rounded-lg border">
	<Table.Root>
		<Table.Header>
			<Table.Row>
				<Table.Head>Concept</Table.Head>
				<Table.Head class="w-20 text-right">Reads</Table.Head>
				<Table.Head class="w-48">Last accessed</Table.Head>
				<Table.Head class="w-28">Version</Table.Head>
			</Table.Row>
		</Table.Header>
		<Table.Body>
			{#each concepts as c (c.concept_id)}
				<Table.Row>
					<Table.Cell>
						<a href={conceptHref(c)} class="text-primary hover:underline">
							{c.name ?? `#${c.concept_id}`}
						</a>
						{#if c.taxonomy}
							<span class="text-muted-foreground ml-2 text-xs">{c.taxonomy}</span>
						{/if}
					</Table.Cell>
					<Table.Cell class="text-right tabular-nums">{c.reads}</Table.Cell>
					<Table.Cell class="text-muted-foreground text-sm">
						{formatTimestamp(c.last_used_at)}
					</Table.Cell>
					<Table.Cell class="text-muted-foreground text-sm tabular-nums">
						{c.versions ?? "—"}
					</Table.Cell>
				</Table.Row>
			{/each}
		</Table.Body>
	</Table.Root>
</div>
