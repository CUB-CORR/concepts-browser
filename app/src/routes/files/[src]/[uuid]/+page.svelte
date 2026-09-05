<script lang="ts">
	import { enhance } from "$app/forms";
	import * as Table from "$lib/components/ui/table";
	import * as Alert from "$lib/components/ui/alert";
	import * as AlertDialog from "$lib/components/ui/alert-dialog";
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Separator } from "$lib/components/ui/separator";
	import UploadFileDialog from "$lib/components/UploadFileDialog.svelte";
	import { formatBytes, formatTimestamp, fileDownloadHref, getfileRef } from "$lib/format";
	import { toast } from "svelte-sonner";
	import DownloadIcon from "@lucide/svelte/icons/download";
	import LockIcon from "@lucide/svelte/icons/lock";
	import CopyIcon from "@lucide/svelte/icons/copy";
	import CheckIcon from "@lucide/svelte/icons/check";
	import Trash2Icon from "@lucide/svelte/icons/trash-2";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import type { FileReference } from "$lib/types";
	import type { ActionData, PageData } from "./$types";

	let { data, form }: { data: PageData; form: ActionData } = $props();

	const file = $derived(data.file);
	const versions = $derived(
		[...(file.versions ?? [])].sort((a, b) => b.version_no - a.version_no),
	);
	// A new version may rename the file, so the history is where a rename becomes visible. The
	// column only appears once there is one: an unrenamed file has one name, shown above.
	const renamed = $derived(versions.some((v) => v.path && v.path !== file.path));
	const reference = $derived(getfileRef(file.uuid));

	let copied = $state(false);

	async function copy() {
		await navigator.clipboard.writeText(reference);
		copied = true;
		toast.success("Reference copied");
		setTimeout(() => (copied = false), 1500);
	}

	function conceptHref(r: FileReference): string {
		if (!r.taxonomy || !r.name) return `/concepts/id/${r.concept_id}`;
		return `/concepts/tax/${encodeURIComponent(r.taxonomy)}/${encodeURIComponent(r.name)}?cid=${r.concept_id}`;
	}

	// A refused delete carries the concepts that are in the way — a better answer than 409.
	const blockers = $derived(
		form && "references" in form ? ((form.references ?? []) as FileReference[]) : [],
	);
</script>

<svelte:head><title>{file.path}</title></svelte:head>

