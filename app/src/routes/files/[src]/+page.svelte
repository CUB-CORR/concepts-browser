<script lang="ts">
	import * as Table from "$lib/components/ui/table";
	import * as Alert from "$lib/components/ui/alert";
	import { Badge } from "$lib/components/ui/badge";
	import UploadFileDialog from "$lib/components/UploadFileDialog.svelte";
	import { formatBytes, formatTimestamp, filePageHref, fileDownloadHref } from "$lib/format";
	import DownloadIcon from "@lucide/svelte/icons/download";
	import LockIcon from "@lucide/svelte/icons/lock";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import type { ActionData, PageData } from "./$types";

	let { data, form }: { data: PageData; form: ActionData } = $props();

	const sorted = $derived([...data.files].sort((a, b) => a.path.localeCompare(b.path)));
</script>

<svelte:head><title>{data.src} files</title></svelte:head>

<div class="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div>
			<p class="text-muted-foreground text-xs">
				<a href="/files" class="underline underline-offset-2">Data files</a>
			</p>
			<h1 class="font-mono text-2xl font-semibold tracking-tight">{data.src}</h1>
			<p class="text-muted-foreground max-w-3xl text-sm">
				{data.source?.nicename ? `${data.source.nicename}. ` : ""}Every data file this source's
				definitions read. A snippet reaches one with <code class="font-mono">getfile("&lt;uuid&gt;")</code>,
				so the reference survives every replacement — and a replacement publishes a new version
				of each concept that reads it.
			</p>
		</div>
		{#if data.canPublish}
			<UploadFileDialog src={data.src} files={data.files} />
		{/if}
	</div>

	{#if form && "error" in form && form.error}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Title>{form.error}</Alert.Title>
		</Alert.Root>
	{/if}

	{#if sorted.length === 0}
		<div class="text-muted-foreground rounded-lg border border-dashed p-10 text-center text-sm">
			No files in this source's library yet.
		</div>
	{:else}
		<div class="overflow-x-auto rounded-lg border">
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head>Path</Table.Head>
						<Table.Head class="text-right">Size</Table.Head>
						<Table.Head>Version</Table.Head>
						<Table.Head>Updated</Table.Head>
						<Table.Head>Read by</Table.Head>
						<Table.Head class="w-10"></Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each sorted as file (file.uuid)}
						<Table.Row>
							<Table.Cell class="font-mono">
								<a href={filePageHref(data.src, file.uuid)} class="hover:underline">{file.path}</a>
							</Table.Cell>
							<Table.Cell class="text-right tabular-nums">{formatBytes(file.size)}</Table.Cell>
							<Table.Cell>
								<Badge variant="secondary" class="font-mono">v{file.version_no}</Badge>
							</Table.Cell>
							<Table.Cell class="text-muted-foreground text-xs">
								{file.updated_by ?? "—"} · {formatTimestamp(file.updated_at)}
							</Table.Cell>
							<Table.Cell class="text-xs">
								{#if file.referenced_by}
									<a href={filePageHref(data.src, file.uuid)} class="hover:underline">
										{file.referenced_by} concept{file.referenced_by === 1 ? "" : "s"}
									</a>
								{:else}
									<span class="text-muted-foreground">no concept</span>
								{/if}
							</Table.Cell>
							<Table.Cell>
								{#if data.canDownload}
									<a
										href={fileDownloadHref(data.src, file.uuid)}
										class="text-muted-foreground hover:text-foreground inline-flex"
										title="Download {file.path}"
										aria-label="Download {file.path}"
									>
										<DownloadIcon class="size-4" />
									</a>
								{:else}
									<LockIcon
										class="text-muted-foreground size-4"
										aria-label="Downloading requires read-detail access"
									/>
								{/if}
							</Table.Cell>
						</Table.Row>
					{/each}
				</Table.Body>
			</Table.Root>
		</div>
	{/if}
</div>
