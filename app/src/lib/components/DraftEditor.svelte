<script lang="ts">
	import { enhance, applyAction } from "$app/forms";
	import { untrack } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import SchemaForm from "$lib/components/schema/SchemaForm.svelte";
	import CodeEditor from "$lib/components/CodeEditor.svelte";
	import AttachedFiles from "$lib/components/AttachedFiles.svelte";
	import FilePicker from "$lib/components/FilePicker.svelte";
	import { Button } from "$lib/components/ui/button";
	import { Input } from "$lib/components/ui/input";
	import { Label } from "$lib/components/ui/label";
	import { Badge } from "$lib/components/ui/badge";
	import { Checkbox } from "$lib/components/ui/checkbox";
	import { Textarea } from "$lib/components/ui/textarea";
	import * as Select from "$lib/components/ui/select";
	import * as Alert from "$lib/components/ui/alert";
	import * as AlertDialog from "$lib/components/ui/alert-dialog";
	import { conceptContext } from "$lib/concept-context";
	import { validate } from "$lib/schema/validate";
	import { skeleton } from "$lib/schema/skeleton";
	import { pyTemplate } from "$lib/editor/template";
	import { filePageHref } from "$lib/format";
	import { toast } from "svelte-sonner";
	import SaveIcon from "@lucide/svelte/icons/save";
	import UploadIcon from "@lucide/svelte/icons/upload";
	import CircleCheckIcon from "@lucide/svelte/icons/circle-check";
	import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";
	import Trash2Icon from "@lucide/svelte/icons/trash-2";
	import type { Draft, JsonSchema, SourceFile } from "$lib/types";

	let {
		name,
		source,
		schema,
		canPublish,
		draft,
		type,
		files = [],
	}: {
		name: string;
		source: string;
		schema: JsonSchema | null;
		canPublish: boolean;
		draft?: Draft;
		type?: string;
		/** The source files this draft's snippet references (the API resolves them on `?draft=`). */
		files?: SourceFile[];
	} = $props();

	/** The Python box, so the file picker can write at the caret rather than at the end. */
	let code = $state<ReturnType<typeof CodeEditor> | null>(null);

	// Drafts are deliberately never cascaded into: an open draft is somebody's work in progress,
	// and rewriting it under them would be worse than telling them. So a file that moved on
	// since the draft pinned it shows up here instead, and publishing re-pins it.
	const movedOn = $derived(draft?.files_changed_since_draft ?? []);
	const unresolved = $derived(draft?.unresolved_files ?? []);

	const pinnedConcept = conceptContext();

	const isEdit = $derived(!!draft);
	const effectiveType = $derived(draft?.type ?? type ?? "config");

	// Seed editor state once from props; thereafter it's owned by the editor.
	let def = $state<Record<string, unknown>>(
		untrack(() => (draft ? structuredClone($state.snapshot(draft.json)) : skeleton(schema, type))),
	);
	let py = $state(untrack(() => draft?.py ?? pyTemplate(name)));
	let message = $state(untrack(() => draft?.message ?? ""));
	let changeType = $state(untrack(() => draft?.change_type ?? "improvement"));
	let serverErrors = $state<{ path: string; message: string }[] | null>(null);

	// Default derived from change type when the publish dialog opens; the author can override.
	let notifyUsers = $state(false);

	const clientErrors = $derived(schema ? validate(schema, def) : []);
	const jsonString = $derived(JSON.stringify(def));

	let jsonRaw = $state(untrack(() => JSON.stringify(draft?.json ?? {}, null, 2)));
	function applyRaw(t: string) {
		jsonRaw = t;
		try {
			def = JSON.parse(t);
		} catch {
			/* keep last good */
		}
	}

	function onResult(result: { type: string; data?: Record<string, unknown> }, okMsg: string) {
		if (result.type === "success" || result.type === "redirect") {
			serverErrors = null;
			toast.success(okMsg);
		} else if (result.type === "failure") {
			serverErrors = (result.data?.validationErrors as typeof serverErrors) ?? null;
			toast.error(String(result.data?.error ?? "Action failed"));
		}
	}
</script>

<div
	class="flex flex-col gap-5 rounded-lg border-2 border-blue-200 bg-blue-50/30 p-4 dark:border-blue-900 dark:bg-blue-950/20"
