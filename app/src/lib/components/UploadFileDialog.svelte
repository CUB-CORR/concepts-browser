<script lang="ts">
	// Upload a data file into a source's library — a new one, or a new version of one that is
	// already there. A new version may also *rename* the file: the identity is the uuid, so
	// the replace control sends it along and the path is free to change.
	//
	// Replacing is the case worth stopping for: every concept whose current published config
	// reads the file gets a new published version the moment this succeeds. So before a replace
	// goes out, the dialog asks the API which concepts those are and shows them. There is no
	// ceiling — a hundred is as legitimate as one — the point is only that nobody publishes a
	// hundred versions without having been told.
	import { untrack } from "svelte";
	import { enhance } from "$app/forms";
	import { invalidateAll } from "$app/navigation";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import * as Dialog from "$lib/components/ui/dialog";
	import * as Alert from "$lib/components/ui/alert";
	import { toast } from "svelte-sonner";
	import UploadIcon from "@lucide/svelte/icons/upload";
	import LoaderIcon from "@lucide/svelte/icons/loader-circle";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import type { FileReference, FileUploadResult, SourceFileRecord } from "$lib/types";

	let {
		src,
		files = [],
		replacing = null,
		label = "Upload file",
		variant = "default",
	}: {
		src: string;
		/** The library as it stands, so a typed path can be recognised as a replacement. */
		files?: SourceFileRecord[];
		/** Fixed target: the file page's replace control. The uuid picks the file, so the path
		 *  stays editable — a new version may give it a new name. */
		replacing?: SourceFileRecord | null;
		label?: string;
		variant?: "default" | "outline" | "secondary";
	} = $props();

	let open = $state(false);
	let picked = $state<FileList | undefined>(undefined);
	let path = $state(untrack(() => replacing?.path ?? ""));
	let message = $state("");
	let busy = $state(false);
	let errorMsg = $state<string | null>(null);

	// The impact review: null until asked for, then the concepts a replace would publish.
	let refs = $state<FileReference[] | null>(null);
	let checking = $state(false);

	/** The library entry this upload would replace, if any. */
	const target = $derived(replacing ?? files.find((f) => f.path === path.trim()) ?? null);
	/** A replace is only cleared to send once its impact has been shown. */
	const needsReview = $derived(target != null && refs == null);

	function reset() {
		picked = undefined;
		path = replacing?.path ?? "";
		message = "";
		errorMsg = null;
		refs = null;
		checking = false;
		busy = false;
	}

	function retypePath(value: string) {
		path = value;
		// The impact shown belonged to the previous path; a new one has to be asked about again.
		// Not when replacing: there the uuid picks the file, so retyping renames it rather than
		// pointing the upload somewhere else, and the impact is the same either way.
		if (!replacing) refs = null;
	}

	// Prefill the path from the chosen file's name — most files are flat — while leaving it
	// editable for the ones that live in a subdirectory.
	function pick(list: FileList | null) {
		picked = list ?? undefined;
		if (!replacing && !path && list?.length) retypePath(list[0].name);
	}

	async function review() {
		if (!target) return;
		checking = true;
		errorMsg = null;
		try {
			const res = await fetch(
				`/files/${encodeURIComponent(src)}/${encodeURIComponent(target.uuid)}/references`,
			);
			if (!res.ok) throw new Error(`references lookup failed (${res.status})`);
			refs = (await res.json()) as FileReference[];
		} catch {
			errorMsg = "Could not read which concepts use this file. Try again before uploading.";
		} finally {
			checking = false;
		}
	}

	function conceptHref(r: FileReference): string {
		if (!r.taxonomy || !r.name) return `/concepts/id/${r.concept_id}`;
		return `/concepts/tax/${encodeURIComponent(r.taxonomy)}/${encodeURIComponent(r.name)}?cid=${r.concept_id}`;
	}

	function report(result: FileUploadResult) {
		const renamed = replacing != null && result.path !== replacing.path;
		if (result.unchanged) {
			toast.info(
				renamed
					? `Renamed to ${result.path} — identical bytes, so nothing was published.`
					: "Identical bytes — nothing was published.",
			);
		} else if (result.bumped?.length) {
			toast.success(
				`v${result.version_no} uploaded — published a new version of ${result.bumped.length} concept${result.bumped.length === 1 ? "" : "s"}.`,
			);
		} else {
			toast.success(`v${result.version_no} uploaded.`);
		}
	}