<div class="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-6">
	<div class="flex flex-wrap items-start justify-between gap-3">
		<div class="min-w-0">
			<p class="text-muted-foreground text-xs">
				<a href="/files" class="underline underline-offset-2">Data files</a>
				<span> / </span>
				<a href={`/files/${encodeURIComponent(data.src)}`} class="font-mono underline underline-offset-2">
					{data.src}
				</a>
			</p>
			<h1 class="font-mono text-2xl font-semibold tracking-tight break-all">{file.path}</h1>
			<div class="text-muted-foreground mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
				<Badge variant="secondary" class="font-mono">v{file.version_no}</Badge>
				<span class="tabular-nums">{formatBytes(file.size)}</span>
				<span class="font-mono">{file.media_type}</span>
				<span>{file.updated_by ?? "—"} · {formatTimestamp(file.updated_at)}</span>
			</div>
		</div>
		<div class="flex items-center gap-2">
			{#if data.canDownload}
				<Button variant="outline" size="sm" href={fileDownloadHref(data.src, file.uuid)}>
					<DownloadIcon class="size-4" /> Download
				</Button>
			{:else}
				<span class="text-muted-foreground flex items-center gap-1.5 text-xs">
					<LockIcon class="size-3.5" /> Download requires read-detail access
				</span>
			{/if}
			{#if data.canPublish}
				<UploadFileDialog src={data.src} replacing={file} label="New version" />
			{/if}
		</div>
	</div>

	{#if form && "error" in form && form.error}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Title>{form.error}</Alert.Title>
			{#if blockers.length}
				<Alert.Description>
					Still read by:
					<ul class="mt-1 flex flex-col gap-0.5">
						{#each blockers as r (r.concept_id)}
							<li>
								<a href={conceptHref(r)} class="font-mono underline underline-offset-2">
									{r.name ?? `#${r.concept_id}`}
								</a>
							</li>
						{/each}
					</ul>
				</Alert.Description>
			{/if}
		</Alert.Root>
	{/if}

	<section class="flex flex-col gap-2">
		<h2 class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Reference</h2>
		<div class="flex flex-wrap items-center gap-2">
			<code class="bg-muted rounded-md px-2 py-1 font-mono text-sm break-all">{reference}</code>
			<Button variant="ghost" size="sm" onclick={copy} title="Copy the snippet accessor">
				{#if copied}<CheckIcon class="size-3.5" />{:else}<CopyIcon class="size-3.5" />{/if}
				Copy
			</Button>
		</div>
		<p class="text-muted-foreground text-xs">
			Paste this into a <span class="font-mono">py</span> snippet; it resolves to a
			<span class="font-mono">pathlib.Path</span> at extraction time. The uuid is the identity —
			it does not change when the file does, and the path is only a label.
		</p>
	</section>

	<Separator />

	<section class="flex flex-col gap-3">
		<div class="flex items-center gap-2">
			<h2 class="text-lg font-semibold tracking-tight">Read by</h2>
			<Badge variant="secondary">{data.references.length}</Badge>
		</div>
		<p class="text-muted-foreground text-sm">
			The concepts whose current published config references this file. Uploading a new version
			publishes a new version of each of them.
		</p>
		{#if data.references.length === 0}
			<div class="text-muted-foreground rounded-lg border border-dashed p-6 text-center text-sm">
				No published config reads this file.
			</div>
		{:else}
			<ul class="flex flex-col gap-1 text-sm">
				{#each data.references as r (r.concept_id)}
					<li class="flex flex-wrap items-baseline gap-x-2 rounded-md border px-3 py-2">
						<a href={conceptHref(r)} class="font-mono hover:underline">{r.name ?? `#${r.concept_id}`}</a>
						{#if r.display_name}<span class="text-muted-foreground">{r.display_name}</span>{/if}
						{#if r.taxonomy}
							<Badge variant="outline" class="ml-auto font-mono text-[10px]">{r.taxonomy}</Badge>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}
	</section>

	<Separator />

	<section class="flex flex-col gap-3">
		<h2 class="text-lg font-semibold tracking-tight">Versions</h2>
		<div class="overflow-x-auto rounded-lg border">
			<Table.Root>
				<Table.Header>
					<Table.Row>
						<Table.Head class="w-20">Version</Table.Head>
						{#if renamed}<Table.Head>Name</Table.Head>{/if}
						<Table.Head class="text-right">Size</Table.Head>
						<Table.Head>Uploaded</Table.Head>
						<Table.Head>Message</Table.Head>
						<Table.Head>Digest</Table.Head>
						<Table.Head class="w-10"></Table.Head>
					</Table.Row>
				</Table.Header>
				<Table.Body>
					{#each versions as v (v.version_no)}
						<Table.Row>
							<Table.Cell>
								<Badge
									variant={v.version_no === file.version_no ? "secondary" : "outline"}
									class="font-mono"
								>
									v{v.version_no}
								</Badge>
							</Table.Cell>
							{#if renamed}
								<Table.Cell class="font-mono text-xs break-all">
									{#if v.path && v.path !== file.path}
										<span title="uploaded under this name">{v.path}</span>
									{:else}
										<span class="text-muted-foreground">{v.path ?? file.path}</span>
									{/if}
								</Table.Cell>
							{/if}
							<Table.Cell class="text-right tabular-nums">{formatBytes(v.size)}</Table.Cell>
							<Table.Cell class="text-muted-foreground text-xs">
								{v.author ?? "—"} · {formatTimestamp(v.created_at)}
							</Table.Cell>
							<Table.Cell class="text-muted-foreground text-sm italic">
								{v.message ?? "—"}
							</Table.Cell>
							<Table.Cell class="text-muted-foreground font-mono text-[11px]">
								{v.sha256.slice(0, 12)}
							</Table.Cell>
							<Table.Cell>
								{#if data.canDownload}
									<a
										href={fileDownloadHref(data.src, file.uuid, v.version_no)}
										class="text-muted-foreground hover:text-foreground inline-flex"
										title="Download v{v.version_no}"
										aria-label="Download v{v.version_no}"
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
	</section>

	{#if data.canPublish}
		<div>
			<AlertDialog.Root>
				<AlertDialog.Trigger>
					{#snippet child({ props })}
						<Button
							{...props}
							variant="ghost"
							size="sm"
							class="text-destructive hover:bg-destructive/10 hover:text-destructive"
						>
							<Trash2Icon class="size-4" /> Retire this file
						</Button>
					{/snippet}
				</AlertDialog.Trigger>
				<AlertDialog.Content>
					<AlertDialog.Header>
						<AlertDialog.Title>Retire <span class="font-mono">{file.path}</span>?</AlertDialog.Title>
						<AlertDialog.Description>
							The file stops being offered in this source's library. Nothing is erased — published
							versions keep resolving the bytes they were written against. A file any published
							config still reads cannot be retired; the API refuses and names them.
						</AlertDialog.Description>
					</AlertDialog.Header>
					<form method="POST" action="?/delete" use:enhance>
						<input type="hidden" name="uuid" value={file.uuid} />
						<AlertDialog.Footer>
							<AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
							<AlertDialog.Action type="submit" class="bg-destructive text-white hover:bg-destructive/90">
								Retire file
							</AlertDialog.Action>
						</AlertDialog.Footer>
					</form>
				</AlertDialog.Content>
			</AlertDialog.Root>
		</div>
	{/if}
</div>
