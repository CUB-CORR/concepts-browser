<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { loadMonaco } from "$lib/editor/monaco";
	import { bindPythonSurface, registerPythonExtras } from "$lib/editor/python";
	import { mode } from "mode-watcher";

	let {
		value = $bindable(""),
		language = "python",
		readOnly = false,
		height = "320px",
		source = null,
	}: {
		value?: string;
		language?: string;
		readOnly?: boolean;
		height?: string;
		/** Source key whose generated Python surface drives completion. Fetched lazily, here
		 *  rather than in `load`, so the ~250 KB document never rides along with the page. */
		source?: string | null;
	} = $props();

	let container: HTMLDivElement;
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	let editor: any = null;
	let applying = false;
	let unbind: (() => void) | null = null;

	onMount(() => {
		let disposed = false;
		(async () => {
			const monaco = await loadMonaco();
			if (disposed || !container) return;
			if (language === "python") registerPythonExtras(monaco);

			editor = monaco.editor.create(container, {
				value,
				language,
				readOnly,
				theme: mode.current === "dark" ? "vs-dark" : "vs",
				minimap: { enabled: false },
				fontSize: 13,
				lineNumbers: "on",
				scrollBeyondLastLine: false,
				automaticLayout: true,
				tabSize: 4,
				renderLineHighlight: "none",
				padding: { top: 8, bottom: 8 },
			});

			if (language === "python" && source) {
				const model = editor.getModel();
				if (model) unbind = bindPythonSurface(model, source);
			}

			// Lock the `def …` signature (line 1) and the final `return …` line; only the
			// body in between stays editable.
			if (!readOnly && language === "python") {
				try {
					const { constrainedEditor } = await import("constrained-editor-plugin");
					const model = editor.getModel();
					const lines = model.getLineCount();
					if (lines >= 3) {
						const c = constrainedEditor(monaco);
						c.initializeIn(editor);
						const lastBody = lines - 1;
						c.addRestrictionsTo(model, [
							{ range: [2, 1, lastBody, model.getLineMaxColumn(lastBody)], allowMultiline: true, label: "body" },
						]);
					}
				} catch {
					// constrained editor is best-effort; a plain editor still works.
				}
			}

			editor.onDidChangeModelContent(() => {
				applying = true;
				value = editor.getValue();
				applying = false;
			});
		})();
		return () => {
			disposed = true;
		};
	});

	onDestroy(() => {
		unbind?.();
		editor?.dispose();
	});

	/** Write text where the caret is (replacing the selection, if any) and hand focus back —
	 *  what the file picker needs to drop a `getfile("…")` into the snippet being written. */
	export function insertAtCursor(text: string): void {
		if (!editor) return;
		const selection = editor.getSelection();
		if (!selection) return;
		editor.executeEdits("insert", [{ range: selection, text, forceMoveMarkers: true }]);
		editor.focus();
	}

	// Reflect external value changes (e.g. reset / seed) without clobbering live typing.
	$effect(() => {
		const v = value;
		if (editor && !applying && v !== editor.getValue()) editor.setValue(v ?? "");
	});

	// Follow the app's light/dark toggle. setTheme is global to the Monaco namespace, which is
	// fine — every editor and colorized block should track the same app mode.
	$effect(() => {
		const dark = mode.current === "dark";
		if (editor) loadMonaco().then((m) => m.editor.setTheme(dark ? "vs-dark" : "vs"));
	});
</script>

<div bind:this={container} class="w-full overflow-hidden rounded-md border" style="height: {height}"></div>