</script>

<Dialog.Root bind:open onOpenChange={(o) => !o && reset()}>
	<Dialog.Trigger>
		{#snippet child({ props })}
			<Button {...props} {variant} size="sm"><UploadIcon class="size-4" /> {label}</Button>
		{/snippet}
	</Dialog.Trigger>

	<Dialog.Content class="sm:max-w-lg">
		<Dialog.Header>
			<Dialog.Title>
				{#if replacing}
					New version of <span class="font-mono">{replacing.path}</span>
				{:else}
					Upload to <span class="font-mono">{src}</span>
				{/if}
			</Dialog.Title>
			<Dialog.Description>
				The file is stored against the source and versioned there. Snippets reference it by
				uuid, so replacing it never breaks a reference — it publishes a new version of every
				concept that reads it.
			</Dialog.Description>
		</Dialog.Header>

		<form
			method="POST"
			action="?/upload"
			enctype="multipart/form-data"
			class="flex flex-col gap-4"
			use:enhance={() => {
				busy = true;
				return async ({ result }) => {
					busy = false;
					if (result.type === "failure") {
						errorMsg = String((result.data as { error?: string })?.error ?? "The upload failed.");
					} else if (result.type === "success") {
						report((result.data as { uploaded: FileUploadResult }).uploaded);
						open = false;
						await invalidateAll();
					}
				};
			}}
		>
			{#if replacing}
				<input type="hidden" name="uuid" value={replacing.uuid} />
			{/if}

			<div class="flex flex-col gap-1.5">
				<Label for="upload-file">File</Label>
				<Input
					id="upload-file"
					type="file"
					name="file"
					bind:files={picked}
					onchange={(e) => pick(e.currentTarget.files)}
				/>
			</div>

			<div class="flex flex-col gap-1.5">
				<Label for="upload-path">Path</Label>
				<Input
					id="upload-path"
					name="path"
					value={path}
					oninput={(e) => retypePath(e.currentTarget.value)}
					placeholder="postcode/postcode_mapping.csv"
					class="font-mono"
				/>
				<p class="text-muted-foreground text-xs">
					{#if replacing}
						How the file is known inside this source. Changing it renames the file: the uuid
						stays what it is, so every snippet reading it is unaffected, and versions published
						before now keep the name they were published against.
					{:else}
						How the file is known inside this source. An existing path means a new version of
						that file, not a second one.
					{/if}
				</p>
			</div>

			<div class="flex flex-col gap-1.5">
				<Label for="upload-message">Message <span class="text-muted-foreground font-normal">(optional)</span></Label>
				<Input id="upload-message" name="message" bind:value={message} placeholder="what changed in this file" />
			</div>

			{#if target && refs}
				<Alert.Root>
					<TriangleAlertIcon class="size-4" />
					<Alert.Title>
						{#if refs.length === 0}
							No concept reads this file yet — nothing will be published.
						{:else}
							This will publish a new version of {refs.length} concept{refs.length === 1 ? "" : "s"}.
						{/if}
					</Alert.Title>
					{#if refs.length}
						<Alert.Description>
							<ul class="mt-1 flex flex-col gap-0.5">
								{#each refs as r (r.concept_id)}
									<li>
										<a href={conceptHref(r)} class="font-mono underline underline-offset-2">
											{r.name ?? `#${r.concept_id}`}
										</a>
										{#if r.display_name}<span class="text-muted-foreground"> — {r.display_name}</span>{/if}
									</li>
								{/each}
							</ul>
						</Alert.Description>
					{/if}
				</Alert.Root>
			{/if}

			{#if errorMsg}
				<Alert.Root variant="destructive">
					<TriangleAlertIcon class="size-4" />
					<Alert.Title>{errorMsg}</Alert.Title>
				</Alert.Root>
			{/if}

			<Dialog.Footer>
				{#if needsReview}
					<Button type="button" onclick={review} disabled={checking || !picked?.length}>
						{#if checking}<LoaderIcon class="size-4 animate-spin" />{/if}
						Review impact
					</Button>
				{:else}
					<Button type="submit" disabled={busy || !picked?.length || !path.trim()}>
						{#if busy}<LoaderIcon class="size-4 animate-spin" />{/if}
						{target ? "Upload new version" : "Upload"}
					</Button>
				{/if}
			</Dialog.Footer>
		</form>
	</Dialog.Content>
</Dialog.Root>
