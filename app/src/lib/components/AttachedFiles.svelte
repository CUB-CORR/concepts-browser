<script lang="ts">
	// The data files this version of a source definition reads — mapping tables, a pickled
	// model — sitting directly above the code box that reads them.
	//
	// Read-only, always: a file belongs to the **source**, not to one concept's version, and is
	// versioned in the source's library. What a config carries is a pin (uuid at version), so
	// there is nothing here to attach or detach; uploading a new version happens in the library
	// and publishes a new version of every concept whose snippet references the file.
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { formatBytes, fileDownloadHref, filePageHref, getfileRef } from "$lib/format";
	import { toast } from "svelte-sonner";
	import PaperclipIcon from "@lucide/svelte/icons/paperclip";
	import DownloadIcon from "@lucide/svelte/icons/download";
	import LockIcon from "@lucide/svelte/icons/lock";
	import CopyIcon from "@lucide/svelte/icons/copy";
	import CheckIcon from "@lucide/svelte/icons/check";
	import type { SourceFile } from "$lib/types";

	let {
		files,
		source,
		locked = false,
	}: {
		files: SourceFile[];
		/** The source whose library these files live in — what makes them addressable. */
		source: string;
		/** The signed-in user lacks `can_read_detail`, so the API refuses the bytes with a 403.
		 *  The manifest still lists what is pinned — that part is metadata — but each row loses
		 *  its download link and says why, rather than offering a link that errors. */
		locked?: boolean;
	} = $props();

	let copied = $state<string | null>(null);

	async function copy(file: SourceFile) {
		await navigator.clipboard.writeText(getfileRef(file.uuid));
		copied = file.uuid;
		toast.success("Reference copied");
		setTimeout(() => (copied = null), 1500);
	}
</script>

<div class="flex flex-col gap-2 rounded-md border border-dashed p-3">
	<div class="flex items-center gap-2">
		<PaperclipIcon class="text-muted-foreground size-3.5" />
		<h5 class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Data files</h5>
		{#if files.length}
			<Badge variant="secondary" class="text-[10px]">{files.length}</Badge>
		{/if}
		<a
			href={`/files/${encodeURIComponent(source)}`}
			class="text-muted-foreground hover:text-foreground ml-auto text-[11px] underline underline-offset-2"
		>
			{source} file library
		</a>
	</div>

	{#if files.length}
		<ul class="flex flex-col gap-1">
			{#each files as file (file.uuid)}
				<li class="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
					{#if locked}
						<span
							class="text-muted-foreground flex items-center gap-1 font-mono"
							title="Downloading {file.path} requires read-detail access"
						>
							<LockIcon class="size-3" />{file.path}
						</span>
					{:else}
						<a
							href={fileDownloadHref(source, file.uuid, file.version_no)}
							class="hover:text-foreground text-muted-foreground flex items-center gap-1 font-mono"
							title="Download {file.path} (v{file.version_no})"
						>
							<DownloadIcon class="size-3" />{file.path}
						</a>
					{/if}
					<Badge variant="outline" class="font-mono text-[10px]">v{file.version_no}</Badge>
					<span class="text-muted-foreground tabular-nums">{formatBytes(file.size)}</span>
					<Button
						variant="ghost"
						size="sm"
						class="h-6 gap-1 px-1.5 font-mono text-[11px]"
						title="Copy the snippet accessor"
						onclick={() => copy(file)}
					>
						{#if copied === file.uuid}<CheckIcon class="size-3" />{:else}<CopyIcon class="size-3" />{/if}
						getfile("…")
					</Button>
					<a
						href={filePageHref(source, file.uuid)}
						class="text-muted-foreground hover:text-foreground ml-auto underline underline-offset-2"
					>
						history
					</a>
				</li>
			{/each}
		</ul>
	{:else}
		<p class="text-muted-foreground text-xs">
			This definition reads no data files. Files live in the
			<a href={`/files/${encodeURIComponent(source)}`} class="underline underline-offset-2"
				>{source} file library</a
			>; a snippet reads one with <code class="font-mono">getfile("&lt;uuid&gt;")</code>.
		</p>
	{/if}

	{#if locked && files.length}
		<p class="text-muted-foreground flex items-start gap-1.5 text-[11px]">
			<LockIcon class="mt-0.5 size-3 shrink-0" />
			<span>File contents require read-detail access. You can see what this definition pins —
				which file, at which version — but not download it.</span
			>
		</p>
	{/if}

	<p class="text-muted-foreground text-[11px]">
		<code class="font-mono">getfile("&lt;uuid&gt;")</code> resolves to a
		<code class="font-mono">pathlib.Path</code> at extraction time. Uploading a new version of a
		file is done in the source's library, and publishes a new version of every concept that
		references it — which is what keeps definition and data from drifting apart.
	</p>
</div>
