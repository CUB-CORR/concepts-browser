<script lang="ts">
	import { Button } from "$lib/components/ui/button";
	import { toast } from "svelte-sonner";
	import CopyIcon from "@lucide/svelte/icons/copy";
	import CheckIcon from "@lucide/svelte/icons/check";
	import ChevronDownIcon from "@lucide/svelte/icons/chevron-down";
	import ChevronUpIcon from "@lucide/svelte/icons/chevron-up";
	import { loadMonaco } from "$lib/editor/monaco";
	import { mode } from "mode-watcher";

	let { code, language = "text" }: { code: string; language?: string } = $props();

	// Long blocks are clamped to a preview so they don't push the history / new-draft
	// controls below the fold; a "Show all" toggle reveals the rest.
	const COLLAPSE_THRESHOLD = 50;
	const PREVIEW_LINES = 20;

	let copied = $state(false);
	let expanded = $state(false);
	// Monaco-tokenized HTML; null until colorized (and on failure) so we fall back to the
	// raw text and the block always renders.
	let highlighted = $state<string | null>(null);

	const lineCount = $derived(code.split("\n").length);
	const collapsible = $derived(lineCount > COLLAPSE_THRESHOLD);
	const collapsed = $derived(collapsible && !expanded);

	async function copy() {
		await navigator.clipboard.writeText(code);
		copied = true;
		toast.success("Copied to clipboard");
		setTimeout(() => (copied = false), 1500);
	}

	// Highlight with the same Monaco grammar the editor uses, so read-only code matches the
	// editor. Browser-only ($effect never runs during SSR), re-runs when code/language change.
	$effect(() => {
		const src = code;
		const lang = language;
		// colorize() bakes the active theme's colors into the returned HTML, so re-run when
		// the app switches light/dark to keep the read-only block legible on either background.
		const dark = mode.current === "dark";
		expanded = false;
		highlighted = null;
		if (lang === "text") return;
		let cancelled = false;
		(async () => {
			try {
				const monaco = await loadMonaco();
				monaco.editor.setTheme(dark ? "vs-dark" : "vs");
				const html = await monaco.editor.colorize(src, lang, { tabSize: 4 });
				if (!cancelled) highlighted = html;
			} catch {
				// leave highlighted null → raw-text fallback
			}
		})();
		return () => {
			cancelled = true;
		};
	});
</script>

<div class="flex flex-col gap-1">
	<div class="group relative">
		<div class="text-muted-foreground absolute top-2 left-3 z-10 font-mono text-[10px] uppercase">
			{language}
		</div>
		<Button
			variant="ghost"
			size="icon"
			class="absolute top-1.5 right-1.5 z-10 size-7 opacity-0 transition-opacity group-hover:opacity-100"
			title="Copy"
			onclick={copy}
		>
			{#if copied}<CheckIcon class="size-3.5" />{:else}<CopyIcon class="size-3.5" />{/if}
		</Button>
		<pre
			class="bg-muted/60 overflow-x-auto rounded-md border p-3 pt-6 text-xs leading-relaxed"
			class:overflow-y-hidden={collapsed}
			style:max-height={collapsed ? `calc(${PREVIEW_LINES}lh + 2.25rem)` : undefined}><code
				>{#if highlighted !== null}{@html highlighted}{:else}{code}{/if}</code
			></pre>
		{#if collapsed}
			<button
				type="button"
				class="text-muted-foreground hover:text-foreground from-muted absolute inset-x-0 bottom-0 flex cursor-pointer items-end justify-center gap-1 rounded-b-md bg-gradient-to-t to-transparent pt-12 pb-2 text-xs font-medium"
				onclick={() => (expanded = true)}
			>
				<ChevronDownIcon class="size-3.5" /> Show all {lineCount} lines
			</button>
		{/if}
	</div>
	{#if collapsible && expanded}
		<button
			type="button"
			class="text-muted-foreground hover:text-foreground flex cursor-pointer items-center justify-center gap-1 text-xs font-medium"
			onclick={() => (expanded = false)}
		>
			<ChevronUpIcon class="size-3.5" /> Show less
		</button>
	{/if}
</div>
