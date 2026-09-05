<script lang="ts">
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Separator } from "$lib/components/ui/separator";
	import * as Alert from "$lib/components/ui/alert";
	import CodeBlock from "$lib/components/CodeBlock.svelte";
	import AttachedFiles from "$lib/components/AttachedFiles.svelte";
	import SchemaView from "$lib/components/schema/SchemaView.svelte";
	import VersionHistory from "$lib/components/VersionHistory.svelte";
	import { changeTypeVariant, formatTimestamp } from "$lib/format";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import LockIcon from "@lucide/svelte/icons/lock";
	import type { Draft, HistoryRow, JsonSchema, SourceConfig } from "$lib/types";

	let {
		taxonomy,
		name,
		source,
		config,
		schema = null,
		history,
		drafts = [],
		selectedVersion,
		activeDraftId = null,
		canEdit = false,
		readOnly = false,
	}: {
		taxonomy: string;
		name: string;
		source: string;
		config: SourceConfig;
		schema?: JsonSchema | null;
		history: HistoryRow[];
		drafts?: Draft[];
		selectedVersion: number | null;
		activeDraftId?: number | null;
		canEdit?: boolean;
		readOnly?: boolean;
	} = $props();

	const info = $derived(config.version_info);
	// `can_read` sees the concept and its JSON; the snippet and the file bytes are
	// `can_read_detail`. The API says which of the two happened — `py_locked` distinguishes
	// "withheld" from "there is no code here" — so the panel can name the missing capability
	// instead of rendering an empty box.
	const pyLocked = $derived(Boolean(config.py_locked));
	const json = $derived(JSON.stringify(config.json, null, 2));
	const pyReady = $derived(Boolean((config.json as Record<string, unknown>).py_ready_polars));
	let showRaw = $state(false);
</script>

<div class="flex flex-col gap-4">
	{#if info.warning}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Title>Critical update supersedes this version</Alert.Title>
			<Alert.Description>
				Corrected in v{info.warning.corrected_in_version}{#if info.warning.message}: {info.warning.message}{/if}
			</Alert.Description>
		</Alert.Root>
	{/if}

	<div class="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
		{#if readOnly}
			<Badge variant="secondary" class="gap-1 text-xs">
				<LockIcon class="size-3" /> Read-only · auto-generated
			</Badge>
			<span class="flex items-center gap-1.5">
				<span class="text-muted-foreground">Type</span>
				<Badge variant="outline" class="font-mono">{info.type}</Badge>
			</span>
		{:else}
			<span class="flex items-center gap-1.5">
				<span class="text-muted-foreground">Version</span>
				<Badge variant="secondary" class="font-mono">v{info.source_version}</Badge>
			</span>
			<span class="flex items-center gap-1.5">
				<span class="text-muted-foreground">Type</span>
				<Badge variant="outline" class="font-mono">{info.type}</Badge>
			</span>
			<Badge variant={changeTypeVariant(info.change_type)} class="text-xs">{info.change_type}</Badge>
			<span class="text-muted-foreground">
				by {info.author ?? "—"} · {formatTimestamp(info.committed_at)}
			</span>
		{/if}
	</div>

	{#if info.message}
		<p class="text-muted-foreground text-sm italic">"{info.message}"</p>
	{/if}

	<div class="flex flex-col gap-2">
		<div class="flex items-center justify-between">
			<h4 class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Definition</h4>
			<div class="flex items-center gap-2">
				{#if pyReady}
					<Badge variant="outline" class="text-xs">py_ready_polars</Badge>
				{/if}
				<Button variant="ghost" size="sm" class="h-7 px-2 text-xs" onclick={() => (showRaw = !showRaw)}>
					{showRaw ? "Fields" : "Raw JSON"}
				</Button>
			</div>
		</div>
		{#if showRaw}
			<CodeBlock code={json} language="json" />
		{:else}
			<div class="rounded-md border p-3">
				<SchemaView {schema} value={config.json} />
			</div>
		{/if}
	</div>

	{#if config.py || pyLocked || config.files?.length}
		<div class="flex flex-col gap-2">
			<h4 class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Python</h4>
			<!-- Downloads only: files live in the source's library, and this version's pins are
			     immutable, so there is nothing to add or remove here. -->
			<AttachedFiles files={config.files ?? []} {source} locked={pyLocked} />
			{#if config.py}
				<CodeBlock code={config.py} language="python" />
			{:else if pyLocked}
				<Alert.Root>
					<LockIcon class="size-4" />
					<Alert.Title>This definition's code requires read-detail access</Alert.Title>
					<Alert.Description>
						There is a Python snippet here, but showing it (and downloading the data files it
						reads) needs the <code class="font-mono">can_read_detail</code> capability. Ask an
						administrator to grant it.
					</Alert.Description>
				</Alert.Root>
			{/if}
		</div>
	{/if}

	{#if !readOnly}
		<Separator />
		<VersionHistory {taxonomy} {name} {source} rows={history} {drafts} {selectedVersion} {activeDraftId} canDelete={canEdit} />
	{/if}
</div>