>
	<div class="flex flex-wrap items-center gap-2">
		{#if isEdit}
			<Badge variant="default">Draft #{draft!.id}</Badge>
		{:else}
			<Badge variant="default">New config</Badge>
		{/if}
		<Badge variant="outline" class="font-mono">{effectiveType}</Badge>
		<span class="text-muted-foreground font-mono text-xs">{source}</span>
		{#if isEdit}
			<code class="text-muted-foreground ml-auto text-xs"
				>?draft={draft!.id}</code
			>
		{/if}
	</div>

	{#if serverErrors?.length}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Title>Server rejected the config</Alert.Title>
			<Alert.Description>
				<ul class="list-disc pl-4">
					{#each serverErrors as e (e.path + e.message)}
						<li><span class="font-mono">{e.path || "(root)"}</span>: {e.message}</li>
					{/each}
				</ul>
			</Alert.Description>
		</Alert.Root>
	{/if}

	<div class="flex flex-col gap-2">
		<h4 class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Definition</h4>
		{#if schema}
			<SchemaForm {schema} bind:value={def} errors={clientErrors} />
		{:else}
			<p class="text-muted-foreground text-xs">This source is not schema-governed — edit raw JSON.</p>
			<Textarea class="min-h-[220px] font-mono text-xs" value={jsonRaw} oninput={(e) => applyRaw(e.currentTarget.value)} />
		{/if}
	</div>

	{#if unresolved.length}
		<Alert.Root variant="destructive">
			<TriangleAlertIcon class="size-4" />
			<Alert.Title>
				{unresolved.length} unresolved file reference{unresolved.length === 1 ? "" : "s"}
			</Alert.Title>
			<Alert.Description>
				<p>
					These uuids name no file in <span class="font-mono">{source}</span>'s library — the
					snippet cannot run until each is a file that exists or is removed.
				</p>
				<ul class="list-disc pl-4">
					{#each unresolved as uuid (uuid)}
						<li class="font-mono text-xs">{uuid}</li>
					{/each}
				</ul>
			</Alert.Description>
		</Alert.Root>
	{/if}

	{#if movedOn.length}
		<Alert.Root>
			<TriangleAlertIcon class="size-4" />
			<Alert.Title>
				{movedOn.length} file{movedOn.length === 1 ? " has" : "s have"} a newer version
			</Alert.Title>
			<Alert.Description>
				<p>
					This draft is still pinned to the version it was written against; publishing pins the
					current one. Published configs were re-published when the file changed — this draft was
					left alone on purpose.
				</p>
				<ul class="list-disc pl-4">
					{#each movedOn as f (f.uuid)}
						<li class="text-xs">
							<a href={filePageHref(source, f.uuid)} class="font-mono underline underline-offset-2">
								{f.path ?? f.uuid}
							</a>
							— pinned v{f.pinned_version ?? "?"}, now v{f.current_version ?? "?"}
						</li>
					{/each}
				</ul>
			</Alert.Description>
		</Alert.Root>
	{/if}

	<div class="flex flex-col gap-2">
		<div class="flex flex-wrap items-center justify-between gap-2">
			<h4 class="text-muted-foreground text-xs font-semibold tracking-wide uppercase">Python</h4>
			<div class="flex items-center gap-2">
				<span class="text-muted-foreground text-[11px]">
					Completion knows names, signatures and docstrings — not what a chained expression
					evaluates to.
				</span>
				<FilePicker {source} onpick={(ref) => code?.insertAtCursor(ref)} />
			</div>
		</div>
		<AttachedFiles {files} {source} />
		<CodeEditor bind:this={code} bind:value={py} language="python" {source} />
	</div>

	<div class="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_180px]">
		<div class="flex flex-col gap-1.5">
			<Label class="text-xs">Message</Label>
			<Input bind:value={message} placeholder="what changed and why" />
		</div>
		<div class="flex flex-col gap-1.5">
			<Label class="text-xs">Change type</Label>
			<Select.Root type="single" bind:value={changeType}>
				<Select.Trigger class="w-full">{changeType}</Select.Trigger>
				<Select.Content>
					<Select.Item value="improvement">improvement</Select.Item>
					<Select.Item value="critical">critical</Select.Item>
				</Select.Content>
			</Select.Root>
		</div>
	</div>

	{#if clientErrors.length}
		<p class="text-destructive text-xs">{clientErrors.length} validation issue(s) — see fields above.</p>
	{/if}

	<div class="flex items-center gap-2">
		{#if isEdit}
			<form method="POST" action="?/saveDraft" use:enhance={() => async ({ result }) => {
				onResult(result, "Draft saved");
				if (result.type === "success") await invalidateAll();
			}}>
				<input type="hidden" name="cid" value={pinnedConcept.id} />
				<input type="hidden" name="draftId" value={draft!.id} />
				<input type="hidden" name="json" value={jsonString} />
				<input type="hidden" name="py" value={py} />
				<input type="hidden" name="message" value={message} />
				<input type="hidden" name="change_type" value={changeType} />
				<Button type="submit"><SaveIcon class="size-4" /> Save draft</Button>
			</form>
		{:else}
			<form method="POST" action="?/createDraft" use:enhance={() => async ({ result }) => {
				onResult(result, "Draft created");
				await applyAction(result); // follow the redirect to ?draft=… so the new draft opens
			}}>
				<input type="hidden" name="cid" value={pinnedConcept.id} />
				<input type="hidden" name="source" value={source} />
				<input type="hidden" name="empty" value="true" />
				<input type="hidden" name="type" value={effectiveType} />
				<input type="hidden" name="json" value={jsonString} />
				<input type="hidden" name="py" value={py} />
				<input type="hidden" name="message" value={message} />
				<input type="hidden" name="change_type" value={changeType} />
				<Button type="submit"><SaveIcon class="size-4" /> Create draft</Button>
			</form>
		{/if}

		{#if isEdit && canPublish}
			<AlertDialog.Root onOpenChange={(open) => { if (open) notifyUsers = changeType === "critical"; }}>
				<AlertDialog.Trigger>
					{#snippet child({ props })}
						<Button variant="outline" {...props}><UploadIcon class="size-4" /> Publish</Button>
					{/snippet}
				</AlertDialog.Trigger>
				<AlertDialog.Content>
					<AlertDialog.Header>
						<AlertDialog.Title>Publish draft #{draft!.id}?</AlertDialog.Title>
						<AlertDialog.Description>
							This assigns the next version and makes it the active config for
							<span class="font-mono">{source}</span>. Save your edits first — publish uses the last
							saved draft.
						</AlertDialog.Description>
					</AlertDialog.Header>
					<form method="POST" action="?/publishDraft" use:enhance={() => async ({ result }) => {
						onResult(result, "Published");
						await applyAction(result); // follow redirect → closes the dialog and shows the new version
					}}>
						<input type="hidden" name="cid" value={pinnedConcept.id} />
						<input type="hidden" name="draftId" value={draft!.id} />
						<input type="hidden" name="source" value={source} />
						<input type="hidden" name="message" value={message} />
						<input type="hidden" name="change_type" value={changeType} />
						<input type="hidden" name="notify" value={notifyUsers ? "true" : "false"} />
						<div class="flex items-start gap-3 py-2">
							<Checkbox id="publish-notify" bind:checked={notifyUsers} />
							<div class="grid gap-1">
								<Label for="publish-notify" class="font-normal">
									Notify users and project leads by email
								</Label>
								<p class="text-muted-foreground text-xs">
									Emails everyone who has used this concept and the leads of projects it was used in.
								</p>
							</div>
						</div>
						<AlertDialog.Footer>
							<AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
							<AlertDialog.Action type="submit">Publish</AlertDialog.Action>
						</AlertDialog.Footer>
					</form>
				</AlertDialog.Content>
			</AlertDialog.Root>
		{/if}

		{#if isEdit}
			<AlertDialog.Root>
				<AlertDialog.Trigger>
					{#snippet child({ props })}
						<Button
							variant="ghost"
							{...props}
							class="text-destructive hover:bg-destructive/10 hover:text-destructive"
						>
							<Trash2Icon class="size-4" /> Discard
						</Button>
					{/snippet}
				</AlertDialog.Trigger>
				<AlertDialog.Content>
					<AlertDialog.Header>
						<AlertDialog.Title>Discard draft #{draft!.id}?</AlertDialog.Title>
						<AlertDialog.Description>
							This permanently deletes the unpublished draft for
							<span class="font-mono">{source}</span>. Published versions are unaffected. This cannot be
							undone.
						</AlertDialog.Description>
					</AlertDialog.Header>
					<form method="POST" action="?/deleteDraft" use:enhance={() => async ({ result }) => {
						onResult(result, "Draft discarded");
						await applyAction(result); // follow redirect → closes the editor, back to published view
					}}>
						<input type="hidden" name="cid" value={pinnedConcept.id} />
						<input type="hidden" name="draftId" value={draft!.id} />
						<input type="hidden" name="source" value={source} />
						<AlertDialog.Footer>
							<AlertDialog.Cancel>Cancel</AlertDialog.Cancel>
							<AlertDialog.Action type="submit" class="bg-destructive text-white hover:bg-destructive/90">
								Discard draft
							</AlertDialog.Action>
						</AlertDialog.Footer>
					</form>
				</AlertDialog.Content>
			</AlertDialog.Root>
		{/if}

		<div class="ml-auto flex items-center gap-1 text-xs text-green-700 dark:text-green-400">
			{#if schema && !clientErrors.length}<CircleCheckIcon class="size-3.5" /> schema valid{/if}
		</div>
	</div>
</div>
