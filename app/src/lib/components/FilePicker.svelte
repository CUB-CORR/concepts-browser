<script lang="ts">
	// Pick a data file for the snippet being written.
	//
	// A file is referenced by uuid, which is what makes a reference survive every replacement —
	// and also what makes it untypeable. So the uuid is never something a person has to handle:
	// they pick a path here and the accessor is written at the caret.
	import { Badge } from "$lib/components/ui/badge";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import * as Dialog from "$lib/components/ui/dialog";
	import { loadSourceFiles } from "$lib/editor/python";
	import { formatBytes, getfileRef } from "$lib/format";
	import PaperclipIcon from "@lucide/svelte/icons/paperclip";
	import type { SourceFileRecord } from "$lib/types";

	let {
		source,
		onpick,
	}: {
		source: string;
		/** Called with the accessor to write — `getfile("<uuid>")`. */
		onpick: (reference: string) => void;
	} = $props();

	let open = $state(false);
	let query = $state("");
	// null while loading or when the library could not be read; the two are told apart by
	// `loading`, because "no files" and "we don't know" deserve different words.
	let files = $state<SourceFileRecord[] | null>(null);
	let loading = $state(false);

	async function load() {
		loading = true;
		files = await loadSourceFiles(source);
		loading = false;
	}

	const matches = $derived.by(() => {
		const q = query.trim().toLowerCase();
		const all = [...(files ?? [])].sort((a, b) => a.path.localeCompare(b.path));
		return q ? all.filter((f) => f.path.toLowerCase().includes(q)) : all;
	});

	function choose(file: SourceFileRecord) {
		onpick(getfileRef(file.uuid));
		open = false;
		query = "";
	}
</script>

<Dialog.Root
	bind:open
	onOpenChange={(o) => {
		if (o) load();
		else query = "";
	}}
>
	<Dialog.Trigger>
		{#snippet child({ props })}
			<Button {...props} variant="outline" size="sm" class="h-7 gap-1 px-2 text-xs">
				<PaperclipIcon class="size-3.5" /> Insert file
			</Button>
		{/snippet}
	</Dialog.Trigger>

	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>Insert a data file</Dialog.Title>
			<Dialog.Description>
				Writes <code class="font-mono">getfile("&lt;uuid&gt;")</code> at the cursor. It resolves to a
				<code class="font-mono">pathlib.Path</code> at extraction time and keeps resolving when the
				file is replaced.
			</Dialog.Description>
		</Dialog.Header>

		<Input bind:value={query} placeholder="filter by path…" class="font-mono" />

		<div class="max-h-80 overflow-y-auto">
			{#if loading}
				<p class="text-muted-foreground p-3 text-sm">Loading {source}'s files…</p>
			{:else if files == null}
				<p class="text-muted-foreground p-3 text-sm">Could not read this source's file library.</p>
			{:else if matches.length === 0}
				<p class="text-muted-foreground p-3 text-sm">
					{#if files.length === 0}
						No files in
						<a href={`/files/${encodeURIComponent(source)}`} class="underline underline-offset-2">
							{source}'s library
						</a> yet.
					{:else}
						Nothing matches "{query}".
					{/if}
				</p>
			{:else}
				<ul class="flex flex-col gap-1">
					{#each matches as file (file.uuid)}
						<li>
							<button
								type="button"
								class="hover:bg-accent flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm"
								onclick={() => choose(file)}
							>
								<span class="truncate font-mono">{file.path}</span>
								<Badge variant="outline" class="ml-auto font-mono text-[10px]">v{file.version_no}</Badge>
								<span class="text-muted-foreground shrink-0 text-xs tabular-nums">
									{formatBytes(file.size)}
								</span>
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>

		<Dialog.Footer>
			<a
				href={`/files/${encodeURIComponent(source)}`}
				class="text-muted-foreground text-xs underline underline-offset-2"
			>
				Manage {source}'s files
			</a>
		</Dialog.Footer>
	</Dialog.Content>
</Dialog.Root>
