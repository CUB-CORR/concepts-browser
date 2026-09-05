<script lang="ts">
	// Admin-only export of the concepts list. Sits at the bottom of the filter sidebar and
	// exports exactly what the list currently shows: `ids` carries the filtered concept ids
	// (null = the whole taxonomy), `date` the page's as-of lens. The file is built server-side
	// and can take a while for large taxonomies, hence the in-dialog progress state.
	import { toast } from "svelte-sonner";
	import * as Dialog from "$lib/components/ui/dialog";
	import { Button } from "$lib/components/ui/button";
	import { Checkbox } from "$lib/components/ui/checkbox";
	import { Label } from "$lib/components/ui/label";
	import DownloadIcon from "@lucide/svelte/icons/download";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";

	type Format = "csv" | "xlsx";

	let {
		taxonomy,
		taxonomyName,
		date,
		ids,
		count,
	}: {
		taxonomy: string;
		taxonomyName: string;
		/** The page's as-of lens as YYYY-MM-DD, or "" when live. */
		date: string;
		/** Concept ids of the filtered list, or null to export the whole taxonomy. */
		ids: number[] | null;
		/** How many concepts the export will contain. */
		count: number;
	} = $props();

	let open = $state(false);
	let includeConfigs = $state(false);
	let exporting = $state<Format | null>(null);

	async function download(format: Format) {
		exporting = format;
		try {
			const res = await fetch("/concepts/export", {
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify({
					taxonomy,
					format,
					ids,
					include_configs: includeConfigs,
					date: date || null,
				}),
			});
			if (!res.ok) {
				toast.error(`Export failed (${res.status})`);
				return;
			}
			const blob = await res.blob();
			const filename = /filename="([^"]+)"/.exec(
				res.headers.get("content-disposition") ?? "",
			)?.[1];
			const link = document.createElement("a");
			link.href = URL.createObjectURL(blob);
			link.download = filename ?? `concepts_${taxonomy}.${format}`;
			link.click();
			URL.revokeObjectURL(link.href);
			toast.success(`Exported ${count} ${count === 1 ? "concept" : "concepts"}`);
			open = false;
		} catch {
			toast.error("Export failed");
		} finally {
			exporting = null;
		}
	}
</script>

<Dialog.Root bind:open>
	<Dialog.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="outline" size="sm" class="w-full">
				<DownloadIcon class="size-4" />
				Export
			</Button>
		{/snippet}
	</Dialog.Trigger>

	<!-- While the file is being built, the dialog can't be dismissed: the spinner is the only
	     indication that anything is happening. -->
	<Dialog.Content
		showCloseButton={exporting === null}
		escapeKeydownBehavior={exporting ? "ignore" : "close"}
		interactOutsideBehavior={exporting ? "ignore" : "close"}
	>
		<Dialog.Header>
			<Dialog.Title>Export concepts</Dialog.Title>
			<Dialog.Description>
				{count}
				{count === 1 ? "concept" : "concepts"}
				{ids === null ? "in" : "matching the current filters in"}
				<span class="font-medium">{taxonomyName}</span>{date ? `, as of ${date}` : ""}. One
				row per concept with its name in every taxonomy, the clinical documentation and the
				configured sources.
			</Dialog.Description>
		</Dialog.Header>

		<div class="flex items-start gap-3">
			<Checkbox
				id="export-include-configs"
				bind:checked={includeConfigs}
				disabled={exporting !== null}
			/>
			<div class="grid gap-1">
				<Label for="export-include-configs" class="font-normal">
					Include source configuration
				</Label>
				<p class="text-muted-foreground text-xs">
					Adds the latest published JSON and Python of each source as extra columns.
				</p>
			</div>
		</div>

		<Dialog.Footer>
			{#if exporting}
				<p class="text-muted-foreground mr-auto flex items-center gap-2 text-xs">
					<LoaderIcon class="size-3.5 animate-spin" />
					Preparing the file — this can take a moment.
				</p>
			{/if}
			<Button
				variant="outline"
				disabled={exporting !== null}
				onclick={() => download("csv")}
			>
				{#if exporting === "csv"}<LoaderIcon class="size-4 animate-spin" />{/if}
				CSV
			</Button>
			<Button disabled={exporting !== null} onclick={() => download("xlsx")}>
				{#if exporting === "xlsx"}<LoaderIcon class="size-4 animate-spin" />{/if}
				Excel (.xlsx)
			</Button>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
